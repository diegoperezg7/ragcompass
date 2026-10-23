"""Retrieval benchmark over the corpus itself.

Queries are generated from source sentences and table rows with a fixed seed; the ground
truth is the character span of the source. A retrieved chunk is relevant when it overlaps
that span, so chunkings of different shapes are judged on the same targets.

Metrics, per query:

- recall@k: share of the source span covered by the union of the top-k chunks;
- recall within a token budget: the same, keeping ranked chunks only while they fit in
  ``BUDGET_TOKENS`` of context, which charges large chunks for the room they take;
- MRR: reciprocal rank of the first chunk that overlaps the span (0 if none in the top 10);
- nDCG@k: gains are the share of the span a chunk newly covers, so a chunk repeating text
  already retrieved neither helps nor hurts; the ideal is the best achievable coverage order.
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
    TopByMetric,
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
BUDGET_TOKENS = 1024  # context budget for the token-efficiency metric: what fits a tight prompt
MAX_DENSE_CHUNKS = 20_000  # above this per configuration, dense indexing is skipped with a warning
TIMEOUT_SECONDS = float(__import__("os").environ.get("RAGCOMPASS_BENCH_TIMEOUT", "600"))
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
    kind: str = "keyphrase"  # keyphrase, masked, question, llm or file


@dataclass(frozen=True)
class IndexedChunk:
    file: str
    index: int  # position among the chunks of this file, as in the chunk explorer
    start: int
    end: int
    text: str
    tokens: int = 0

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
            tokens = layout.tokens.count(chunk.start, chunk.end) + chunk.extra_tokens
            out.append(IndexedChunk(doc.path, i, chunk.start, chunk.end, text, tokens))
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


QUERY_KINDS = ("keyphrase", "masked", "question")
MASK_SHARE = 0.4  # share of the rarest words removed from masked queries
# Above this share of copied words, a benchmark cannot tell lexical from semantic retrieval
# apart: BM25 wins by construction. Template queries sit near 1, paraphrases well below 0.5.
OVERLAP_WARNING = 0.6


# Function words that the language-detection lists leave out but that make poor query terms.
_QUERY_STOPWORDS = {
    "en": "you your our their they them there these those been has had were would should could its into than "
    "then also any all each when where what who how more most such only own same other some very just will can "
    "may must does did done about after before over under again",
    "es": "todos todas este esta estos estas sin sobre entre hasta desde cada otro otra muy ser está están son "
    "han hay puede pueden debe deben tiene tienen también cuando donde",
}
QUERY_STOPWORDS = {lang: set(words.split()) for lang, words in _QUERY_STOPWORDS.items()}


def _content(text: str, language: str) -> list[str]:
    stop = STOPWORDS.get(language, STOPWORDS["en"]) | QUERY_STOPWORDS.get(language, QUERY_STOPWORDS["en"])
    words = [w for w in WORD.findall(text) if len(w) > 2 and w.lower() not in stop]
    return words or WORD.findall(text)


def idf_table(units: list[Unit]) -> dict[str, float]:
    """Inverse document frequency of every term across the query sources."""
    df: Counter[str] = Counter()
    for unit in units:
        df.update(set(terms(unit.text)))
    n = len(units) or 1
    return {term: math.log((n + 1) / (count + 0.5)) for term, count in df.items()}


def _mask(words: list[str], idf: dict[str, float]) -> list[str]:
    """Drop the rarest words (codes and numbers first): the ones that make lexical matching easy."""
    if len(words) < 4:
        return words
    drop = max(1, math.ceil(MASK_SHARE * len(words)))
    rank = sorted(
        range(len(words)),
        key=lambda i: (-(any(c.isdigit() for c in words[i])), -idf.get(words[i].lower(), 0), i),
    )
    removed = set(rank[:drop])
    return [w for i, w in enumerate(words) if i not in removed]


def _template_query(unit: Unit, rng: random.Random, idf: dict[str, float], kind: str) -> str:
    lang = unit.language if unit.language in QUESTION else "en"
    if unit.cells is not None and unit.header is not None:
        key = next(cell for cell in unit.cells if cell)
        pairs = [
            (h, cell) for h, cell in zip(unit.header, unit.cells, strict=False) if h and cell and cell != key
        ]
        column = rng.choice(pairs)[0] if pairs else unit.header[0]
        if kind != "keyphrase" and len(pairs) > 1:
            # Ask through the most common other value instead of the row's identifier.
            others = [(h, cell) for h, cell in pairs if h != column]
            worded = [hc for hc in others if any(ch.isalpha() for ch in hc[1])] or others
            key = min(worded, key=lambda hc: sum(idf.get(t, 0) for t in terms(hc[1])))[1]
        return ROW_QUESTION[lang].format(column, key)
    content = _content(unit.text, unit.language)
    length = min(len(content), rng.randint(5, 8))
    first = rng.randint(0, len(content) - length)
    words = content[first : first + length]
    if kind == "keyphrase":
        return " ".join(words)
    masked = " ".join(_mask(words, idf))
    return QUESTION[lang].format(masked) if kind == "question" else masked


TEMPLATE_WORDS = {
    t for template in (*QUESTION.values(), *ROW_QUESTION.values()) for t in TERM.findall(template.lower())
}


def lexical_overlap(query: str, source: str, idf: dict[str, float], language: str = "en") -> float:
    """IDF-weighted share of the query's own words that appear literally in its source.

    1 means every distinctive word of the query is copied from the source (lexical matching is
    easy); 0 means none is. Function words and the fixed words of the templates are ignored.
    """
    stop = STOPWORDS.get(language, STOPWORDS["en"]) | QUERY_STOPWORDS.get(language, QUERY_STOPWORDS["en"])
    query_terms = {t for t in terms(query) if t not in stop and t not in TEMPLATE_WORDS}
    if not query_terms:
        return 0.0
    ceiling = max(idf.values(), default=1.0)  # unseen words count as the rarest
    weight = lambda t: idf.get(t, ceiling)  # noqa: E731
    shared = query_terms & set(terms(source))
    return sum(weight(t) for t in shared) / sum(weight(t) for t in query_terms)


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
    idf = idf_table(units)
    rng.shuffle(units)
    queries = []
    for i, unit in enumerate(units[:count], start=1):
        if mode == "llm":
            text, kind = _llm_query(unit), "llm"
        else:
            kind = QUERY_KINDS[(i - 1) % len(QUERY_KINDS)]  # equal thirds of each kind
            text = _template_query(unit, rng, idf, kind)
        queries.append(Query(f"q{i:03d}", text, unit.file, unit.start, unit.end, kind))
    return queries


def load_queries(analysis: Analysis, path: str | Path) -> list[Query]:
    """Read a user query set: JSON list or JSON Lines of {"text", "answer", "file"?, "id"?}.

    ``answer`` is a passage copied from the document; it is located in the canonical text with
    whitespace normalised, which gives the ground-truth span. ``file`` limits the search to one file.
    """
    raw = Path(path).read_text(encoding="utf-8")
    items = (
        json.loads(raw)
        if raw.lstrip().startswith("[")
        else [json.loads(line) for line in raw.splitlines() if line.strip()]
    )
    queries = []
    for n, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not item.get("text") or not item.get("answer"):
            raise ValueError(f"query {n}: each entry needs a 'text' and an 'answer' passage")
        files = [item["file"]] if item.get("file") else sorted(analysis.docs)
        span = None
        for file in files:
            if file not in analysis.docs:
                raise ValueError(f"query {n}: unknown file {file!r}")
            span = _locate(analysis.docs[file].layout.text, item["answer"])
            if span:
                queries.append(
                    Query(str(item.get("id") or f"q{n:03d}"), item["text"], file, *span, kind="file")
                )
                break
        if span is None:
            raise ValueError(f"query {n}: the answer passage was not found in {', '.join(files)}")
    return queries


def _locate(text: str, passage: str) -> tuple[int, int] | None:
    words = passage.split()
    if not words:
        return None
    pattern = r"\s+".join(re.escape(w) for w in words)
    match = re.search(pattern, text) or re.search(pattern, text, re.IGNORECASE)
    return (match.start(), match.end()) if match else None


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
        self.matrix = embedder.embed(texts, cache=False)  # timed: never served from the cache

    def search(self, vector, depth: int) -> list[int]:
        import numpy as np

        scores = self.matrix @ vector
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


class SpanCover:
    """Tracks which part of a query's source span the chunks seen so far already cover."""

    def __init__(self, query: Query) -> None:
        self.query = query
        self.pieces: list[tuple[int, int]] = []

    def add(self, chunk: IndexedChunk) -> float:
        """Cover ``chunk`` and return the share of the span it newly covers."""
        q = self.query
        start, end = max(chunk.start, q.start), min(chunk.end, q.end)
        if chunk.file != q.file or end <= start:
            return 0.0
        before = self.covered()
        self.pieces.append((start, end))
        return (self.covered() - before) / max(q.end - q.start, 1)

    def covered(self) -> int:
        total, reach = 0, self.query.start
        for start, end in sorted(self.pieces):
            start = max(start, reach)
            if end > start:
                total += end - start
                reach = end
        return total


