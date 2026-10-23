"""Chunking strategies. Each returns character spans over a :class:`Layout`.

Sizes and overlaps are in tokens of the active tokenizer.
"""

from __future__ import annotations

from dataclasses import dataclass

from ragcompass.layout import Layout
from ragcompass.models import BlockType

PROSE_SEPARATORS = ["\n\n", "\n", ". ", " "]
CODE_SEPARATORS = ["\nclass ", "\ndef ", "\nfunction ", "\n\n", "\n", " "]


@dataclass(frozen=True)
class Chunk:
    start: int
    end: int
    extra_tokens: int = 0  # tokens added on top of the span, such as a repeated table header


def fixed(layout: Layout, size: int, overlap: int = 0) -> list[Chunk]:
    """Windows of ``size`` tokens that advance by ``size - overlap``."""
    total = len(layout.tokens)
    if total == 0:
        return []
    step = max(size - overlap, 1)
    chunks = []
    first = 0
    while True:
        last = min(first + size, total)
        chunks.append(Chunk(layout.tokens.offset(first), layout.tokens.offset(last)))
        if last == total:
            return chunks
        first += step


def _fixed_span(layout: Layout, start: int, end: int, size: int) -> list[tuple[int, int]]:
    starts = [p for p in layout.tokens.starts if start <= p < end]
    spans = []
    for i in range(0, len(starts), size):
        stop = starts[i + size] if i + size < len(starts) else end
        spans.append((starts[i] if i else start, stop))
    return spans or [(start, end)]


def _pieces(text: str, start: int, end: int, separator: str) -> list[tuple[int, int]]:
    pieces = []
    position = start
    while True:
        found = text.find(separator, position, end)
        if found == -1:
            break
        cut = found + len(separator)
        pieces.append((position, cut))
        position = cut
    if position < end:
        pieces.append((position, end))
    return pieces


def _recursive(
    layout: Layout, start: int, end: int, size: int, overlap: int, separators: list[str]
) -> list[tuple[int, int]]:
    count = layout.tokens.count
    if count(start, end) <= size:
        return [(start, end)]
    text = layout.text
    for i, separator in enumerate(separators):
        if text.find(separator, start, end) != -1:
            rest = separators[i + 1 :]
            break
    else:
        return _fixed_span(layout, start, end, size)

    out: list[tuple[int, int]] = []
    buffer: list[tuple[int, int]] = []

    def flush() -> None:
        if buffer:
            out.append((buffer[0][0], buffer[-1][1]))

    for piece in _pieces(text, start, end, separator):
        if count(*piece) > size:
            flush()
            buffer = []
            out.extend(_recursive(layout, piece[0], piece[1], size, overlap, rest))
            continue
        if buffer and count(buffer[0][0], piece[1]) > size:
            flush()
            tail: list[tuple[int, int]] = []
            for kept in reversed(buffer):
                if count(kept[0], buffer[-1][1]) > overlap:
                    break
                tail.insert(0, kept)
            buffer = tail
            while buffer and count(buffer[0][0], piece[1]) > size:
                buffer.pop(0)
        buffer.append(piece)
    flush()
    return out


def recursive(
    layout: Layout, size: int, overlap: int = 0, separators: list[str] | None = None
) -> list[Chunk]:
    """Split on the coarsest separator that fits, then pack pieces up to ``size``."""
    if not layout.text:
        return []
    spans = _recursive(layout, 0, len(layout.text), size, overlap, separators or PROSE_SEPARATORS)
    return [Chunk(s, e) for s, e in spans if layout.text[s:e].strip()]


def _pack(layout: Layout, sections: list[tuple[int, int]], size: int) -> list[Chunk]:
    """Merge consecutive sections while they fit; split the ones that do not."""
    count = layout.tokens.count
    chunks: list[Chunk] = []
    current: tuple[int, int] | None = None
    for section in sections:
        if count(*section) > size:
            if current:
                chunks.append(Chunk(*current))
                current = None
            for s, e in _recursive(layout, section[0], section[1], size, 0, PROSE_SEPARATORS):
                chunks.append(Chunk(s, e))
        elif current and count(current[0], section[1]) <= size:
            current = (current[0], section[1])
        else:
            if current:
                chunks.append(Chunk(*current))
            current = section
    if current:
        chunks.append(Chunk(*current))
    return chunks


def heading(layout: Layout, size: int) -> list[Chunk]:
    """One section per heading; small neighbouring sections are packed together."""
    if not layout.text:
        return []
    starts = [0] + [s.start for s in layout.spans if layout.blocks[s.block].type == BlockType.HEADING]
    starts = sorted(set(starts))
    sections = [(a, b) for a, b in zip(starts, starts[1:] + [len(layout.text)], strict=True) if a < b]
    return _pack(layout, sections, size)


def page(layout: Layout, size: int) -> list[Chunk]:
    """One chunk per page, split further only when a page exceeds ``size``."""
    pages: dict[int, list[int]] = {}
    for span in layout.spans:
        number = layout.blocks[span.block].page or 0
        bounds = pages.setdefault(number, [span.start, span.end])
        bounds[1] = span.end
    count = layout.tokens.count
    chunks: list[Chunk] = []
    for start, end in pages.values():
        if count(start, end) <= size:
            chunks.append(Chunk(start, end))
        else:
            chunks.extend(Chunk(s, e) for s, e in _recursive(layout, start, end, size, 0, PROSE_SEPARATORS))
    return chunks


def row(layout: Layout, size: int) -> list[Chunk]:
    """Groups of whole table rows with the header repeated; other blocks are packed."""
    count = layout.tokens.count
    chunks: list[Chunk] = []
    pending: list[tuple[int, int]] = []
    for span in layout.spans:
        block = layout.blocks[span.block]
        if block.type != BlockType.TABLE:
            pending.append((span.start, span.end))
            continue
        lines = _pieces(layout.text, span.start, span.end, "\n")
        header, rows = lines[0], lines[1:]
        header_tokens = count(*header)
        group_start = header[0]  # the first group carries the header in its own span
        if pending:
            # A short caption or sheet name travels with the table instead of becoming its own chunk.
            if count(pending[-1][0], header[1]) <= size // 2:
                group_start = pending[-1][0]
                pending.pop()
            if pending:
                chunks.extend(_pack(layout, pending, size))
            pending = []
        if not rows:
            chunks.append(Chunk(group_start, header[1]))
            continue
        extra = 0
        last = header[1]
        for line in rows:
            if count(group_start, line[1]) + extra > size and last > group_start:
                chunks.append(Chunk(group_start, last, extra))
                group_start, extra = line[0], header_tokens
            last = line[1]
        chunks.append(Chunk(group_start, last, extra))
    if pending:
        chunks.extend(_pack(layout, pending, size))
    return chunks
