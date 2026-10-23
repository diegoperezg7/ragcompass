import copy
import json
import random
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ragcompass import bench
from ragcompass.analyze import run_analysis
from ragcompass.bench import (
    BM25,
    Bootstrap,
    IndexedChunk,
    Query,
    budget_recall,
    coverage,
    rrf,
    score_query,
    span_recall,
)
from ragcompass.tokens import RegexTokenizer
from tests.conftest import CORPUS

EVALSMITH = Path(__file__).resolve().parents[2] / "evalsmith-mcp" / "dist" / "cli" / "index.js"
LOG2_3 = 1.584962500721156


@pytest.fixture(scope="module")
def analysis():
    return run_analysis(CORPUS, tokenizer=RegexTokenizer())


@pytest.fixture(scope="module")
def bm25_run(analysis):
    return bench.run_bench(analysis, queries=30, seed=7, dense=False)


def chunk(start, end, file="a.md", index=0, tokens=100):
    return IndexedChunk(file, index, start, end, "", tokens)


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
    # marginal gains [0, 0.5, 0.5]; the ideal takes 140..260 first (0.6), then 50..150 adds 0.4
    dcg = 0.5 / LOG2_3 + 0.5 / 2
    idcg = 0.6 + 0.4 / LOG2_3
    assert scored["ndcg"] == pytest.approx(dcg / idcg)


def test_ndcg_is_one_when_the_first_chunk_covers_the_span():
    query = Query("q1", "x", "a.md", 100, 200)
    whole, duplicate = chunk(0, 300), chunk(50, 250, index=1)  # overlapping chunks both contain the span
    assert score_query([whole, duplicate], [whole, duplicate], query, k=5)["ndcg"] == pytest.approx(1.0)


def test_budget_recall_charges_large_chunks():
    query = Query("q1", "x", "a.md", 900, 1000)
    big = [chunk(0, 600, tokens=600), chunk(600, 1200, index=1, tokens=600)]
    small = [chunk(0, 300, tokens=300), chunk(900, 1000, index=1, tokens=100)]
    assert span_recall(big, query) == 1.0
    assert budget_recall(big, query, budget=1000) == 0.0  # the second big chunk does not fit
    assert budget_recall(small, query, budget=1000) == 1.0


def test_bm25_and_rrf():
    index = BM25(["fan assembly HX-FAN-118", "air filter cleaning", "relay RLY-4471-B contact"])
    assert index.search("replace the relay", 3)[0] == 2
    assert index.search("nothing matches", 3) == []
    assert rrf([[0, 1], [1, 2]], 3)[0] == 1  # the only document both retrievers return wins the fusion


def test_bootstrap_is_seeded_and_bonferroni_widens():
    values = [1.0, 0.0, 1.0, 1.0, 0.5, 0.2, 0.9]
    first, second = Bootstrap(7, seed=3).interval(values), Bootstrap(7, seed=3).interval(values)
    assert first == second
    assert first.ci[0] <= first.mean <= first.ci[1]
    boot = Bootstrap(7, seed=3)
    zeros = [0.0] * 7
    one, three = boot.difference(values, zeros, 1), boot.difference(values, zeros, 3)
    assert three.ci[0] <= one.ci[0] and three.ci[1] >= one.ci[1]


def test_lexical_overlap_is_measured_on_the_query():
    idf = {"fan": 2.0, "assembly": 2.0, "replace": 1.0, "warranty": 3.0}
    source = "Replace the fan assembly when the warning appears."
    assert bench.lexical_overlap("fan assembly", source, idf) == 1.0  # every query word is copied
    assert bench.lexical_overlap("warranty fan", source, idf) == pytest.approx(2 / 5)
    # template words and function words do not count
    assert bench.lexical_overlap("What does the documentation say about fan?", source, idf) == 1.0


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
    assert result.budget_tokens == bench.BUDGET_TOKENS
    assert len(result.configs) == 3
    for config in result.configs:
        assert config.ndcg.ci[0] <= config.ndcg.mean <= config.ndcg.ci[1]
        assert 0 <= config.recall_at_k.mean <= 1 and 0 <= config.recall_at_budget.mean <= 1
    retriever = next(d for d in result.decisions if d.key == "retrieval.retriever")
    assert retriever.basis == "rule-based" and not retriever.changed
    assert {d.key for d in result.decisions} == {
        "chunking.documents",
        "retrieval.retriever",
        "retrieval.top_k",
    }
    assert result.query_kinds == {"keyphrase": 10, "masked": 10, "question": 10}
    # template queries copy their words from the source, and the benchmark says so
    assert result.lexical_overlap["mean"] >= bench.OVERLAP_WARNING
    assert any("copied from their source" in w for w in result.warnings)
    assert any("approximate real ones" in w for w in result.warnings)


def test_bench_is_reproducible(analysis, bm25_run):
    again = bench.run_bench(analysis, queries=30, seed=7, dense=False).result
    strip = lambda r: [(c.label, c.recall_at_k, c.recall_at_budget, c.mrr, c.ndcg) for c in r.configs]  # noqa: E731
    assert strip(again) == strip(bm25_run.result)