def span_recall(chunks: list[IndexedChunk], query: Query) -> float:
    cover = SpanCover(query)
    for chunk in chunks:
        cover.add(chunk)
    return cover.covered() / max(query.end - query.start, 1)


def _gain_if_added(cover: SpanCover, chunk: IndexedChunk) -> float:
    trial = SpanCover(cover.query)
    trial.pieces = list(cover.pieces)
    return trial.add(chunk)


def _ideal_gains(all_chunks: list[IndexedChunk], query: Query, cut: int) -> list[float]:
    """Greedy best order: each step takes the chunk that covers the most still-uncovered span."""
    pool = [c for c in all_chunks if coverage(c, query) > 0]
    cover, gains = SpanCover(query), []
    while pool and len(gains) < cut:
        best = max(pool, key=lambda c: (_gain_if_added(cover, c), -c.tokens))
        pool.remove(best)
        gain = cover.add(best)
        if gain <= 0:
            break
        gains.append(gain)
    return gains


def budget_recall(ranked: list[IndexedChunk], query: Query, budget: int = BUDGET_TOKENS) -> float:
    """Span recall keeping ranked chunks while they fit in ``budget`` tokens of context."""
    kept, used = [], 0
    for chunk in ranked:
        if used + chunk.tokens > budget:
            break
        kept.append(chunk)
        used += chunk.tokens
    return span_recall(kept, query)


