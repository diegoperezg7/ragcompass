"""Canonical text of a document with the character span of every block.

Every chunker works on this text, so all strategies are measured against the
same boundaries.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from ragcompass.models import Block, BlockType
from ragcompass.tokens import TokenIndex, Tokenizer

SEPARATOR = "\n\n"
SENTENCE_END = ".!?…"
CLOSERS = "\"')]»”’"
OPENERS = (":", "{", "(", "[", ",", "\\", "=", "+", "&&", "||")
DEFINITIONS = ("def ", "async def ", "class ", "function ", "export ", "@", "fn ", "func ")
CONTINUATIONS = (")", "]", "}", "else", "elif", "except", "finally", "catch")


def _line_before(text: str, start: int, position: int) -> str | None:
    """Last non-blank line in ``text[start:position]``."""
    end = position - 1
    while end > start:
        line_start = max(text.rfind("\n", start, end) + 1, start)
        if text[line_start:end].strip():
            return text[line_start:end]
        end = line_start - 1
    return None


def _line_after(text: str, position: int, end: int) -> str | None:
    """First non-blank line in ``text[position:end]``."""
    while position < end:
        line_end = text.find("\n", position, end)
        line_end = end if line_end == -1 else line_end
        if text[position:line_end].strip():
            return text[position:line_end]
        position = line_end + 1
    return None


@dataclass(frozen=True)
class Span:
    block: int
    start: int
    end: int


class Layout:
    def __init__(self, blocks: list[Block], tokenizer: Tokenizer) -> None:
        self.blocks = blocks
        parts: list[str] = []
        spans: list[Span] = []
        offset = 0
        for i, block in enumerate(blocks):
            if parts:
                parts.append(SEPARATOR)
                offset += len(SEPARATOR)
            spans.append(Span(i, offset, offset + len(block.text)))
            parts.append(block.text)
            offset += len(block.text)
        self.text = "".join(parts)
        self.spans = spans
        self._starts = [s.start for s in spans]
        self.tokens = TokenIndex(self.text, tokenizer)
        # (header end, table end) of every table with at least one data row
        self.tables = []
        for span in spans:
            if blocks[span.block].type == BlockType.TABLE:
                newline = self.text.find("\n", span.start, span.end)
                if newline != -1:
                    self.tables.append((newline, span.end))

    def headerless(self, start: int, end: int, extra_tokens: int = 0) -> bool:
        """True when the chunk holds table rows but neither the header nor a repeated copy."""
        if extra_tokens:
            return False
        for header_end, table_end in self.tables:
            if start > header_end and start < table_end and self.text[start : min(end, table_end)].strip():
                return True
        return False

    def ends_with_heading(self, start: int, end: int) -> bool:
        """True when the last thing in the chunk is a heading, cut off from its content."""
        tail = self.text[start:end].rstrip()
        if not tail or start + len(tail) >= len(self.text.rstrip()):
            return False
        i = bisect_right(self._starts, start + len(tail) - 1) - 1
        return i >= 0 and self.blocks[self.spans[i].block].type == BlockType.HEADING

    def block_at(self, position: int) -> Span | None:
        """The block that strictly contains ``position``, if any."""
        i = bisect_right(self._starts, position) - 1
        if i < 0:
            return None
        span = self.spans[i]
        if span.start < position < span.end:
            return span
        return None

    def _code_boundary(self, span: Span, position: int) -> str:
        """A code boundary is clean only between top-level statements or definitions."""
        text = self.text
        if text[position - 1] != "\n":
            return "code"  # in the middle of a line
        previous = _line_before(text, span.start, position)
        following = _line_after(text, position, span.end)
        if previous is None or following is None:
            return "clean"
        if previous.lstrip().startswith("@") or previous.rstrip().endswith(OPENERS):
            return "code"  # decorator or open statement continues below
        stripped = following.lstrip()
        if stripped.startswith(DEFINITIONS):
            return "clean"  # a new function or class, possibly a method
        if following[0].isspace() or stripped.startswith(CONTINUATIONS):
            return "code"  # inside an indented block or a multi-line construct
        return "clean"

    def boundary(self, position: int) -> str:
        """Classify a chunk boundary: ``clean``, ``sentence``, ``table_row`` or ``code``."""
        span = self.block_at(position)
        if span is None:
            return "clean"
        block = self.blocks[span.block]
        text = self.text
        if block.type == BlockType.TABLE:
            return "clean" if text[position - 1] == "\n" or text[position] == "\n" else "table_row"
        if block.type == BlockType.CODE:
            return self._code_boundary(span, position)
        before = text[span.start : position].rstrip()
        if not before:
            return "clean"
        if not text[span.start + len(before) : span.end].strip():
            return "clean"  # only whitespace left in the block
        stripped = before.rstrip(CLOSERS)
        at_gap = text[position - 1].isspace() or text[position].isspace()
        if stripped and stripped[-1] in SENTENCE_END and at_gap:
            return "clean"
        return "sentence"
