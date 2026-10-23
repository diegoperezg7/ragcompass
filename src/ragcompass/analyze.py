"""Pipeline: ingest -> profile -> simulate -> rules -> report."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ragcompass import __version__
from ragcompass.ingest import extract, iter_files
from ragcompass.layout import Layout
from ragcompass.models import CorpusSummary, DocKind, Report
from ragcompass.profile import build_profile
from ragcompass.rules import recommend
from ragcompass.simulate import Doc, simulate
from ragcompass.tokens import Tokenizer, get_tokenizer


@dataclass
class Analysis:
    """A report plus the parsed documents behind it, keyed by relative path."""

    report: Report
    docs: dict[str, Doc]


def analyze(path: str | Path, tokenizer: Tokenizer | None = None, label: str | None = None) -> Report:
    return run_analysis(path, tokenizer, label).report


def run_analysis(path: str | Path, tokenizer: Tokenizer | None = None, label: str | None = None) -> Analysis:
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"{root} does not exist")
    tokenizer = tokenizer or get_tokenizer()
    base = root if root.is_dir() else root.parent

    profiles = []
    docs = []
    for file in iter_files(root):
        extracted = extract(file)
        layout = Layout(extracted.blocks, tokenizer)
        relative = file.relative_to(base).as_posix()
        profiles.append(build_profile(relative, file.stat().st_size, extracted, layout))
        if not extracted.error:
            docs.append(Doc(kind=extracted.kind, layout=layout, path=relative))

    simulations = simulate(docs)
    plan = recommend(profiles, docs, simulations)
    analysed = [p for p in profiles if not p.error and p.kind != DocKind.UNSUPPORTED]
    languages: Counter[str] = Counter(p.language for p in analysed if p.language)
    summary = CorpusSummary(
        root=label or root.name,
        files=len(profiles),
        analysed=len(analysed),
        tokens=sum(p.tokens for p in analysed),
        pages=sum(p.pages or 0 for p in analysed),
        kinds=dict(Counter(p.kind.value for p in profiles).most_common()),
        languages=dict(languages.most_common()),
        tokenizer=tokenizer.name,
    )
    config = {
        "version": 1,
        "generator": f"ragcompass {__version__}",
        "corpus": {"root": summary.root, "files": summary.analysed, "tokens": summary.tokens},
        **plan.config,
    }
    report = Report(
        version=__version__,
        summary=summary,
        documents=profiles,
        simulations=simulations,
        recommendations=plan.recommendations,
        index=plan.index,
        costs=plan.costs,
        config=config,
    )
    return Analysis(report=report, docs={doc.path: doc for doc in docs})