def score_query(ranked: list[IndexedChunk], all_chunks: list[IndexedChunk], query: Query, k: int) -> dict:
    cover = SpanCover(query)
    gains = [cover.add(c) for c in ranked]
    first = next((i for i, c in enumerate(ranked) if coverage(c, query) > 0), None)
    ideal = _ideal_gains(all_chunks, query, k)
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains[:k]))
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return {
        "recall": {cut: span_recall(ranked[:cut], query) for cut in range(1, MAX_K + 1)},
        "budget": budget_recall(ranked, query),
        "mrr": 1 / (first + 1) if first is not None else 0.0,
        "ndcg": dcg / idcg if idcg else 0.0,
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

    def interval(self, values: list[float], confidence: float = CONFIDENCE) -> Interval:
        means = [mean([values[i] for i in sample]) for sample in self.samples]
        tail = (1 - confidence) / 2
        return Interval(
            mean=round(mean(values), 4),
            ci=[round(percentile(means, tail), 4), round(percentile(means, 1 - tail), 4)],
        )

    def difference(self, a: list[float], b: list[float], comparisons: int = 1) -> Interval:
        """Interval of a minus b, Bonferroni-adjusted for ``comparisons`` simultaneous tests."""
        return self.interval(
            [x - y for x, y in zip(a, b, strict=True)], 1 - (1 - CONFIDENCE) / max(comparisons, 1)
        )


class BenchTimeout(ValueError):
    pass


def adjusted_confidence(comparisons: int) -> float | int:
    value = round(100 * (1 - (1 - CONFIDENCE) / max(comparisons, 1)), 1)
    return int(value) if value.is_integer() else value


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
    queries_file: str | Path | None = None,
) -> BenchRun:
    started = time.perf_counter()
    warnings: list[str] = []
    group = main_group(analysis)
    if group is None:
        raise ValueError("the corpus has no text to benchmark")
    top_k_rec = next(r for r in analysis.report.recommendations if r.key == "retrieval.top_k")
    k = k or top_k_rec.value["final"]
    k = max(1, min(k, MAX_K))

    if queries_file is not None:
        mode, query_list = "file", load_queries(analysis, queries_file)
    else:
        try:
            query_list = generate_queries(analysis, queries, seed, mode)
        except Exception as exc:  # an unreachable Ollama falls back to templates
            warnings.append(f"LLM queries unavailable ({exc}); used template queries")
            mode = "template"
            query_list = generate_queries(analysis, queries, seed, mode)
        if len(query_list) < queries:
            warnings.append(f"only {len(query_list)} queries could be made from this corpus")
    if not query_list:
        raise ValueError("the corpus has no sentences or table rows to make queries from")
    idf = idf_table(_units(analysis))
    languages = {p.path: p.language or "en" for p in analysis.report.documents}
    overlaps: dict[str, list[float]] = defaultdict(list)
    for query in query_list:
        source = analysis.docs[query.file].layout.text[query.start : query.end]
        overlaps[query.kind].append(lexical_overlap(query.text, source, idf, languages.get(query.file, "en")))
    overlap_mean = mean([v for values in overlaps.values() for v in values])
    if mode == "template":
        warnings.append(
            "synthetic queries approximate real ones: they are built from words of their source; "
            "--queries llm (local Ollama) or --queries-file with your own questions measure more reliably"
        )
    if overlap_mean >= OVERLAP_WARNING:
        warnings.append(
            f"{overlap_mean:.0%} of the query words are copied from their source: lexical retrieval wins by "
            "construction, so BM25 alone is never chosen on this evidence"
        )

    group_candidates = candidates(analysis, group)
    chunk_sets = {c.label: build_chunks(analysis, c) for c in group_candidates}

    embedder = None
    retrievers = ["bm25"]
    if dense:
        largest = max(len(chunks) for chunks in chunk_sets.values())
        if not embeddings.available():
            warnings.append(embeddings.INSTALL_HINT + "; only BM25 was measured")
        elif largest > MAX_DENSE_CHUNKS:
            warnings.append(
                f"{largest:,} chunks exceed the dense limit of {MAX_DENSE_CHUNKS:,} per configuration; only BM25 was measured"
            )
        else:
            try:
                embedder = embeddings.get_embedder(embeddings.model_for(_languages(analysis)))
                embedder.warm_up()  # so the first configuration does not pay for loading the model
                retrievers += ["dense", "hybrid"]
            except Exception as exc:  # model download blocked, for instance
                warnings.append(f"dense retrieval unavailable: {exc}")

    # Query vectors are computed once, and their cost is timed apart from the search itself.
    query_vectors, embed_ms = {}, {}
    if embedder is not None:
        for query in query_list:
            timer = time.perf_counter()
            query_vectors[query.id] = embedder.embed([query.text], cache=False)[0]
            embed_ms[query.id] = (time.perf_counter() - timer) * 1000

    def check_time():
        if time.perf_counter() - started > TIMEOUT_SECONDS:
            raise BenchTimeout(
                f"benchmark stopped after {TIMEOUT_SECONDS:.0f} s (RAGCOMPASS_BENCH_TIMEOUT); "
                "use fewer queries, dense=false or a smaller corpus"
            )

    boot = Bootstrap(len(query_list), seed)
    entries: list[Entry] = []
    windowed_before = embedder.windowed if embedder else 0
    for candidate in group_candidates:
        chunks = chunk_sets[candidate.label]
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
        check_time()
        for retriever in retrievers:
            runs, per_query, latency = {}, [], []
            for query in query_list:
                timer = time.perf_counter()
                if retriever == "bm25":
                    ranked = bm25.search(query.text, MAX_K)
                elif retriever == "dense":
                    ranked = dense_index.search(query_vectors[query.id], MAX_K)
                else:
                    ranked = rrf(
                        [
                            bm25.search(query.text, RRF_DEPTH),
                            dense_index.search(query_vectors[query.id], RRF_DEPTH),
                        ],
                        MAX_K,
                    )
                elapsed = (time.perf_counter() - timer) * 1000
                latency.append(elapsed + (embed_ms[query.id] if retriever != "bm25" else 0.0))
                runs[query.id] = ranked
                per_query.append(score_query([chunks[i] for i in ranked], chunks, query, k))
            entries.append(Entry(candidate, retriever, chunks, runs, per_query, built[retriever], latency))
            check_time()
    if embedder is not None and embedder.windowed > windowed_before:
        warnings.append(
            f"the dense model reads {embedder.max_tokens} tokens per pass; "
            f"{embedder.windowed - windowed_before} longer chunks were embedded in windows and averaged"
        )

    configs = [_config(entry, k, boot) for entry in entries]
    winner, measured, decisions = _decide(
        analysis, entries, configs, retrievers, k, boot, len(query_list), overlap_mean, warnings
    )
    to16 = {path: utf16_offsets(doc.layout.text) for path, doc in analysis.docs.items()}
    result = BenchResult(
        k=k,
        seed=seed,
        queries=len(query_list),
        mode=mode,
        query_kinds=dict(Counter(q.kind for q in query_list)),
        lexical_overlap={
            "mean": round(overlap_mean, 3),
            "by_kind": {kind: round(mean(values), 3) for kind, values in overlaps.items()},
        },
        retrievers=retrievers,
        dense_model=embedder.name if embedder else None,
        dense_max_tokens=embedder.max_tokens if embedder else None,
        budget_tokens=BUDGET_TOKENS,
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
        recall_at_budget=boot.interval([q["budget"] for q in entry.per_query]),
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


def _budget(entry: Entry) -> list[float]:
    return [q["budget"] for q in entry.per_query]


def _r(value: float) -> float:
    return round(value, 3)


def _decide(analysis, entries, configs, retrievers, k, boot, n_queries, overlap=0.0, warnings=None):
    report = analysis.report
    warnings = warnings if warnings is not None else []
    by_label = {e.label: e for e in entries}
    group = entries[0].candidate.group
    labels = list(dict.fromkeys(e.candidate.label for e in entries))
    rule_label = next(e.candidate.label for e in entries if e.candidate.recommended)

    def rec(key):
        return next(r for r in report.recommendations if r.key == key)

    def chunking(retriever: str) -> Measured:
        """Span recall within the token budget, every candidate with the same retriever.

        The budget keeps a chunking from winning by size; the rule's pick is tested against every
        other candidate with Bonferroni-adjusted intervals.
        """
        rule_entry = by_label[f"{rule_label} · {retriever}"]
        others = [by_label[f"{label} · {retriever}"] for label in labels if label != rule_label]
        comparisons = max(len(others), 1)
        common = {
            "queries": n_queries,
            "retriever": retriever,
            "budget": BUDGET_TOKENS,
            "conf": adjusted_confidence(comparisons),
            "m": comparisons,
        }
        better = []
        for e in others:
            gap = boot.difference(_budget(e), _budget(rule_entry), comparisons)
            if gap.ci[0] > 0:
                better.append((mean(_budget(e)), e, gap))
        if better:
            _, top, gap = max(better, key=lambda t: t[0])
            params = {
                **common,
                "winner": top.candidate.label,
                "score": _r(mean(_budget(top))),
                "rule": rule_label,
                "score_rule": _r(mean(_budget(rule_entry))),
                "gap": _r(gap.mean),
                "low": _r(gap.ci[0]),
                "high": _r(gap.ci[1]),
            }
            return Measured(top.candidate.value, [("bench.chunking.changed", params)], changed=True)
        score = boot.interval(_budget(rule_entry))
        params = {
            **common,
            "config": rule_label,
            "score": _r(score.mean),
            "low": _r(score.ci[0]),
            "high": _r(score.ci[1]),
        }
        return Measured(
            rule_entry.candidate.value,
            [("bench.chunking.confirmed", params)],
            changed=False,
            basis="rule-based",
        )

    def retriever_on(label: str) -> tuple[Measured, Entry]:
        """nDCG@k of the three retrievers on one chunking. An option that loses significantly to the
        best is never returned; with copied query words BM25 alone is not eligible."""
        rule_retriever = rec("retrieval.retriever").value
        if "hybrid" not in retrievers:
            m = Measured(
                rule_retriever, [("bench.retriever.unavailable", {})], changed=False, basis="rule-based"
            )
            return m, by_label[f"{label} · bm25"]
        options = {r: by_label[f"{label} · {r}"] for r in ("bm25", "dense", "hybrid")}
        scores = {r: _r(mean(_ndcg(e))) for r, e in options.items()}
        lexical = overlap >= OVERLAP_WARNING
        eligible = ["dense", "hybrid"] if lexical else list(options)
        top = max(eligible, key=lambda r: mean(_ndcg(options[r])))
        within = [
            r
            for r in eligible
            if r == top
            or boot.difference(_ndcg(options[top]), _ndcg(options[r]), len(eligible) - 1).ci[0] <= 0
        ]
        base = {"k": k, **scores, "conf": adjusted_confidence(len(eligible) - 1)}
        parts: list[Part] = []
        if lexical:
            parts.append(("bench.retriever.lexical", {**base, "overlap": round(100 * overlap)}))
        if rule_retriever in within and len(within) > 1:
            parts.append(("bench.retriever.tie", {**base, "rule": rule_retriever, "best": top}))
            m = Measured(rule_retriever, parts, changed=False, basis="rule-based")
        elif within == [top]:
            parts.append(("bench.retriever.best", {**base, "best": top}))
            m = Measured(top, parts, changed=rule_retriever != top)
        else:
            choice = "hybrid" if "hybrid" in within else top
            gap = boot.difference(_ndcg(options[top]), _ndcg(options[rule_retriever]), len(eligible) - 1)
            params = {
                **base,
                "rule": rule_retriever,
                "best": top,
                "choice": choice,
                "within": ", ".join(within),
                "gap": _r(gap.mean),
                "low": _r(gap.ci[0]),
                "high": _r(gap.ci[1]),
            }
            parts.append(("bench.retriever.excluded", params))
            if choice != top:
                parts.append(("bench.retriever.prefer_hybrid", {}))
            m = Measured(choice, parts, changed=rule_retriever != choice)
        return m, options[m.value] if m.value in options else options[top]

    def label_of(value: dict) -> str:
        return f"{value['strategy']} {value['size']}/{value['overlap']}"

    # Chunkings are compared with the retriever the rules deploy; if the measurement then picks
    # another retriever, the comparison is repeated once with it so both decisions agree.
    rule_retriever = rec("retrieval.retriever").value
    compared = rule_retriever if rule_retriever in retrievers else retrievers[-1]
    m_chunking = chunking(compared)
    m_retriever, final = retriever_on(label_of(m_chunking.value))
    if final.retriever != compared:
        compared = final.retriever
        again = chunking(compared)
        if again.value != m_chunking.value:
            m_retriever, final = retriever_on(label_of(again.value))
        m_chunking = again
    if final.retriever != compared:
        m_chunking.parts.append(
            ("bench.chunking.other_retriever", {"compared": compared, "deployed": final.retriever})
        )

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

    decide(f"chunking.{group}", by_label[f"{rule_label} · {retrievers[0]}"].candidate.value, m_chunking)
    decide("retrieval.retriever", rule_retriever, m_retriever)

    # Top-k: the smallest k that keeps 95% of recall@10 with the retriever that will be used. It can
    # go up or down; rules keep it under the context budget and the index size.
    curve = {cut: mean([q["recall"][cut] for q in final.per_query]) for cut in range(1, MAX_K + 1)}
    rule_k = rec("retrieval.top_k").value["final"]
    if curve[MAX_K] == 0:
        warnings.append("no query found its source in the top 10; top-k is left to the rules")
        m = Measured(rule_k, [("bench.top_k.no_recall", {})], changed=False, basis="rule-based")
    else:
        needed = next(cut for cut in range(1, MAX_K + 1) if curve[cut] >= TOP_K_RECALL_SHARE * curve[MAX_K])
        params = {
            "k": needed,
            "recall": _r(curve[needed]),
            "recall10": _r(curve[MAX_K]),
            "share": round(100 * TOP_K_RECALL_SHARE),
            "rule_k": rule_k,
            "rule_recall": _r(curve[min(rule_k, MAX_K)]),
            "retriever": final.retriever,
        }
        if needed != rule_k:
            m = Measured(needed, [("bench.top_k.changed", params)], changed=True)
        else:
            m = Measured(rule_k, [("bench.top_k.confirmed", params)], changed=False)
    decide("retrieval.top_k", {"final": rule_k}, m)

    # The winner is what gets recommended; the best score on the headline metric is reported apart.
    ordered = sorted(entries, key=lambda e: -mean(_ndcg(e)))
    best, second = ordered[0], (ordered[1] if len(ordered) > 1 else None)
    margin = boot.difference(_ndcg(best), _ndcg(second)) if second else None
    winner = BenchWinner(
        label=final.label,
        chunking={"value": m_chunking.value, "basis": m_chunking.basis},
        retriever={"value": final.retriever, "basis": m_retriever.basis},
        top_k={"value": measured["retrieval.top_k"].value, "basis": measured["retrieval.top_k"].basis},
        top_by_metric=TopByMetric(
            metric="ndcg",
            label=best.label,
            runner_up=second.label if second else None,
            significant=bool(margin and margin.ci[0] > 0),
            margin=margin,
        ),
    )
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
    retriever = next((d.measured_value for d in result.decisions if d.key == "retrieval.retriever"), None)
    names = [e.retriever for e in entries]
    primary = retriever if retriever in names else names[-1]
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
