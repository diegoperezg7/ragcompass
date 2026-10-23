"""HTML pages, with navigation and scripts stripped."""

from __future__ import annotations

from pathlib import Path

from ragcompass.ingest.text import table_block
from ragcompass.models import Block, BlockType, DocKind

BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table", "pre", "blockquote", "dd", "dt"]
NOISE_TAGS = ["script", "style", "noscript", "nav", "footer", "template", "svg", "form"]


def extract(path: Path):
    from bs4 import BeautifulSoup

    from ragcompass.ingest import Extracted, read_text

    soup = BeautifulSoup(read_text(path), "html.parser")
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    images = len(soup.find_all("img"))
    root = soup.body or soup
    blocks: list[Block] = []
    for element in root.find_all(BLOCK_TAGS):
        # Nested blocks (a <p> inside an <li>) are covered by their outermost block.
        if element.find_parent(BLOCK_TAGS):
            continue
        name = element.name
        if name == "table":
            rows = [
                [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
                for tr in element.find_all("tr")
            ]
            rows = [row for row in rows if any(row)]
            if rows:
                blocks.append(table_block(rows))
            continue
        text = element.get_text(" ", strip=True)
        if not text:
            continue
        if name[0] == "h" and name[1:].isdigit():
            blocks.append(Block(type=BlockType.HEADING, text=text, level=int(name[1])))
        elif name == "li":
            blocks.append(Block(type=BlockType.LIST_ITEM, text=text))
        elif name == "pre":
            blocks.append(Block(type=BlockType.CODE, text=element.get_text()))
        else:
            blocks.append(Block(type=BlockType.PARAGRAPH, text=text))
    return Extracted(kind=DocKind.HTML, blocks=blocks, images=images)
