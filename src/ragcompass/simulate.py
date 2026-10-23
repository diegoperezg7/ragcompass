"""Run every chunking strategy over the corpus and measure the result."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ragcompass import chunking
from ragcompass.chunking import Chunk
from ragcompass.layout import Layout
from ragcompass.models import BlockType, DocKind, SimulationResult, SizeStats

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
    sentence_cuts = table_cuts = orphans = 0
    for doc in docs:
        layout = doc.layout
        source_tokens += len(layout.tokens)
        for chunk in chunker(doc):
            sizes.append(layout.tokens.count(chunk.start, chunk.end) + chunk.extra_tokens)
            kinds = {layout.boundary(chunk.start), layout.boundary(chunk.end)}
            sentence_cuts += "sentence" in kinds
            table_cuts += "table_row" in kinds or layout.headerless(
                chunk.start, chunk.end, chunk.extra_tokens
            )
            orphans += layout.ends_with_heading(chunk.start, chunk.end)
    n = len(sizes)
    pct = lambda x: round(100 * x / n, 1) if n else 0.0  # noqa: E731
    total = sum(sizes)
    tiny = sum(1 for s in sizes if s < size * TINY_FRACTION)
    sentence_pct, table_pct, orphan_pct, tiny_pct = (
        pct(sentence_cuts),
        pct(table_cuts),
        pct(orphans),
        pct(tiny),
    )
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
        tiny_pct=tiny_pct,
        damage=round(sentence_pct + TABLE_CUT_WEIGHT * table_pct + orphan_pct + tiny_pct, 1),
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