def _decide(analysis, run, entries, retrievers=("bm25",), overlap=0.0):
    boot = Bootstrap(len(run.queries), 7)
    warnings = []
    _, measured, decisions = bench._decide(
        analysis, entries, [], list(retrievers), run.result.k, boot, len(run.queries), overlap, warnings
    )
    return measured, {d.key: d for d in decisions}, warnings


def test_measurement_overrides_rule(analysis, bm25_run):
    # The second candidate recovers the whole span within the budget, the recommended one little of it.
    entries = copy.deepcopy(bm25_run.entries)
    rng = random.Random(1)
    for entry in entries:
        for scores in entry.per_query:
            base = 0.2 if entry.candidate.recommended else 0.9
            scores["budget"] = base + rng.uniform(-0.05, 0.05)
    _, decisions, _ = _decide(analysis, bm25_run, entries)
    chunking = decisions["chunking.documents"]
    assert chunking.changed and chunking.basis == "measured"
    assert chunking.measured_value != chunking.rule_value
    assert "measurement wins" in chunking.reason and "Bonferroni" in chunking.reason


def test_no_significant_winner_keeps_the_rule(analysis, bm25_run):
    entries = copy.deepcopy(bm25_run.entries)
    rng = random.Random(2)
    for entry in entries:
        for scores in entry.per_query:
            scores["budget"] = 0.5 + rng.uniform(-0.3, 0.3)  # same distribution for every chunking
    _, decisions, _ = _decide(analysis, bm25_run, entries)
    assert decisions["chunking.documents"].basis == "rule-based"
    assert not decisions["chunking.documents"].changed


def _retriever_entries(run, scores, noise=0.05):
    rng = random.Random(3)
    entries = []
    for entry in run.entries:
        for retriever in ("bm25", "dense", "hybrid"):
            per_query = [
                dict(q, ndcg=scores[retriever] + rng.uniform(-noise, noise)) for q in entry.per_query
            ]
            entries.append(
                bench.Entry(entry.candidate, retriever, entry.chunks, entry.runs, per_query, 1.0, [1.0])
            )
    return entries


def _retriever(analysis, run, scores, overlap=0.0):
    measured, decisions, warnings = _decide(
        analysis, run, _retriever_entries(run, scores), ("bm25", "dense", "hybrid"), overlap
    )
    return SimpleNamespace(m=measured["retrieval.retriever"], d=decisions["retrieval.retriever"], w=warnings)


def test_retriever_decision_cites_all_three(analysis, bm25_run):
    clear = _retriever(analysis, bm25_run, {"bm25": 0.9, "dense": 0.5, "hybrid": 0.6})
    assert clear.m.value == "bm25" and clear.m.basis == "measured"
    import re

    cited = dict(re.findall(r"(bm25|dense|hybrid) (0\.\d+)", clear.d.reason))
    assert set(cited) == {"bm25", "dense", "hybrid"}
    assert float(cited["bm25"]) > float(cited["hybrid"]) > float(cited["dense"])


def test_retriever_tie_keeps_the_rule(analysis, bm25_run):
    # the rule says hybrid (the sample corpus is identifier-dense); hybrid ties with BM25
    tie = _retriever(analysis, bm25_run, {"bm25": 0.9, "dense": 0.5, "hybrid": 0.9})
    assert tie.m.value == "hybrid" and tie.m.basis == "rule-based"
    assert "within noise" in tie.d.reason


def test_retriever_never_returns_a_significant_loser(analysis, bm25_run):
    # hybrid (the rule) loses to both single retrievers, which tie: the choice comes from those two
    lost = _retriever(analysis, bm25_run, {"bm25": 0.9, "dense": 0.89, "hybrid": 0.5})
    assert lost.m.value in ("bm25", "dense") and lost.m.changed
    assert "loses to" in lost.d.reason


def test_copied_query_words_make_bm25_ineligible(analysis, bm25_run):
    lexical = _retriever(analysis, bm25_run, {"bm25": 0.95, "dense": 0.5, "hybrid": 0.7}, overlap=0.9)
    assert lexical.m.value != "bm25"
    assert "not eligible" in lexical.d.reason


def _with_recall(run, curve):
    entries = copy.deepcopy(run.entries)
    for entry in entries:
        for scores in entry.per_query:
            scores["recall"] = dict(curve)
    return entries


def test_top_k_can_go_up(analysis, bm25_run):
    curve = {cut: min(1.0, cut / 8) for cut in range(1, 11)}  # recall grows until k = 8
    measured, decisions, _ = _decide(analysis, bm25_run, _with_recall(bm25_run, curve))
    assert measured["retrieval.top_k"].value == 8
    assert decisions["retrieval.top_k"].changed


