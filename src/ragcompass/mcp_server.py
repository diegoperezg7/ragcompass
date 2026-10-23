"""MCP server: the same analysis, benchmark and export as the CLI, as tools for an assistant.

Paths are read from the local disk, so they must sit under an allowed root: the working
directory by default, or the folders given with ``--root`` / ``RAGCOMPASS_MCP_ROOTS``.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ragcompass import __version__
from ragcompass.analyze import Analysis, run_analysis
from ragcompass.ingest import iter_files
from ragcompass.report import localize

CACHE_ITEMS = 8
Lang = Literal["en", "es"]

INSTRUCTIONS = """ragcompass profiles a document corpus and recommends how to configure retrieval-augmented
generation, with a reason and measured figures for every setting. Start with analyze_corpus or
recommend_config on a folder; run_benchmark measures retrieval with generated queries and can overrule
the rules; export_config returns ragcompass.yaml or LangChain, LlamaIndex or Haystack code."""


class Workspace:
    """Allowed roots plus a small cache of analyses, invalidated when files change."""

    def __init__(self, roots: list[Path] | None = None) -> None:
        env = os.environ.get("RAGCOMPASS_MCP_ROOTS")
        default = [Path(p) for p in env.split(os.pathsep) if p] if env else [Path.cwd()]
        self.roots = [r.expanduser().resolve() for r in (roots or default)]
        self._cache: OrderedDict[tuple, Analysis] = OrderedDict()
        self._lock = threading.Lock()

    def resolve(self, path: str) -> Path:
        target = Path(path).expanduser()
        target = (target if target.is_absolute() else self.roots[0] / target).resolve()
        if not any(target == root or root in target.parents for root in self.roots):
            raise ToolError(f"{path} is outside the allowed roots: {', '.join(map(str, self.roots))}")
        if not target.exists():
            raise ToolError(f"{path} does not exist")
        return target

    def analysis(self, path: str, fresh: bool = False) -> Analysis:
        target = self.resolve(path)
        signature = tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in iter_files(target))
        key = (str(target), signature)
        with self._lock:
            if not fresh and key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        analysis = run_analysis(target)
        with self._lock:
            self._cache[key] = analysis
            while len(self._cache) > CACHE_ITEMS:
                self._cache.popitem(last=False)
        return analysis


def _recommendations(analysis: Analysis, lang: str) -> list[dict[str, Any]]:
    localize(analysis.report, lang)
    return [
        {"key": r.key, "value": r.value, "basis": r.basis, "reason": r.reason}
        for r in analysis.report.recommendations
    ]


def build_server(workspace: Workspace | None = None) -> MCPServer:
    workspace = workspace or Workspace()
    server = MCPServer("ragcompass", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(title="Analyse a corpus")
    def analyze_corpus(path: str, lang: Lang = "en") -> dict[str, Any]:
        """Profile every file under `path` (type, pages, tokens, language, structure, identifiers),
        simulate chunking strategies and return the recommendations with their reasons."""
        analysis = workspace.analysis(path)
        report = analysis.report
        chosen = {
            (r.key.split(".", 1)[1], r.value["strategy"], r.value["size"], r.value["overlap"])
            for r in report.recommendations
            if r.key.startswith("chunking.")
        }
        return {
            "summary": report.summary.model_dump(),
            "documents": [
                {
                    "path": d.path,
                    "kind": d.kind.value,
                    "pages": d.pages,
                    "tokens": d.tokens,
                    "language": d.language,
                    "headings": d.headings,
                    "tables": d.tables,
                    "images": d.images,
                    "identifiers_per_1k": d.identifiers.per_1k_tokens,
                    "error": d.error,
                }
                for d in report.documents
            ],
            "chosen_chunking": [
                s.model_dump(exclude={"histogram"})
                for s in report.simulations
                if (s.group, s.strategy, s.size, s.overlap) in chosen
            ],
            "recommendations": _recommendations(analysis, lang),
        }

    @server.tool(title="Recommend a RAG configuration")
    def recommend_config(path: str, lang: Lang = "en") -> dict[str, Any]:
        """The ragcompass.yaml configuration for `path` and the reason behind every setting."""
        analysis = workspace.analysis(path)
        return {"config": analysis.report.config, "recommendations": _recommendations(analysis, lang)}

    @server.tool(title="Benchmark retrieval")
    def run_benchmark(
        path: str,
        queries: int = 60,
        seed: int = 13,
        k: int | None = None,
        dense: bool = True,
        lang: Lang = "en",
    ) -> dict[str, Any]:
        """Measure retrieval on `path` with seeded synthetic queries: the recommended chunking against
        the next candidates, with BM25, dense and hybrid retrieval. Returns recall@k, MRR and nDCG with
        bootstrap intervals and the settings the measurement confirmed or changed."""
        from ragcompass import bench

        if not 1 <= queries <= 500:
            raise ToolError("queries must be between 1 and 500")
        analysis = workspace.analysis(path, fresh=True)  # the benchmark rewrites the stored report
        try:
            run = bench.run_bench(analysis, queries, seed, k, "template", dense)
        except ValueError as exc:  # no text to make queries from
            raise ToolError(str(exc)) from exc
        bench.apply(analysis, run)
        result = run.result.model_dump()
        for decision in result["decisions"]:
            decision["reason"] = decision["reason_i18n"].get(lang, decision["reason"])
            del decision["reason_i18n"], decision["reason_parts"]
        return {
            "bench": result,
            "config": analysis.report.config,
            "recommendations": _recommendations(analysis, lang),
        }

    @server.tool(title="Export the configuration")
    def export_config(
        path: str,
        target: Literal["yaml", "langchain", "llamaindex", "haystack"] = "yaml",
        measured: bool = False,
    ) -> dict[str, Any]:
        """ragcompass.yaml or a ready-to-paste LangChain, LlamaIndex or Haystack snippet for `path`.
        With `measured`, the benchmark runs first and its values are used."""
        from ragcompass import bench
        from ragcompass.exporters import FILENAMES, export

        analysis = workspace.analysis(path, fresh=measured)
        if measured:
            bench.apply(analysis, bench.run_bench(analysis))
        return {"target": target, "filename": FILENAMES[target], "content": export(analysis.report, target)}

    return server


def serve(
    transport: str = "stdio", host: str = "127.0.0.1", port: int = 8461, roots: list[Path] | None = None
) -> None:
    server = build_server(Workspace(roots))
    if transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=host, port=port, stateless_http=True)
