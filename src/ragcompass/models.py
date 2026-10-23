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


class SizeStats(BaseModel):
    min: int = 0
    p50: int = 0
    p95: int = 0
    max: int = 0
    mean: float = 0.0


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
    tiny_pct: float  # chunks below a quarter of the target size
    damage: float  # sentence_cut_pct + 3 * table_cut_pct + orphan_heading_pct + tiny_pct


class Recommendation(BaseModel):
    key: str
    value: Any
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)


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
    version: str
    summary: CorpusSummary
    documents: list[DocProfile]
    simulations: list[SimulationResult]
    recommendations: list[Recommendation]
    index: list[IndexEstimate]
    costs: list[EmbeddingCost]
    config: dict[str, Any]
    llm_summary: str | None = None
