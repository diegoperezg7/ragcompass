from ragcompass import rules
from ragcompass.analyze import analyze
from ragcompass.tokens import RegexTokenizer
from tests.conftest import CORPUS


def rec(report, key):
    return next(r for r in report.recommendations if r.key == key)


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


PROSE = (
    "The committee met on a quiet morning to review the plan for the new library. "
    "Everyone agreed that the reading room should face the garden and that the old "
    "shelves could be restored rather than replaced. "
)


def test_example_corpus_recommendations():
    report = analyze(CORPUS, tokenizer=RegexTokenizer())
    assert report.summary.files == 9
    assert report.summary.kinds["pdf_scanned"] == 1
    assert rec(report, "parser.pdf_scanned").value.startswith("OCR")
    assert rec(report, "chunking.documents").value["strategy"] == "heading"
    assert rec(report, "chunking.tables").value["strategy"] == "row"
    assert rec(report, "retrieval.hybrid_bm25").value is True  # SKUs and dates everywhere
    assert rec(report, "embedding.dimension").value == 1024  # English + Spanish
    assert "page" in rec(report, "metadata").value
    assert {i.dimension for i in report.index} == {384, 768, 1024, 1536, 3072}


def test_every_recommendation_has_a_reason():
    report = analyze(CORPUS, tokenizer=RegexTokenizer())
    assert all(r.reason.strip() for r in report.recommendations)


def test_analysis_is_deterministic():
    first = analyze(CORPUS, tokenizer=RegexTokenizer()).model_dump()
    second = analyze(CORPUS, tokenizer=RegexTokenizer()).model_dump()
    assert first == second


def test_plain_english_prose(tmp_path):
    write(tmp_path, "notes.txt", PROSE * 20)
    report = analyze(tmp_path, tokenizer=RegexTokenizer())
    assert rec(report, "retrieval.hybrid_bm25").value is False
    assert rec(report, "embedding.dimension").value == 768
    assert rec(report, "chunking.documents").value["size"] == rules.DEFAULT_PROSE_SIZE
    assert rec(report, "retrieval.reranker").value is False


def test_index_size_arithmetic(tmp_path):
    write(tmp_path, "notes.txt", PROSE * 20)
    report = analyze(tmp_path, tokenizer=RegexTokenizer())
    vectors = rec(report, "vectors").value
    by_dim = {i.dimension: i for i in report.index}
    assert by_dim[768].float32_bytes == vectors * 768 * 4
    assert by_dim[768].int8_bytes == vectors * 768
    assert by_dim[768].hnsw_overhead_bytes == vectors * 16 * 2 * 4


def test_quantization_switches_to_int8(tmp_path, monkeypatch):
    write(tmp_path, "notes.txt", PROSE * 20)
    monkeypatch.setattr(rules, "INT8_THRESHOLD_BYTES", 1)
    report = analyze(tmp_path, tokenizer=RegexTokenizer())
    assert rec(report, "embedding.quantization").value == "int8"


def test_top_k_follows_context_budget(tmp_path):
    write(tmp_path, "notes.txt", PROSE * 20)
    report = analyze(tmp_path, tokenizer=RegexTokenizer())
    # 3000-token budget / 512-token chunks = 5.86 -> 6
    assert rec(report, "retrieval.top_k").value == {"candidates": 6, "final": 6}


def test_overlap_rule(tmp_path):
    # No sentence punctuation: every boundary cuts a sentence, so overlap goes to 20%.
    write(tmp_path, "words.txt", " ".join(["word"] * 3000))
    report = analyze(tmp_path, tokenizer=RegexTokenizer())
    assert rec(report, "chunking.documents").value == {"strategy": "recursive", "size": 512, "overlap": 102}
    # Clean sentence boundaries everywhere: no overlap needed.
    write(tmp_path, "words.txt", PROSE * 40)
    report = analyze(tmp_path, tokenizer=RegexTokenizer())
    assert rec(report, "chunking.documents").value["overlap"] == 0


def test_scanned_pages_are_estimated_not_simulated():
    report = analyze(CORPUS / "scanned-invoice.pdf", tokenizer=RegexTokenizer())
    vectors = rec(report, "vectors")
    assert vectors.evidence["simulated"] == 0
    assert vectors.evidence["scanned_estimate"] == 1  # 450 tokens fit one 512-token chunk
