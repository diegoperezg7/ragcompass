"""Per-document profile built from the extracted blocks."""

from __future__ import annotations

from ragcompass.ingest import Extracted
from ragcompass.layout import Layout
from ragcompass.models import BlockType, DocKind, DocProfile
from ragcompass.signals import count_identifiers, detect_language


def build_profile(path: str, size_bytes: int, extracted: Extracted, layout: Layout) -> DocProfile:
    blocks = extracted.blocks
    tokens = len(layout.tokens)
    language = None
    if extracted.kind != DocKind.CODE:
        language = detect_language(" ".join(b.text for b in blocks if b.type != BlockType.CODE))
    tables = [b for b in blocks if b.type == BlockType.TABLE]
    return DocProfile(
        path=path,
        kind=extracted.kind,
        size_bytes=size_bytes,
        pages=extracted.pages,
        scanned_pages=extracted.scanned_pages,
        chars=len(layout.text),
        tokens=tokens,
        language=language,
        headings=sum(1 for b in blocks if b.type == BlockType.HEADING),
        tables=len(tables),
        table_rows=sum(max(len(b.rows or []) - 1, 0) for b in tables),
        list_items=sum(1 for b in blocks if b.type == BlockType.LIST_ITEM),
        code_blocks=sum(1 for b in blocks if b.type == BlockType.CODE),
        images=extracted.images,
        images_per_page=round(extracted.images / extracted.pages, 2) if extracted.pages else None,
        image_text_ratio=round(extracted.images * 1000 / tokens, 2) if tokens else 0.0,
        identifiers=count_identifiers(layout.text, tokens),
        error=extracted.error,
        warnings=extracted.warnings,
    )
