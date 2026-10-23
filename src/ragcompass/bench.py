"""Retrieval benchmark over the corpus itself.

Queries are generated from source sentences and table rows with a fixed seed; the ground
truth is the character span of the source. A retrieved chunk is relevant when it overlaps
that span, so chunkings of different shapes are judged on the same targets.

Metrics, per query, at cut-off k:

- recall@k: share of the source span covered by the union of the top-k chunks;
- MRR: reciprocal rank of the first chunk that overlaps the span (0 if none in the top 10);
- nDCG@k: graded gains, the share of the span each chunk covers, against the best possible order.
"""

from __future__ import annotations

import json
import math
import random
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ragcompass import embeddings
from ragcompass.analyze import Analysis
from ragcompass.chunking import Chunk
from ragcompass.explorer import utf16_offsets
from ragcompass.messages import LANGUAGES, render_parts
from ragcompass.models import (
    BenchConfig,
    BenchDecision,
    BenchQuery,
    BenchResult,
    BenchWinner,
    BlockType,
    Interval,
    ReasonPart,
)
from ragcompass.rules import Measured, Part, recommend
from ragcompass.signals import STOPWORDS
from ragcompass.simulate import PREFERENCE, chunk_doc, group_of

SEED = 13
QUERIES = 60
KS = (1, 3, 5, 10)
MAX_K = 10
CANDIDATES = 3  # the recommended chunking plus the next two by damage
BOOTSTRAP_SAMPLES = 1000
CONFIDENCE = 0.95
RRF_K = 60  # reciprocal rank fusion constant, as in the original RRF paper
RRF_DEPTH = 100
MIN_SENTENCE_WORDS = 8
TOP_K_RECALL_SHARE = 0.95  # smallest k that keeps 95% of recall@10 is enough
WORD = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
TERM = re.compile(r"\w+", re.UNICODE)
SENTENCE = re.compile(r"\S[^.!?]*(?:[.!?]+|$)")

QUESTION = {"en": "What does the documentation say about {}?", "es": "¿Qué dice la documentación sobre {}?"}
ROW_QUESTION = {"en": "{} of {}", "es": "{} de {}"}


# ---------------------------------------------------------------- corpus and queries


@dataclass(frozen=True)
class Query:
    id: str
    text: str
    file: str
    start: int
    end: int


@dataclass(frozen=True)
class IndexedChunk:
    file: str
    index: int  # position among the chunks of this file, as in the chunk explorer
    start: int
    end: int
    text: str

    @property
    def doc_id(self) -> str:
        return f"{self.file}#{self.index}"


@dataclass(frozen=True)
class Candidate:
    group: str
    strategy: str
    size: int
    overlap: int
    recommended: bool

    @property
    def label(self) -> str:
        return f"{self.strategy} {self.size}/{self.overlap}"

    @property
    def value(self) -> dict:
        return {"strategy": self.strategy, "size": self.size, "overlap": self.overlap}


def _languages(analysis: Analysis) -> dict[str, int]:
    tokens: Counter[str] = Counter()
    for profile in analysis.report.documents:
        if profile.language:
            tokens[profile.language] += profile.tokens
    return dict(tokens.most_common())


def main_group(analysis: Analysis) -> str | None:
    tokens: Counter[str] = Counter()
    for doc in analysis.docs.values():
        group = group_of(doc.kind)
        if group:
            tokens[group] += len(doc.layout.tokens)
    return tokens.most_common(1)[0][0] if tokens else None


def recommended_value(analysis: Analysis, group: str) -> dict:
    return next(r.value for r in analysis.report.recommendations if r.key == f"chunking.{group}")


def candidates(analysis: Analysis, group: str, count: int = CANDIDATES) -> list[Candidate]:
    """The recommended chunking first, then the next lowest-damage configurations.

    The best configuration of another strategy is always included, so the benchmark compares
    strategies and not only sizes of the same one.
    """
    pick = recommended_value(analysis, group)
    ranked = sorted(
        (s for s in analysis.report.simulations if s.group == group),
        key=lambda s: (s.damage, PREFERENCE.index(s.strategy), s.size, s.overlap),
    )
    out = [Candidate(group, pick["strategy"], pick["size"], pick["overlap"], True)]
    seen = {(pick["strategy"], pick["size"], pick["overlap"])}
    other = next((s for s in ranked if s.strategy != pick["strategy"]), None)
    if other is not None and count > 1:
        out.append(Candidate(group, other.strategy, other.size, other.overlap, False))
        seen.add((other.strategy, other.size, other.overlap))
    for sim in ranked:
        if len(out) >= count:
            break
        if (sim.strategy, sim.size, sim.overlap) not in seen:
            seen.add((sim.strategy, sim.size, sim.overlap))
            out.append(Candidate(group, sim.strategy, sim.size, sim.overlap, False))
    return out


