"""PDF extraction with PyMuPDF: text layer, headings by font size, tables and scans."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path

from ragcompass.ingest.text import LIST_ITEM, table_block
from ragcompass.models import Block, BlockType, DocKind

# A page with less text than this and an image covering most of it is a scan.
SCANNED_MAX_CHARS = 25
SCANNED_MIN_COVERAGE = 0.5
HEADING_MAX_CHARS = 120
HEADING_SIZE_FACTOR = 1.15
BULLET = re.compile(r"^\s*(?:[•\-–*]|\d+[.)])\s+")


def _image_boxes(page) -> list:
    import pymupdf

    boxes = []
    for info in page.get_image_info():
        rect = pymupdf.Rect(info["bbox"]) & page.rect
        if not rect.is_empty:
            boxes.append(rect)
    return boxes


def _segments(block: dict) -> list[tuple[str, float, bool, int]]:
    """Split a text block into runs of lines that share font size and weight.

    PyMuPDF often returns a heading and the paragraph under it as one block.
    Each run is (text, font size, all bold, line count).
    """
    runs: list[tuple[list[str], float, bool]] = []
    for line in block["lines"]:
        spans = [span for span in line["spans"] if span["text"].strip()]
        if not spans:
            continue
        text = unicodedata.normalize("NFKC", "".join(span["text"] for span in line["spans"])).strip()
        size = round(max(span["size"] for span in spans), 1)
        bold = all(span["flags"] & 16 for span in spans)
        if runs and runs[-1][1] == size and runs[-1][2] == bold:
            runs[-1][0].append(text)
        else:
            runs.append(([text], size, bold))
    return [("\n".join(lines), size, bold, len(lines)) for lines, size, bold in runs]


def extract(path: Path):
    import pymupdf

    from ragcompass.ingest import Extracted

    pymupdf.no_recommend_layout()  # it prints to stdout, which would corrupt --json output
    document = pymupdf.open(path)
    pages: list[tuple[int, list[tuple[float, float, Block | dict]]]] = []
    size_weights: Counter[float] = Counter()
    scanned = 0
    images = 0

    for number, page in enumerate(document, start=1):
        boxes = _image_boxes(page)
        page_area = abs(page.rect) or 1.0
        raw = page.get_text("dict")["blocks"]
        text_blocks = [b for b in raw if b.get("type") == 0]
        chars = sum(len(s["text"].strip()) for b in text_blocks for ln in b["lines"] for s in ln["spans"])
        coverage = max((abs(box) / page_area for box in boxes), default=0.0)
        if chars < SCANNED_MAX_CHARS and coverage >= SCANNED_MIN_COVERAGE:
            scanned += 1
            images += len(boxes) - 1  # the scan itself is not a figure
            pages.append((number, []))
            continue
        images += len(boxes)

        tables = []
        try:
            for table in page.find_tables().tables:
                rows = [["" if c is None else " ".join(str(c).split()) for c in r] for r in table.extract()]
                rows = [r for r in rows if any(r)]
                if rows:
                    tables.append((pymupdf.Rect(table.bbox), rows))
        except Exception:
            tables = []
        # find_tables can report a cell of a larger table as a table of its own.
        tables = [
            (rect, rows)
            for i, (rect, rows) in enumerate(tables)
            if not any(j != i and other.contains(rect) for j, (other, _) in enumerate(tables))
        ]

        items: list[tuple[float, float, Block | dict]] = []
        for rect, rows in tables:
            items.append((rect.y0, rect.x0, table_block(rows, page=number)))
        for block in text_blocks:
            rect = pymupdf.Rect(block["bbox"])
            centre = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
            if any(centre in table_rect for table_rect, _ in tables):
                continue
            for text, size, bold, lines in _segments(block):
                size_weights[size] += len(text)
                items.append((rect.y0, rect.x0, {"text": text, "size": size, "bold": bold, "lines": lines}))
        items.sort(key=lambda item: (item[0], item[1]))  # stable: segments keep block order
        pages.append((number, items))

    body_size = size_weights.most_common(1)[0][0] if size_weights else 0.0
    heading_sizes = sorted(
        {round(s, 1) for s in size_weights if s >= body_size * HEADING_SIZE_FACTOR}, reverse=True
    )

    blocks: list[Block] = []
    for number, items in pages:
        for _, _, item in items:
            if isinstance(item, Block):
                blocks.append(item)
                continue
            blocks.extend(_classify(item, number, body_size, heading_sizes))

    page_count = document.page_count
    document.close()
    if page_count and scanned == page_count:
        kind = DocKind.PDF_SCANNED
    elif scanned:
        kind = DocKind.PDF_MIXED
    else:
        kind = DocKind.PDF_TEXT
    return Extracted(kind=kind, blocks=blocks, pages=page_count, scanned_pages=scanned, images=images)


def _classify(item: dict, page: int, body_size: float, heading_sizes: list[float]) -> list[Block]:
    text, size, bold, lines = item["text"], item["size"], item["bold"], item["lines"]
    short = len(text) <= HEADING_MAX_CHARS and lines <= 2
    size_key = round(size, 1)
    if short and size_key in heading_sizes:
        level = min(heading_sizes.index(size_key) + 1, 3)
        return [Block(type=BlockType.HEADING, text=" ".join(text.split()), level=level, page=page)]
    if short and bold and size >= body_size and not text.rstrip().endswith((".", ":")):
        level = len(heading_sizes) + 1
        return [Block(type=BlockType.HEADING, text=" ".join(text.split()), level=min(level, 3), page=page)]
    if BULLET.match(text):
        out: list[Block] = []
        for line in text.split("\n"):
            if BULLET.match(line) or not out:
                match = LIST_ITEM.match(line)
                out.append(
                    Block(
                        type=BlockType.LIST_ITEM, text=(match.group(1) if match else line).strip(), page=page
                    )
                )
            else:
                out[-1].text += " " + line.strip()
        return out
    return [Block(type=BlockType.PARAGRAPH, text=" ".join(text.split()), page=page)]
