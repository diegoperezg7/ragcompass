"""Data models shared by the CLI, the API and the report renderers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DocKind(StrEnum):
    PDF_TEXT = "pdf_text"
    PDF_SCANNED = "pdf_scanned"
    PDF_MIXED = "pdf_mixed"
    DOCX = "docx"
    MARKDOWN = "markdown"
    HTML = "html"
    CSV = "csv"
    XLSX = "xlsx"
    CODE = "code"
    TEXT = "text"
    IMAGE = "image"
    UNSUPPORTED = "unsupported"


class BlockType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    CODE = "code"


class Block(BaseModel):
    """A structural unit extracted from a document."""

    type: BlockType
    text: str
    level: int = 0  # heading level, 1 = top
    page: int | None = None  # 1-based page number when the source is paged
    rows: list[list[str]] | None = None  # table cells, first row is the header


class Identifiers(BaseModel):
    codes: int = 0  # alphanumeric codes such as SKUs, part numbers, ticket ids
    dates: int = 0
    numbers: int = 0
    per_1k_tokens: float = 0.0  # all identifiers per 1,000 tokens
    codes_per_1k_tokens: float = 0.0


class DocProfile(BaseModel):
    path: str
    kind: DocKind
    size_bytes: int
    pages: int | None = None
    scanned_pages: int = 0
    chars: int = 0
    tokens: int = 0
    language: str | None = None
    headings: int = 0
    tables: int = 0
    table_rows: int = 0
    list_items: int = 0
    code_blocks: int = 0
    images: int = 0
    images_per_page: float | None = None
    image_text_ratio: float = 0.0  # images per 1,000 tokens of text
    identifiers: Identifiers = Field(default_factory=Identifiers)
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class SizeStats(BaseModel):
    min: int = 0
    p50: int = 0
    p95: int = 0
    max: int = 0
    mean: float = 0.0


class Histogram(BaseModel):
    edges: list[int]  # bin edges in tokens; the last bin also holds anything above the last edge
    counts: list[int]  # len(edges) - 1 values


class SimulationResult(BaseModel):
    group: str
    strategy: str
    size: int
    overlap: int
    chunks: int
    tokens: SizeStats
    total_tokens: int  # tokens that would be embedded, overlap included
    overhead_pct: float  # extra tokens embedded compared with the source text
    sentence_cut_pct: float  # chunks with a boundary in the middle of a sentence
    table_cut_pct: float  # chunks that split a table row or hold rows without their header
    orphan_heading_pct: float  # chunks that end on a heading, separated from its section
    code_cut_pct: float  # chunks with a boundary inside a function, block or statement
    tiny_pct: float  # chunks below a quarter of the target size
    damage: float  # sentence + 3 * table + orphan heading + code cuts + tiny, all in %
    histogram: Histogram = Field(default_factory=lambda: Histogram(edges=[], counts=[]))


class ReasonPart(BaseModel):
    id: str  # message id in ragcompass.messages
    params: dict[str, Any] = Field(default_factory=dict)


class Recommendation(BaseModel):
    key: str
    value: Any
    reason: str  # rendered in the report language
    reason_i18n: dict[str, str] = Field(default_factory=dict)  # rendered in every language
    reason_parts: list[ReasonPart] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    basis: str = "rule-based"  # "measured" once a benchmark has confirmed or replaced the value


class IndexEstimate(BaseModel):
    dimension: int
    vectors: int
    float32_bytes: int
    int8_bytes: int
    hnsw_overhead_bytes: int


class EmbeddingCost(BaseModel):
    model: str
    usd_per_million: float
    tokens: int
    usd: float


class CorpusSummary(BaseModel):
    root: str
    files: int
    analysed: int
    tokens: int
    pages: int
    kinds: dict[str, int]
    languages: dict[str, int]
    tokenizer: str


class Report(BaseModel):
    generator: str = "ragcompass"  # first key of the JSON output; marks it as ours when re-scanned
    version: str
    lang: str = "en"
    id: str | None = None  # set when the API keeps the analysis for the chunk explorer
    summary: CorpusSummary
    documents: list[DocProfile]
    simulations: list[SimulationResult]
    recommendations: list[Recommendation]
    index: list[IndexEstimate]
    costs: list[EmbeddingCost]
    config: dict[str, Any]
    llm_summary: str | None = None
    bench: dict[str, Any] | None = None  # BenchResult once a benchmark has run


class BlockView(BaseModel):
    type: BlockType
    start: int
    end: int
    level: int = 0
    page: int | None = None


class Issue(BaseModel):
    kind: str  # sentence_cut, table_cut, orphan_heading, code_cut or tiny
    detail: str | None = None


class ChunkView(BaseModel):
    index: int
    start: int
    end: int
    tokens: int  # extra_tokens included
    extra_tokens: int = 0  # e.g. a table header repeated on top of the span
    issues: list[Issue]
    boundaries: dict[str, str]  # {"start": kind, "end": kind}; kind is clean, sentence, table_row or code


class ChunkExplorer(BaseModel):
    report_id: str
    file: str
    kind: DocKind
    group: str
    strategy: str  # requested strategy
    applied_strategy: str  # what actually ran: falls back to recursive without the structure
    size: int
    overlap: int
    recommended: bool  # strategy, size and overlap equal the recommendation for this group
    strategies: list[str]  # strategies that make sense for this group
    offsets: str = "utf-16"  # start/end are UTF-16 code units, the unit of JavaScript strings
    text: str
    blocks: list[BlockView]
    chunks: list[ChunkView]
    metrics: SimulationResult  # the simulation metrics for this file alone


class Interval(BaseModel):
    mean: float
    ci: list[float]  # [low, high], 95% bootstrap percentile interval


class BenchConfig(BaseModel):
    label: str
    group: str
    strategy: str
    size: int
    overlap: int
    retriever: str  # bm25, dense or hybrid
    recommended: bool  # chunking equal to the rule-based recommendation
    chunks: int
    recall_at_k: Interval
    recall_at_budget: Interval  # span recall keeping ranked chunks within budget_tokens of context
    mrr: Interval
    ndcg: Interval
    curves: dict[str, dict[str, float]]  # {"recall": {"1": ..., "3": ..., "5": ..., "10": ...}}
    index_ms: float
    query_ms: dict[str, float]  # mean and p95


class BenchWinner(BaseModel):
    label: str
    runner_up: str | None = None
    significant: bool = False
    margin: Interval | None = None  # winner minus runner-up on the primary metric, paired bootstrap


class BenchDecision(BaseModel):
    key: str
    basis: str  # measured or rule-based
    rule_value: Any
    measured_value: Any
    changed: bool
    reason: str
    reason_i18n: dict[str, str]
    reason_parts: list[ReasonPart]


class BenchQuery(BaseModel):
    id: str
    text: str
    file: str
    start: int  # UTF-16 offsets into the canonical text of the file
    end: int


class BenchResult(BaseModel):
    k: int
    seed: int
    queries: int
    mode: str  # template, llm or file
    query_kinds: dict[str, int] = Field(default_factory=dict)  # keyphrase, masked, question, llm, file
    # IDF-weighted share of each source's vocabulary repeated by its query: high values favour BM25
    lexical_overlap: dict[str, Any] = Field(default_factory=dict)  # {"mean": float, "by_kind": {...}}
    retrievers: list[str]
    dense_model: str | None
    dense_max_tokens: int | None = None  # tokens the dense model reads per pass; longer chunks are windowed
    budget_tokens: int = 1024
    warnings: list[str]
    primary_metric: str = "ndcg"
    configs: list[BenchConfig]
    winner: BenchWinner
    decisions: list[BenchDecision]
    sample_queries: list[BenchQuery]
    elapsed_ms: float