def _header_prefix(layout, chunk: Chunk) -> str:
    """The table header a row chunk repeats on top of its span."""
    if not chunk.extra_tokens:
        return ""
    for span in layout.spans:
        if span.start <= chunk.start < span.end and layout.blocks[span.block].type == BlockType.TABLE:
            newline = layout.text.find("\n", span.start, span.end)
            return layout.text[span.start : newline + 1]
    return ""


def build_chunks(analysis: Analysis, candidate: Candidate) -> list[IndexedChunk]:
    out = []
    for doc in analysis.docs.values():
        group = group_of(doc.kind)
        if group is None or not len(doc.layout.tokens):
            continue
        if group == candidate.group:
            strategy, size, overlap = candidate.strategy, candidate.size, candidate.overlap
        else:
            v = recommended_value(analysis, group)
            strategy, size, overlap = v["strategy"], v["size"], v["overlap"]
        layout = doc.layout
        for i, chunk in enumerate(chunk_doc(doc, group, strategy, size, overlap)):
            text = _header_prefix(layout, chunk) + layout.text[chunk.start : chunk.end]
            out.append(IndexedChunk(doc.path, i, chunk.start, chunk.end, text))
    return out


@dataclass
class Unit:
    file: str
    start: int
    end: int
    text: str
    language: str
    header: list[str] | None = None  # table rows only
    cells: list[str] | None = None


def _units(analysis: Analysis) -> list[Unit]:
    """Sentences of prose blocks and data rows of tables: the material queries are made from."""
    languages = {p.path: p.language or "en" for p in analysis.report.documents}
    units = []
    for path, doc in sorted(analysis.docs.items()):
        layout = doc.layout
        lang = languages.get(path, "en")
        for span in layout.spans:
            block = layout.blocks[span.block]
            if block.type in (BlockType.PARAGRAPH, BlockType.LIST_ITEM):
                for match in SENTENCE.finditer(block.text):
                    sentence = match.group(0).strip()
                    if len(WORD.findall(sentence)) >= MIN_SENTENCE_WORDS:
                        start = span.start + match.start()
                        units.append(Unit(path, start, start + len(sentence), sentence, lang))
            elif block.type == BlockType.TABLE and block.rows and len(block.rows) > 1:
                header = block.rows[0]
                position = span.start + len(layout.text[span.start : span.end].split("\n", 1)[0]) + 1
                for row, line in zip(
                    block.rows[1:], layout.text[position : span.end].split("\n"), strict=False
                ):
                    if sum(1 for cell in row if cell) >= 2:
                        units.append(Unit(path, position, position + len(line), line, lang, header, row))
                    position += len(line) + 1
    return units


def _template_query(unit: Unit, rng: random.Random) -> str:
    lang = unit.language if unit.language in QUESTION else "en"
    if unit.cells is not None and unit.header is not None:
        key = next(cell for cell in unit.cells if cell)
        columns = [h for h, cell in zip(unit.header, unit.cells, strict=False) if h and cell and cell != key]
        column = rng.choice(columns) if columns else unit.header[0]
        return ROW_QUESTION[lang].format(column, key)
    stop = STOPWORDS.get(unit.language, STOPWORDS["en"])
    content = [w for w in WORD.findall(unit.text) if len(w) > 2 and w.lower() not in stop]
    if not content:
        content = WORD.findall(unit.text)
    length = min(len(content), rng.randint(4, 7))
    first = rng.randint(0, len(content) - length)
    phrase = " ".join(content[first : first + length])
    return QUESTION[lang].format(phrase) if rng.random() < 0.5 else phrase


