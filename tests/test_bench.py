import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ragcompass import bench
from ragcompass.analyze import run_analysis
from ragcompass.bench import BM25, Bootstrap, IndexedChunk, Query, coverage, rrf, score_query, span_recall
from ragcompass.tokens import RegexTokenizer
from tests.conftest import CORPUS

EVALSMITH = Path(__file__).resolve().parents[2] / "evalsmith-mcp" / "dist" / "cli" / "index.js"


@pytest.fixture(scope="module")
def analysis():
    return run_analysis(CORPUS, tokenizer=RegexTokenizer())


@pytest.fixture(scope="module")
def bm25_run(analysis):
    return bench.run_bench(analysis, queries=30, seed=7, dense=False)


def chunk(start, end, file="a.md", index=0):
    return IndexedChunk(file, index, start, end, "")


def test_span_metrics_by_hand():
    query = Query("q1", "x", "a.md", 100, 200)  # a 100-character source span
    first, second, other = chunk(50, 150), chunk(140, 260, index=1), chunk(0, 500, file="b.md", index=2)
    assert coverage(first, query) == 0.5
    assert coverage(other, query) == 0.0
    assert span_recall([first, second], query) == 1.0  # union covers 100..200
    assert span_recall([first], query) == 0.5
    scored = score_query([other, first, second], [first, second, other], query, k=3)
    assert scored["mrr"] == 0.5  # first overlapping chunk at rank 2
    assert scored["recall"][1] == 0.0 and scored["recall"][3] == 1.0
    # gains [0, 0.5, 0.6] against the ideal [0.6, 0.5]
    dcg = 0.5 / 1.584962500721156 + 0.6 / 2
    idcg = 0.6 + 0.5 / 1.584962500721156
    assert scored["ndcg"] == pytest.approx(dcg / idcg)


def test_bm25_and_rrf():
    index = BM25(["fan assembly HX-FAN-118", "air filter cleaning", "relay RLY-4471-B contact"])
    assert index.search("replace the relay", 3)[0] == 2
    assert index.search("nothing matches", 3) == []
    assert rrf([[0, 1], [1, 2]], 3)[0] == 1  # the only document both retrievers return wins the fusion


def test_bootstrap_is_seeded():
    values = [1.0, 0.0, 1.0, 1.0, 0.5]
    first, second = Bootstrap(5, seed=3).interval(values), Bootstrap(5, seed=3).interval(values)
    assert first == second
    assert first.ci[0] <= first.mean <= first.ci[1]


def test_queries_are_deterministic_and_point_to_their_source(analysis):
    queries = bench.generate_queries(analysis, 20, seed=5)
    assert queries == bench.generate_queries(analysis, 20, seed=5)
    assert queries != bench.generate_queries(analysis, 20, seed=6)
    for query in queries:
        source = analysis.docs[query.file].layout.text[query.start : query.end]
        assert source.strip() and query.text


def test_candidates_compare_strategies(analysis):
    found = bench.candidates(analysis, "documents")
    assert found[0].recommended
    assert len({c.strategy for c in found}) >= 2


def test_bm25_only_bench(bm25_run):
    result = bm25_run.result
    assert result.retrievers == ["bm25"]
    assert result.dense_model is None
    assert len(result.configs) == 3
    for config in result.configs:
        assert config.ndcg.ci[0] <= config.ndcg.mean <= config.ndcg.ci[1]
        assert 0 <= config.recall_at_k.mean <= 1
    hybrid = next(d for d in result.decisions if d.key == "retrieval.hybrid_bm25")
    assert hybrid.basis == "rule-based" and not hybrid.changed
    assert {d.key for d in result.decisions} == {
        "chunking.documents",
        "retrieval.hybrid_bm25",
        "retrieval.top_k",
    }


def test_bench_is_reproducible(analysis, bm25_run):
    again = bench.run_bench(analysis, queries=30, seed=7, dense=False).result
    strip = lambda r: [(c.label, c.recall_at_k, c.mrr, c.ndcg) for c in r.configs]  # noqa: E731
    assert strip(again) == strip(bm25_run.result)


def test_measurement_overrides_rule(analysis, bm25_run, monkeypatch):
    # Make the second candidate perfect and the recommended one poor: the measurement must win.
    run = bm25_run
    for entry in run.entries:
        for scores in entry.per_query:
            scores["ndcg"] = 0.2 if entry.candidate.recommended else 1.0
    boot = Bootstrap(len(run.queries), 7)
    configs = [bench._config(e, run.result.k, boot) for e in run.entries]
    _, measured, decisions = bench._decide(
        analysis, run.entries, configs, ["bm25"], run.result.k, boot, len(run.queries)
    )
    chunking = next(d for d in decisions if d.key == "chunking.documents")
    assert chunking.changed and chunking.basis == "measured"
    assert chunking.measured_value != chunking.rule_value
    assert "measurement wins" in chunking.reason


def test_apply_marks_measured_recommendations():
    fresh = run_analysis(CORPUS, tokenizer=RegexTokenizer())
    run = bench.run_bench(fresh, queries=20, seed=3, dense=False)
    bench.apply(fresh, run)
    report = fresh.report
    assert report.bench["queries"] == 20
    basis = {r.key: r.basis for r in report.recommendations}
    assert basis["chunking.documents"] == "measured"
    assert basis["retrieval.top_k"] == "measured"
    assert basis["retrieval.hybrid_bm25"] == "rule-based"  # dense not measured
    top_k = next(r for r in report.recommendations if r.key == "retrieval.top_k")
    assert "Benchmark" in top_k.reason and "Benchmark" in top_k.reason_i18n["es"]


def test_evalsmith_export(tmp_path, bm25_run):
    out = bench.export_evalsmith(bm25_run, tmp_path / "evals")
    suite = yaml.safe_load((out / "evalsmith.yaml").read_text())
    qrels = json.loads((out / suite["retrieval"]["qrels"]).read_text())
    run = json.loads((out / suite["retrieval"]["run"]).read_text())
    assert set(qrels) == set(run) == {q.id for q in bm25_run.queries}
    assert all(grade in (1, 2) for judged in qrels.values() for grade in judged.values())
    assert all(0 <= gate <= 1 for gate in suite["gates"].values())
    if EVALSMITH.exists() and shutil.which("node"):
        done = subprocess.run(
            ["node", str(EVALSMITH), "run", str(out / "evalsmith.yaml")], capture_output=True, text=True
        )
        assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.skipif(not bench.embeddings.available(), reason="bench extra not installed")
def test_dense_bench_when_models_are_cached(analysis):
    model = bench.embeddings.model_for(bench._languages(analysis))
    name = model.split("/")[-1]
    if not any(name in path.name for path in bench.embeddings.CACHE_DIR.glob("models--*")):
        pytest.skip("embedding model not downloaded")
    result = bench.run_bench(analysis, queries=20, seed=1).result
    assert result.retrievers == ["bm25", "dense", "hybrid"]
    assert result.dense_model == model


def test_missing_extra_is_reported(analysis, monkeypatch):
    monkeypatch.setattr(bench.embeddings, "available", lambda: False)
    result = bench.run_bench(analysis, queries=10, seed=2).result
    assert result.retrievers == ["bm25"]
    assert any("bench extra" in w for w in result.warnings)
