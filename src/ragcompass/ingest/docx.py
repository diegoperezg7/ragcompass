"""Word documents, read in body order so tables stay where they appear."""

from __future__ import annotations

import re
from pathlib import Path

from ragcompass.ingest.text import table_block
from ragcompass.models import Block, BlockType, DocKind

HEADING_STYLE = re.compile(r"^(?:Heading|Título|Titulo)\s*(\d)$", re.IGNORECASE)


def extract(path: Path):
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    from ragcompass.ingest import Extracted

    document = docx.Document(str(path))
    blocks: list[Block] = []
    for element in document.element.body.iterchildren():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(element, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style = paragraph.style.name if paragraph.style is not None else ""
            if style == "Title":
                blocks.append(Block(type=BlockType.HEADING, text=text, level=1))
            elif match := HEADING_STYLE.match(style):
                blocks.append(Block(type=BlockType.HEADING, text=text, level=int(match.group(1))))
            elif style.startswith("List") or element.pPr is not None and element.pPr.numPr is not None:
                blocks.append(Block(type=BlockType.LIST_ITEM, text=text))
            else:
                blocks.append(Block(type=BlockType.PARAGRAPH, text=text))
        elif tag == "tbl":
            table = Table(element, document)
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            if rows:
                blocks.append(table_block(rows))
    images = len(document.element.body.xpath(".//a:blip"))
    return Extracted(kind=DocKind.DOCX, blocks=blocks, images=images)