def _llm_query(unit: Unit) -> str:
    import os

    import httpx

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("RAGCOMPASS_OLLAMA_MODEL", "llama3.2")
    prompt = (
        "Write one short question that the passage below answers. Do not copy more than three consecutive "
        f"words from it. Answer with the question only.\n\nPassage: {unit.text}\n\nQuestion:"
    )
    response = httpx.post(
        f"{host}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0, "seed": SEED}},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["response"].strip().splitlines()[0]


def generate_queries(
    analysis: Analysis, count: int = QUERIES, seed: int = SEED, mode: str = "template"
) -> list[Query]:
    rng = random.Random(seed)
    units = _units(analysis)
    rng.shuffle(units)
    queries = []
    for i, unit in enumerate(units[:count], start=1):
        text = _llm_query(unit) if mode == "llm" else _template_query(unit, rng)
        queries.append(Query(f"q{i:03d}", text, unit.file, unit.start, unit.end))
    return queries


# ---------------------------------------------------------------- retrievers


def terms(text: str) -> list[str]:
    return TERM.findall(text.lower())


class BM25:
    """Okapi BM25 with k1 = 1.5 and b = 0.75."""

    def __init__(self, texts: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.lengths = []
        for i, text in enumerate(texts):
            counts = Counter(terms(text))
            self.lengths.append(sum(counts.values()))
            for term, tf in counts.items():
                self.postings[term].append((i, tf))
        self.n = len(texts)
        self.avg = sum(self.lengths) / self.n if self.n else 0.0

    def search(self, query: str, depth: int) -> list[int]:
        scores: dict[int, float] = defaultdict(float)
        for term in set(terms(query)):
            postings = self.postings.get(term)
            if not postings:
                continue
            idf = math.log(1 + (self.n - len(postings) + 0.5) / (len(postings) + 0.5))
            for doc, tf in postings:
                norm = tf + self.k1 * (1 - self.b + self.b * self.lengths[doc] / (self.avg or 1))
                scores[doc] += idf * tf * (self.k1 + 1) / norm
        return sorted(scores, key=lambda d: (-scores[d], d))[:depth]


class Dense:
    def __init__(self, embedder: embeddings.Embedder, texts: list[str]) -> None:
        self.embedder = embedder
        self.matrix = embedder.embed(texts)

    def search(self, query: str, depth: int) -> list[int]:
        import numpy as np

        scores = self.matrix @ self.embedder.embed([query])[0]
        order = np.lexsort((np.arange(len(scores)), -scores))
        return [int(i) for i in order[:depth]]


def rrf(rankings: list[list[int]], depth: int) -> list[int]:
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            scores[doc] += 1 / (RRF_K + rank)
    return sorted(scores, key=lambda d: (-scores[d], d))[:depth]


# ---------------------------------------------------------------- metrics


def coverage(chunk: IndexedChunk, query: Query) -> float:
    if chunk.file != query.file:
        return 0.0
    overlap = min(chunk.end, query.end) - max(chunk.start, query.start)
    return max(overlap, 0) / max(query.end - query.start, 1)


def span_recall(chunks: list[IndexedChunk], query: Query) -> float:
    pieces = sorted(
        (max(c.start, query.start), min(c.end, query.end))
        for c in chunks
        if c.file == query.file and min(c.end, query.end) > max(c.start, query.start)
    )
    covered, reach = 0, query.start
    for start, end in pieces:
        start = max(start, reach)
        if end > start:
            covered += end - start
            reach = end
    return covered / max(query.end - query.start, 1)


def score_query(ranked: list[IndexedChunk], all_chunks: list[IndexedChunk], query: Query, k: int) -> dict:
    gains = [coverage(c, query) for c in ranked]
    first = next((i for i, g in enumerate(gains) if g > 0), None)
    ideal = sorted((g for g in (coverage(c, query) for c in all_chunks) if g > 0), reverse=True)

    def ndcg(cut: int) -> float:
        dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains[:cut]))
        idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal[:cut]))
        return dcg / idcg if idcg else 0.0

    return {
        "recall": {cut: span_recall(ranked[:cut], query) for cut in range(1, MAX_K + 1)},
        "mrr": 1 / (first + 1) if first is not None else 0.0,
        "ndcg": ndcg(k),
    }


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


