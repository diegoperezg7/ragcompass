"""Chunk-level view of one file under any strategy, for the web chunk explorer."""

from __future__ import annotations

from bisect import bisect_right

from ragcompass.analyze import Analysis
from ragcompass.models import BlockType, BlockView, ChunkExplorer, ChunkView, Issue
from ragcompass.simulate import (
    Doc,
    chunk_doc,
    chunk_flags,
    chunk_tokens,
    group_of,
    has_headings,
    is_paged,
    measure,
)

STRATEGIES = {
    "documents": ["heading", "page", "recursive", "fixed"],
    "tables": ["row", "recursive", "fixed"],
    "code": ["recursive", "fixed"],
}
MIN_SIZE, MAX_SIZE = 16, 8192
DETAILS = {
    "sentence_cut": "a boundary falls inside a sentence",
    "table_cut": "splits a table row or holds rows without their header",
    "orphan_heading": "ends on a heading, separated from its section",
    "code_cut": "a boundary falls inside a function, block or statement",
    "tiny": "smaller than a quarter of the target size",
}


class ExplorerError(ValueError):
    pass


def utf16_offsets(text: str):
    """Map code-point offsets to UTF-16 offsets (identity when no character is astral)."""
    astral = [i for i, ch in enumerate(text) if ord(ch) > 0xFFFF]
    if not astral:
        return lambda offset: offset
    return lambda offset: offset + bisect_right(astral, offset - 1)


def applied(doc: Doc, strategy: str) -> str:
    has = {
        "heading": has_headings(doc),
        "page": is_paged(doc),
        "row": any(b.type == BlockType.TABLE for b in doc.layout.blocks),
    }
    return strategy if has.get(strategy, True) else "recursive"


def explore(
    analysis: Analysis,
    report_id: str,
    file: str,
    strategy: str | None = None,
    size: int | None = None,
    overlap: int | None = None,
) -> ChunkExplorer:
    doc = analysis.docs.get(file)
    if doc is None:
        raise ExplorerError(f"unknown file {file!r}")
    group = group_of(doc.kind)
    if group is None or not len(doc.layout.tokens):
        raise ExplorerError(f"{file!r} has no text to chunk")
    pick = next(r.value for r in analysis.report.recommendations if r.key == f"chunking.{group}")
    strategy = strategy or pick["strategy"]
    size = size if size is not None else pick["size"]
    overlap = overlap if overlap is not None else (pick["overlap"] if strategy == pick["strategy"] else 0)
    if strategy not in STRATEGIES[group]:
        raise ExplorerError(f"strategy must be one of {', '.join(STRATEGIES[group])} for {group}")
    if not MIN_SIZE <= size <= MAX_SIZE:
        raise ExplorerError(f"size must be between {MIN_SIZE} and {MAX_SIZE}")
    if strategy not in ("fixed", "recursive"):
        overlap = 0  # boundaries follow structure; overlap does not apply
    if not 0 <= overlap < size:
        raise ExplorerError("overlap must be at least 0 and smaller than size")

    layout = doc.layout
    chunks = chunk_doc(doc, group, strategy, size, overlap)
    to16 = utf16_offsets(layout.text)
    return ChunkExplorer(
        report_id=report_id,
        file=file,
        kind=doc.kind,
        group=group,
        strategy=strategy,
        applied_strategy=applied(doc, strategy),
        size=size,
        overlap=overlap,
        recommended=(strategy, size, overlap) == (pick["strategy"], pick["size"], pick["overlap"]),
        strategies=STRATEGIES[group],
        text=layout.text,
        blocks=[
            BlockView(
                type=layout.blocks[span.block].type,
                start=to16(span.start),
                end=to16(span.end),
                level=layout.blocks[span.block].level,
                page=layout.blocks[span.block].page,
            )
            for span in layout.spans
        ],
        chunks=[
            ChunkView(
                index=i,
                start=to16(chunk.start),
                end=to16(chunk.end),
                tokens=chunk_tokens(layout, chunk),
                extra_tokens=chunk.extra_tokens,
                issues=[Issue(kind=flag, detail=DETAILS[flag]) for flag in chunk_flags(layout, chunk, size)],
                boundaries={"start": layout.boundary(chunk.start), "end": layout.boundary(chunk.end)},
            )
            for i, chunk in enumerate(chunks)
        ],
        metrics=measure(group, strategy, size, overlap, [doc], lambda d: chunks),
    )