def test_top_k_without_recall_is_not_decided(analysis, bm25_run):
    curve = dict.fromkeys(range(1, 11), 0.0)
    measured, decisions, warnings = _decide(analysis, bm25_run, _with_recall(bm25_run, curve))
    assert decisions["retrieval.top_k"].basis == "rule-based"
    assert any("top 10" in w for w in warnings)


def test_apply_marks_measured_recommendations():
    fresh = run_analysis(CORPUS, tokenizer=RegexTokenizer())
    run = bench.run_bench(fresh, queries=20, seed=3, dense=False)
    bench.apply(fresh, run)
    report = fresh.report
    assert report.bench["queries"] == 20
    basis = {r.key: r.basis for r in report.recommendations}
    assert basis["retrieval.hybrid_bm25"] == "rule-based"  # dense not measured
    assert basis["retrieval.retriever"] == "rule-based"
    assert basis["chunking.documents"] in ("rule-based", "measured")
    top_k = next(r for r in report.recommendations if r.key == "retrieval.top_k")
    assert "Benchmark" in top_k.reason and "Benchmark" in top_k.reason_i18n["es"]


def test_timeout_and_dense_limit(analysis, monkeypatch):
    monkeypatch.setattr(bench, "TIMEOUT_SECONDS", 0.0)
    with pytest.raises(bench.BenchTimeout, match="RAGCOMPASS_BENCH_TIMEOUT"):
        bench.run_bench(analysis, queries=5, dense=False)
    monkeypatch.setattr(bench, "TIMEOUT_SECONDS", 600.0)
    monkeypatch.setattr(bench, "MAX_DENSE_CHUNKS", 1)
    result = bench.run_bench(analysis, queries=5).result
    assert result.retrievers == ["bm25"]
    assert any("dense limit" in w for w in result.warnings)


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


def models_cached(model: str) -> bool:
    name = model.split("/")[-1]
    return bench.embeddings.available() and any(
        name in p.name for p in bench.embeddings.CACHE_DIR.glob("models--*")
    )


def test_dense_bench_when_models_are_cached(analysis):
    model = bench.embeddings.model_for(bench._languages(analysis))
    if not models_cached(model):
        pytest.skip("bench extra or embedding model not available")
    result = bench.run_bench(analysis, queries=20, seed=1).result
    assert result.retrievers == ["bm25", "dense", "hybrid"]
    assert result.dense_model == model and result.dense_max_tokens == 128
    # chunks of 256+ tokens do not fit the 128-token window: they are embedded in windows, and the report says so
    assert any("embedded in windows" in w for w in result.warnings)
    dense = [c for c in result.configs if c.retriever == "dense"]
    assert (
        len({c.query_ms["mean"] > 0 for c in dense}) == 1
    )  # every configuration pays for the query embedding


def test_windows_cover_the_whole_chunk():
    model = bench.embeddings.MULTILINGUAL_MODEL
    if not models_cached(model):
        pytest.skip("bench extra or embedding model not available")
    embedder = bench.embeddings.get_embedder(model)
    text = " ".join(["The calibrator stores energy in its output capacitors for ninety seconds."] * 30)
    windows = embedder.windows(text)
    assert len(windows) > 1
    assert all(embedder.token_count(w) <= embedder.max_tokens - 2 for w in windows)
    assert windows[-1].strip() and text.endswith(windows[-1].strip()[-20:])


def test_missing_extra_is_reported(analysis, monkeypatch):
    monkeypatch.setattr(bench.embeddings, "available", lambda: False)
    result = bench.run_bench(analysis, queries=10, seed=2).result
    assert result.retrievers == ["bm25"]
    assert any("bench extra" in w for w in result.warnings)


def test_user_query_file(tmp_path, analysis):
    passage = "Remove the four screws of the rear grille with a T10 driver."
    path = tmp_path / "queries.jsonl"
    path.write_text(
        json.dumps({"id": "u1", "text": "how do I open the back cover?", "answer": passage})
        + "\n"
        + json.dumps(
            {"text": "warranty length", "answer": "veinticuatro meses", "file": "politica-devoluciones.docx"}
        )
        + "\n",
        encoding="utf-8",
    )
    queries = bench.load_queries(analysis, path)
    assert [q.id for q in queries] == ["u1", "q002"]
    first = queries[0]
    assert first.file == "hx200-maintenance-manual.pdf" and first.kind == "file"
    assert " ".join(analysis.docs[first.file].layout.text[first.start : first.end].split()) == passage
    result = bench.run_bench(analysis, dense=False, queries_file=path).result
    assert result.mode == "file" and result.queries == 2
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"text": "x", "answer": "not in any document at all"}]))
    with pytest.raises(ValueError, match="not found"):
        bench.load_queries(analysis, bad)


def test_llm_queries_fall_back_to_templates(analysis, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")  # nothing listens on the discard port
    result = bench.run_bench(analysis, queries=6, seed=4, mode="llm", dense=False).result
    assert result.mode == "template"
    assert any("LLM queries unavailable" in w for w in result.warnings)