class Bootstrap:
    """Paired percentile bootstrap: every metric is resampled with the same query indices."""

    def __init__(self, n: int, seed: int, samples: int = BOOTSTRAP_SAMPLES) -> None:
        rng = random.Random(seed)
        self.samples = [[rng.randrange(n) for _ in range(n)] for _ in range(samples)] if n else []

    def interval(self, values: list[float]) -> Interval:
        means = [mean([values[i] for i in sample]) for sample in self.samples]
        tail = (1 - CONFIDENCE) / 2
        return Interval(
            mean=round(mean(values), 4),
            ci=[round(percentile(means, tail), 4), round(percentile(means, 1 - tail), 4)],
        )

    def difference(self, a: list[float], b: list[float]) -> Interval:
        return self.interval([x - y for x, y in zip(a, b, strict=True)])


# ---------------------------------------------------------------- the benchmark


@dataclass
class Entry:
    candidate: Candidate
    retriever: str
    chunks: list[IndexedChunk]
    runs: dict[str, list[int]]  # query id -> ranked chunk positions
    per_query: list[dict]
    index_ms: float
    query_ms: list[float]

    @property
    def label(self) -> str:
        return f"{self.candidate.label} · {self.retriever}"


@dataclass
class BenchRun:
    result: BenchResult
    queries: list[Query]
    entries: list[Entry] = field(default_factory=list)
    measured: dict[str, Measured] = field(default_factory=dict)


def _render(parts: list[Part]) -> tuple[dict[str, str], list[ReasonPart]]:
    reason_parts = [ReasonPart(id=i, params=p) for i, p in parts]
    dumped = [part.model_dump() for part in reason_parts]
    return {lang: render_parts(dumped, lang) for lang in LANGUAGES}, reason_parts


