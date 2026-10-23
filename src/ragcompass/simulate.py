"""Run every chunking strategy over the corpus and measure the result."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass

from ragcompass import chunking
from ragcompass.chunking import Chunk
from ragcompass.layout import Layout
from ragcompass.models import BlockType, DocKind, Histogram, SimulationResult, SizeStats

SIZES = (256, 512, 1024)
OVERLAPS = (0.0, 0.1, 0.2)
TINY_FRACTION = 0.25
TABLE_CUT_WEIGHT = 3
STRUCTURE_SHARE = 0.5

GROUPS = {
    "documents": {
        DocKind.PDF_TEXT,
        DocKind.PDF_MIXED,
        DocKind.DOCX,
        DocKind.MARKDOWN,
        DocKind.HTML,
        DocKind.TEXT,
    },
    "tables": {DocKind.CSV, DocKind.XLSX},
    "code": {DocKind.CODE},
}
# Tie-break order when two strategies damage the text equally: prefer structure.
PREFERENCE = ("heading", "row", "page", "recursive", "fixed")


@dataclass
class Doc:
    kind: DocKind
    layout: Layout
    path: str = ""


FLAGS = ("sentence_cut", "table_cut", "orphan_heading", "code_cut", "tiny")


def chunk_tokens(layout: Layout, chunk: Chunk) -> int:
    return layout.tokens.count(chunk.start, chunk.end) + chunk.extra_tokens


HISTOGRAM_BINS = 10


def histogram(sizes: list[int], size: int) -> Histogram:
    """Chunk sizes in ten equal bins from 0 to the target size."""
    edges = [round(size * i / HISTOGRAM_BINS) for i in range(HISTOGRAM_BINS + 1)]
    counts = [0] * HISTOGRAM_BINS
    for value in sizes:
        counts[min(bisect_right(edges, value) - 1, HISTOGRAM_BINS - 1)] += 1
    return Histogram(edges=edges, counts=counts)


def chunk_flags(layout: Layout, chunk: Chunk, size: int) -> list[str]:
    """The kinds of damage one chunk shows, in the order of :data:`FLAGS`."""
    kinds = {layout.boundary(chunk.start), layout.boundary(chunk.end)}
    flags = []
    if "sentence" in kinds:
        flags.append("sentence_cut")
    if "table_row" in kinds or layout.headerless(chunk.start, chunk.end, chunk.extra_tokens):
        flags.append("table_cut")
    if layout.ends_with_heading(chunk.start, chunk.end):
        flags.append("orphan_heading")
    if "code" in kinds:
        flags.append("code_cut")
    if chunk_tokens(layout, chunk) < size * TINY_FRACTION:
        flags.append("tiny")
    return flags


def group_of(kind: DocKind) -> str | None:
    for name, kinds in GROUPS.items():
        if kind in kinds:
            return name
    return None


def token_share(docs: list[Doc], predicate: Callable[[Doc], bool]) -> float:
    total = sum(len(d.layout.tokens) for d in docs)
    return sum(len(d.layout.tokens) for d in docs if predicate(d)) / total if total else 0.0


def has_headings(doc: Doc) -> bool:
    return any(b.type == BlockType.HEADING for b in doc.layout.blocks)


def is_paged(doc: Doc) -> bool:
    return doc.kind.value.startswith("pdf")


def strategies_for(group: str, docs: list[Doc]) -> list[str]:
    """Structure-aware strategies compete only when most of the group's text has that structure."""
    names = ["fixed", "recursive"]
    if group == "documents" and token_share(docs, has_headings) >= STRUCTURE_SHARE:
        names.append("heading")
    if group == "documents" and token_share(docs, is_paged) >= STRUCTURE_SHARE:
        names.append("page")
    if group == "tables":
        names.append("row")
    return names


def chunk_doc(doc: Doc, group: str, strategy: str, size: int, overlap: int) -> list[Chunk]:
    layout = doc.layout
    separators = chunking.CODE_SEPARATORS if group == "code" else None
    if strategy == "fixed":
        return chunking.fixed(layout, size, overlap)
    if strategy == "heading" and has_headings(doc):
        return chunking.heading(layout, size)
    if strategy == "page" and is_paged(doc):
        return chunking.page(layout, size)
    if strategy == "row" and any(b.type == BlockType.TABLE for b in layout.blocks):
        return chunking.row(layout, size)
    # Documents without the structure a strategy needs fall back to recursive splitting.
    return chunking.recursive(layout, size, overlap if strategy == "recursive" else 0, separators)


def percentile(values: list[int], q: float) -> int:
    """Nearest-rank percentile, so results are always observed chunk sizes."""
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * q // 100))
    return ordered[int(rank) - 1]


def measure(
    group: str,
    strategy: str,
    size: int,
    overlap: int,
    docs: list[Doc],
    chunker: Callable[[Doc], list[Chunk]],
) -> SimulationResult:
    sizes: list[int] = []
    source_tokens = 0
    counts = dict.fromkeys(FLAGS, 0)
    for doc in docs:
        layout = doc.layout
        source_tokens += len(layout.tokens)
        for chunk in chunker(doc):
            sizes.append(chunk_tokens(layout, chunk))
            for flag in chunk_flags(layout, chunk, size):
                counts[flag] += 1
    n = len(sizes)
    pct = lambda x: round(100 * x / n, 1) if n else 0.0  # noqa: E731
    total = sum(sizes)
    sentence_pct, table_pct, orphan_pct, code_pct, tiny_pct = (pct(counts[flag]) for flag in FLAGS)
    return SimulationResult(
        group=group,
        strategy=strategy,
        size=size,
        overlap=overlap,
        chunks=n,
        tokens=SizeStats(
            min=min(sizes, default=0),
            p50=percentile(sizes, 50),
            p95=percentile(sizes, 95),
            max=max(sizes, default=0),
            mean=round(total / n, 1) if n else 0.0,
        ),
        total_tokens=total,
        overhead_pct=round(100 * (total - source_tokens) / source_tokens, 1) if source_tokens else 0.0,
        sentence_cut_pct=sentence_pct,
        table_cut_pct=table_pct,
        orphan_heading_pct=orphan_pct,
        code_cut_pct=code_pct,
        tiny_pct=tiny_pct,
        damage=round(sentence_pct + TABLE_CUT_WEIGHT * table_pct + orphan_pct + code_pct + tiny_pct, 1),
        histogram=histogram(sizes, size),
    )


def simulate(docs: list[Doc]) -> list[SimulationResult]:
    results: list[SimulationResult] = []
    by_group: dict[str, list[Doc]] = {}
    for doc in docs:
        group = group_of(doc.kind)
        if group and len(doc.layout.tokens):
            by_group.setdefault(group, []).append(doc)
    for group, members in by_group.items():
        for strategy in strategies_for(group, members):
            overlaps = OVERLAPS if strategy in ("fixed", "recursive") else (0.0,)
            for size in SIZES:
                for fraction in overlaps:
                    overlap = int(size * fraction)
                    results.append(
                        measure(
                            group,
                            strategy,
                            size,
                            overlap,
                            members,
                            lambda d, s=strategy, z=size, o=overlap, g=group: chunk_doc(d, g, s, z, o),
                        )
                    )
    return results
