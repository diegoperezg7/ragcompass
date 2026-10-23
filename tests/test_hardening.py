"""Store expiry, embedding cache bounds, MCP isolation and host warning, projection degeneracy."""

import asyncio
import time

import pytest

from ragcompass.analyze import run_analysis
from ragcompass.store import AnalysisStore
from ragcompass.tokens import RegexTokenizer
from tests.conftest import CORPUS


def test_store_purges_expired_entries_on_put_and_get():
    store = AnalysisStore(max_items=10, ttl=0.05)
    first = run_analysis(CORPUS / "onboarding-handbook.md", tokenizer=RegexTokenizer())
    store.put(first)
    time.sleep(0.1)
    second = run_analysis(CORPUS / "hx200-faq.html", tokenizer=RegexTokenizer())
    store.put(second)  # purges the expired first entry
    assert len(store) == 1
    time.sleep(0.1)
    assert store.get(second.report.id) is None
    assert len(store) == 0


def test_embedding_cache_is_bounded():
    np = pytest.importorskip("numpy")
    from ragcompass.embeddings import Embedder

    embedder = Embedder.__new__(Embedder)  # no model: _compute is replaced below
    from collections import OrderedDict

    embedder._cache, embedder.cache_entries, embedder.windowed = OrderedDict(), 3, 0
    embedder._compute = lambda texts: [np.ones(4, dtype=np.float32) for _ in texts]
    embedder.embed([f"text {i}" for i in range(10)])
    assert len(embedder._cache) == 3
    embedder.embed(["uncached"], cache=False)
    assert "uncached" not in embedder._cache


def test_mcp_benchmark_does_not_touch_the_cached_analysis():
    from mcp.client import Client

    from ragcompass.mcp_server import Workspace, build_server

    workspace = Workspace([CORPUS.parent])
    server = build_server(workspace)

    async def go():
        async with Client(server) as client:
            await client.call_tool("recommend_config", {"path": "corpus"})
            await client.call_tool("run_benchmark", {"path": "corpus", "queries": 6, "dense": False})
            return await client.call_tool("recommend_config", {"path": "corpus"})

    after = asyncio.run(go()).structured_content
    assert {r["basis"] for r in after["recommendations"]} == {"rule-based"}
    cached = workspace.analysis("corpus")
    assert cached.report.bench is None


def test_mcp_http_warns_on_public_host(monkeypatch, capsys):
    from ragcompass import mcp_server

    class Fake:
        def run(self, *args, **kwargs):
            self.called = kwargs

    monkeypatch.setattr(mcp_server, "build_server", lambda workspace: Fake())
    mcp_server.serve("http", host="0.0.0.0", port=1, roots=[CORPUS])
    assert "no authentication" in capsys.readouterr().err
    mcp_server.serve("http", host="127.0.0.1", port=1, roots=[CORPUS])
    assert capsys.readouterr().err == ""


def test_projection_flattens_a_degenerate_second_axis(monkeypatch):
    np = pytest.importorskip("numpy")
    from ragcompass import embeddings, projection

    class LineEmbedder:
        name = "line"

        def embed(self, texts, cache=True):
            # every chunk on one line: the second principal component carries no variance
            return np.array([[float(i), 2.0 * i, 0.0] for i in range(len(texts))], dtype=np.float32)

    monkeypatch.setattr(embeddings, "available", lambda: True)
    monkeypatch.setattr(embeddings, "get_embedder", lambda model: LineEmbedder())
    analysis = run_analysis(CORPUS, tokenizer=RegexTokenizer())
    result = projection.project(analysis, queries=False)
    assert result["explained_variance"][1] < projection.FLAT_VARIANCE
    assert all(p["y"] == 0.0 for p in result["points"])