def run_bench(
    analysis: Analysis,
    queries: int = QUERIES,
    seed: int = SEED,
    k: int | None = None,
    mode: str = "template",
    dense: bool = True,
) -> BenchRun:
    started = time.perf_counter()
    warnings: list[str] = []
    group = main_group(analysis)
    if group is None:
        raise ValueError("the corpus has no text to benchmark")
    top_k_rec = next(r for r in analysis.report.recommendations if r.key == "retrieval.top_k")
    k = k or top_k_rec.value["final"]
    k = max(1, min(k, MAX_K))

    try:
        query_list = generate_queries(analysis, queries, seed, mode)
    except Exception as exc:  # an unreachable Ollama falls back to templates
        warnings.append(f"LLM queries unavailable ({exc}); used template queries")
        mode = "template"
        query_list = generate_queries(analysis, queries, seed, mode)
    if not query_list:
        raise ValueError("the corpus has no sentences or table rows to make queries from")
    if len(query_list) < queries:
        warnings.append(f"only {len(query_list)} queries could be made from this corpus")
    if mode == "template":
        warnings.append(
            "template queries reuse words of their source and favour BM25; "
            "use --queries llm (local Ollama) for paraphrased questions"
        )

    embedder = None
    retrievers = ["bm25"]
    if dense:
        if embeddings.available():
            try:
                embedder = embeddings.get_embedder(embeddings.model_for(_languages(analysis)))
                retrievers += ["dense", "hybrid"]
            except Exception as exc:  # model download blocked, for instance
                warnings.append(f"dense retrieval unavailable: {exc}")
        else:
            warnings.append(embeddings.INSTALL_HINT + "; only BM25 was measured")

    boot = Bootstrap(len(query_list), seed)
    entries: list[Entry] = []
    for candidate in candidates(analysis, group):
        chunks = build_chunks(analysis, candidate)
        texts = [c.text for c in chunks]
        timer = time.perf_counter()
        bm25 = BM25(texts)
        built = {"bm25": (time.perf_counter() - timer) * 1000}
        dense_index = None
        if embedder is not None:
            timer = time.perf_counter()
            dense_index = Dense(embedder, texts)
            built["dense"] = (time.perf_counter() - timer) * 1000
            built["hybrid"] = built["bm25"] + built["dense"]
        for retriever in retrievers:
            runs, per_query, latency = {}, [], []
            for query in query_list:
                timer = time.perf_counter()
                if retriever == "bm25":
                    ranked = bm25.search(query.text, MAX_K)
                elif retriever == "dense":
                    ranked = dense_index.search(query.text, MAX_K)
                else:
                    ranked = rrf(
                        [bm25.search(query.text, RRF_DEPTH), dense_index.search(query.text, RRF_DEPTH)], MAX_K
                    )
                latency.append((time.perf_counter() - timer) * 1000)
                runs[query.id] = ranked
                per_query.append(score_query([chunks[i] for i in ranked], chunks, query, k))
            entries.append(Entry(candidate, retriever, chunks, runs, per_query, built[retriever], latency))

    configs = [_config(entry, k, boot) for entry in entries]
    winner, measured, decisions = _decide(analysis, entries, configs, retrievers, k, boot, len(query_list))
    to16 = {path: utf16_offsets(doc.layout.text) for path, doc in analysis.docs.items()}
    result = BenchResult(
        k=k,
        seed=seed,
        queries=len(query_list),
        mode=mode,
        retrievers=retrievers,
        dense_model=embedder.name if embedder else None,
        warnings=warnings,
        configs=configs,
        winner=winner,
        decisions=decisions,
        sample_queries=[
            BenchQuery(
                id=q.id, text=q.text, file=q.file, start=to16[q.file](q.start), end=to16[q.file](q.end)
            )
            for q in query_list[:10]
        ],
        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return BenchRun(result=result, queries=query_list, entries=entries, measured=measured)


def _config(entry: Entry, k: int, boot: Bootstrap) -> BenchConfig:
    c = entry.candidate
    recall = [q["recall"][k] for q in entry.per_query]
    latency = sorted(entry.query_ms)
    return BenchConfig(
        label=entry.label,
        group=c.group,
        strategy=c.strategy,
        size=c.size,
        overlap=c.overlap,
        retriever=entry.retriever,
        recommended=c.recommended,
        chunks=len(entry.chunks),
        recall_at_k=boot.interval(recall),
        mrr=boot.interval([q["mrr"] for q in entry.per_query]),
        ndcg=boot.interval([q["ndcg"] for q in entry.per_query]),
        curves={
            "recall": {str(cut): round(mean([q["recall"][cut] for q in entry.per_query]), 4) for cut in KS}
        },
        index_ms=round(entry.index_ms, 2),
        query_ms={"mean": round(mean(latency), 3), "p95": round(percentile(latency, 0.95), 3)},
    )


def _ndcg(entry: Entry) -> list[float]:
    return [q["ndcg"] for q in entry.per_query]


def _decide(analysis, entries, configs, retrievers, k, boot, n_queries):
    report = analysis.report
    by_label = {e.label: e for e in entries}
    ordered = sorted(entries, key=lambda e: -mean(_ndcg(e)))
    best, second = ordered[0], (ordered[1] if len(ordered) > 1 else None)
    margin = boot.difference(_ndcg(best), _ndcg(second)) if second else None
    winner = BenchWinner(
        label=best.label,
        runner_up=second.label if second else None,
        significant=bool(margin and margin.ci[0] > 0),
        margin=margin,
    )

    def rec(key):
        return next(r for r in report.recommendations if r.key == key)

    hybrid_rule = rec("retrieval.hybrid_bm25").value
    measured: dict[str, Measured] = {}
    decisions: list[BenchDecision] = []

    def decide(key, rule_value, m: Measured):
        measured[key] = m
        texts, parts = _render(m.parts)
        decisions.append(
            BenchDecision(
                key=key,
                basis=m.basis,
                rule_value=rule_value,
                measured_value=m.value,
                changed=m.changed,
                reason=texts["en"],
                reason_i18n=texts,
                reason_parts=parts,
            )
        )

    # Chunking of the main group: every chunking at its best retriever, the rule's pick against the rest.
    group = entries[0].candidate.group
    best_of: dict[str, Entry] = {}
    for e in entries:
        current = best_of.get(e.candidate.label)
        if current is None or mean(_ndcg(e)) > mean(_ndcg(current)):
            best_of[e.candidate.label] = e
    rule_entry = next(e for e in best_of.values() if e.candidate.recommended)
    top = max(best_of.values(), key=lambda e: (mean(_ndcg(e)), e.candidate.recommended))
    common = {"queries": n_queries, "k": k}
    if top is not rule_entry:
        gap = boot.difference(_ndcg(top), _ndcg(rule_entry))
        if gap.ci[0] > 0:
            params = {
                **common,
                "winner": top.label,
                "score": round(mean(_ndcg(top)), 3),
                "rule": rule_entry.label,
                "score_rule": round(mean(_ndcg(rule_entry)), 3),
                "gap": round(gap.mean, 3),
                "low": round(gap.ci[0], 3),
                "high": round(gap.ci[1], 3),
            }
            m = Measured(top.candidate.value, [("bench.chunking.changed", params)], changed=True)
            decide(f"chunking.{group}", rule_entry.candidate.value, m)
    if f"chunking.{group}" not in measured:
        score = boot.interval(_ndcg(rule_entry))
        params = {
            **common,
            "config": rule_entry.label,
            "score": round(score.mean, 3),
            "low": round(score.ci[0], 3),
            "high": round(score.ci[1], 3),
        }
        m = Measured(rule_entry.candidate.value, [("bench.chunking.confirmed", params)], changed=False)
        decide(f"chunking.{group}", rule_entry.candidate.value, m)
    chosen = measured[f"chunking.{group}"].value
    chosen_label = f"{chosen['strategy']} {chosen['size']}/{chosen['overlap']}"

    # Hybrid BM25 means adding BM25 to dense retrieval: compare hybrid with dense alone.
    if "hybrid" in retrievers:
        hybrid, dense = by_label[f"{chosen_label} · hybrid"], by_label[f"{chosen_label} · dense"]
        bm25 = by_label[f"{chosen_label} · bm25"]
        gap = boot.difference(_ndcg(hybrid), _ndcg(dense))
        params = {
            "k": k,
            "hybrid": round(mean(_ndcg(hybrid)), 3),
            "dense": round(mean(_ndcg(dense)), 3),
            "bm25": round(mean(_ndcg(bm25)), 3),
            "gap": round(gap.mean, 3),
            "low": round(gap.ci[0], 3),
            "high": round(gap.ci[1], 3),
        }
        if gap.ci[0] > 0:
            m = Measured(True, [("bench.hybrid.better", params)], changed=hybrid_rule is not True)
        elif gap.ci[1] < 0:
            m = Measured(False, [("bench.hybrid.worse", params)], changed=hybrid_rule is not False)
        else:
            m = Measured(hybrid_rule, [("bench.hybrid.tie", params)], changed=False, basis="rule-based")
        final = max((hybrid, dense) if m.value is not False else (dense,), key=lambda e: mean(_ndcg(e)))
        if m.value:
            final = hybrid
    else:
        m = Measured(hybrid_rule, [("bench.hybrid.unavailable", {})], changed=False, basis="rule-based")
        final = by_label[f"{chosen_label} · bm25"]
    decide("retrieval.hybrid_bm25", hybrid_rule, m)

    # Top-k: the smallest k that keeps most of recall@10 with the retriever that will be used.
    entry = final
    curve = {cut: mean([q["recall"][cut] for q in entry.per_query]) for cut in range(1, MAX_K + 1)}
    rule_k = rec("retrieval.top_k").value["final"]
    target = TOP_K_RECALL_SHARE * curve[MAX_K]
    needed = next(cut for cut in range(1, MAX_K + 1) if curve[cut] >= target)
    params = {
        "k": needed,
        "recall": round(curve[needed], 3),
        "recall10": round(curve[MAX_K], 3),
        "share": round(100 * TOP_K_RECALL_SHARE),
        "rule_k": rule_k,
        "rule_recall": round(curve[min(rule_k, MAX_K)], 3),
    }
    if needed < rule_k:
        m = Measured(needed, [("bench.top_k.lower", params)], changed=True)
    else:
        m = Measured(rule_k, [("bench.top_k.confirmed", params)], changed=False)
    decide("retrieval.top_k", {"final": rule_k}, m)
    return winner, measured, decisions


def apply(analysis: Analysis, run: BenchRun) -> None:
    """Recompute the plan with the measured values and attach the benchmark to the report."""
    report = analysis.report
    plan = recommend(report.documents, list(analysis.docs.values()), report.simulations, run.measured)
    report.recommendations = plan.recommendations
    report.index = plan.index
    report.costs = plan.costs
    report.config = {
        **{k: v for k, v in report.config.items() if k in ("version", "generator", "corpus")},
        **plan.config,
    }
    report.bench = run.result.model_dump()


# ---------------------------------------------------------------- evalsmith export


def _qrels(entry: Entry, queries: list[Query]) -> dict[str, dict[str, int]]:
    qrels = {}
    for query in queries:
        judged = {}
        for chunk in entry.chunks:
            share = coverage(chunk, query)
            if share > 0:
                judged[chunk.doc_id] = 2 if share >= 0.5 else 1
        qrels[query.id] = judged
    return qrels


def _evalsmith_scores(qrels, run, k) -> tuple[float, float]:
    """recall@k and nDCG@k the way evalsmith computes them, to set gates it will pass."""
    recalls, ndcgs = [], []
    for qid, judged in qrels.items():
        relevant = {d for d, g in judged.items() if g > 0}
        if not relevant:
            continue
        ranked = list(dict.fromkeys(run.get(qid, [])))[:k]
        recalls.append(len(relevant & set(ranked)) / len(relevant))
        dcg = sum(judged.get(d, 0) / math.log2(i + 2) for i, d in enumerate(ranked))
        ideal = sorted(judged.values(), reverse=True)[:k]
        idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
        ndcgs.append(dcg / idcg if idcg else 0.0)
    return mean(recalls), mean(ndcgs)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def export_evalsmith(run: BenchRun, directory: str | Path, gate_margin: float = 0.05) -> Path:
    """Write qrels, runs and an evalsmith.yaml that gates CI on the measured configuration.

    Chunk ids differ between chunkings, so every chunking gets its own qrels; the suite compares
    the retrievers of the winning chunking, which share them.
    """
    import yaml

    out = Path(directory)
    (out / "configs").mkdir(parents=True, exist_ok=True)
    (out / "queries.json").write_text(
        json.dumps(
            {q.id: {"text": q.text, "file": q.file, "start": q.start, "end": q.end} for q in run.queries},
            indent=2,
        ),
        encoding="utf-8",
    )
    by_candidate: dict[str, list[Entry]] = defaultdict(list)
    for entry in run.entries:
        by_candidate[entry.candidate.label].append(entry)
    for label, entries in by_candidate.items():
        folder = out / "configs" / _slug(label)
        (folder / "runs").mkdir(parents=True, exist_ok=True)
        (folder / "qrels.json").write_text(
            json.dumps(_qrels(entries[0], run.queries), indent=2), encoding="utf-8"
        )
        for entry in entries:
            ranked = {
                qid: [entry.chunks[i].doc_id for i in positions] for qid, positions in entry.runs.items()
            }
            (folder / "runs" / f"{entry.retriever}.json").write_text(
                json.dumps(ranked, indent=2), encoding="utf-8"
            )

    result = run.result
    chosen = next(d.measured_value for d in result.decisions if d.key.startswith("chunking."))
    label = f"{chosen['strategy']} {chosen['size']}/{chosen['overlap']}"
    entries = by_candidate[label]
    hybrid = next((d.measured_value for d in result.decisions if d.key == "retrieval.hybrid_bm25"), None)
    names = [e.retriever for e in entries]
    primary = "hybrid" if hybrid and "hybrid" in names else names[-1]
    base = f"configs/{_slug(label)}"
    qrels = json.loads((out / base / "qrels.json").read_text(encoding="utf-8"))
    primary_run = json.loads((out / base / "runs" / f"{primary}.json").read_text(encoding="utf-8"))
    k = result.k
    recall, ndcg = _evalsmith_scores(qrels, primary_run, k)
    floor = lambda value: max(0.0, math.floor((value - gate_margin) * 100) / 100)  # noqa: E731
    suite = {
        "name": f"ragcompass-{_slug(label)}",
        "retrieval": {
            "qrels": f"{base}/qrels.json",
            "run": f"{base}/runs/{primary}.json",
            "k": sorted({1, 3, k, 10}),
        },
        "gates": {f"recall@{k}": floor(recall), f"ndcg@{k}": floor(ndcg)},
    }
    if len(entries) > 1:
        suite["compare"] = {
            "metric": f"ndcg@{k}",
            "configs": [{"name": e.retriever, "run": f"{base}/runs/{e.retriever}.json"} for e in entries],
            "bootstrap": {"samples": 2000, "seed": result.seed, "confidence": CONFIDENCE},
        }
    header = (
        "# evalsmith suite generated by ragcompass bench. Gates sit 0.05 below the measured values.\n"
        "# Run: npx evalsmith run evalsmith.yaml\n"
    )
    (out / "evalsmith.yaml").write_text(header + yaml.safe_dump(suite, sort_keys=False), encoding="utf-8")
    return out
