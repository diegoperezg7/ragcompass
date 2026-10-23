"""Markdown, plain text and source code."""

from __future__ import annotations

import re
from pathlib import Path

from ragcompass.models import Block, BlockType, DocKind

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+(.+)$")
TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def table_block(rows: list[list[str]], page: int | None = None) -> Block:
    text = "\n".join("| " + " | ".join(row) + " |" for row in rows)
    return Block(type=BlockType.TABLE, text=text, rows=rows, page=page)


def parse_markdown(source: str) -> list[Block]:
    blocks: list[Block] = []
    paragraph: list[str] = []
    lines = source.splitlines()

    def flush() -> None:
        if paragraph:
            blocks.append(Block(type=BlockType.PARAGRAPH, text=" ".join(paragraph)))
            paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            blocks.append(Block(type=BlockType.CODE, text="\n".join(body)))
        elif match := HEADING.match(stripped):
            flush()
            level = len(match.group(1))
            blocks.append(Block(type=BlockType.HEADING, text=match.group(2), level=level))
        elif stripped.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not TABLE_SEPARATOR.match(lines[i]):
                    rows.append(split_row(lines[i]))
                i += 1
            blocks.append(table_block(rows))
            continue
        elif match := LIST_ITEM.match(line):
            flush()
            blocks.append(Block(type=BlockType.LIST_ITEM, text=match.group(1).strip()))
        elif not stripped:
            flush()
        else:
            paragraph.append(stripped)
        i += 1
    flush()
    return blocks


def extract_code(path: Path):
    from ragcompass.ingest import Extracted, read_text

    source = read_text(path)
    blocks = [Block(type=BlockType.CODE, text=source)] if source.strip() else []
    return Extracted(kind=DocKind.CODE, blocks=blocks)
