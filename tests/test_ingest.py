"""Counts checked by hand against the content written in examples/generate.py."""

import pytest

from ragcompass.ingest import extract
from ragcompass.layout import Layout
from ragcompass.models import BlockType, DocKind
from ragcompass.profile import build_profile
from tests.conftest import CORPUS


def profile(name, tokenizer):
    path = CORPUS / name
    extracted = extract(path)
    assert extracted.error is None
    return build_profile(name, path.stat().st_size, extracted, Layout(extracted.blocks, tokenizer))


def test_text_pdf(tokenizer):
    p = profile("hx200-maintenance-manual.pdf", tokenizer)
    assert p.kind == DocKind.PDF_TEXT
    assert p.headings == 8  # 1 title, 5 numbered sections, 2 subsections
    assert p.tables == 2
    assert p.table_rows == 5 + 7  # maintenance tasks + verification points
    assert p.list_items == 4 + 4  # safety rules + troubleshooting codes
    assert p.images == 1  # wiring diagram
    assert p.scanned_pages == 0
    assert p.language == "en"


def test_scanned_pdf_has_no_text_layer(tokenizer):
    p = profile("scanned-invoice.pdf", tokenizer)
    assert p.kind == DocKind.PDF_SCANNED
    assert p.pages == p.scanned_pages == 1
    assert p.tokens == 0
    assert p.images == 0  # the scan itself is not counted as a figure


def test_docx(tokenizer):
    p = profile("politica-devoluciones.docx", tokenizer)
    assert p.kind == DocKind.DOCX
    assert p.headings == 5
    assert p.list_items == 4
    assert (p.tables, p.table_rows) == (1, 4)
    assert p.images == 1
    assert p.language == "es"


def test_markdown(tokenizer):
    p = profile("onboarding-handbook.md", tokenizer)
    assert p.headings == 6  # 1 title, 4 sections, 1 subsection
    assert (p.tables, p.table_rows) == (1, 3)
    assert p.list_items == 4 + 3
    assert p.code_blocks == 1


def test_html_strips_navigation(tokenizer):
    path = CORPUS / "hx200-faq.html"
    extracted = extract(path)
    text = " ".join(b.text for b in extracted.blocks)
    assert "Products" not in text  # <nav>
    assert "fictional" not in text  # <footer>
    assert "analytics" not in text  # <script>
    p = profile("hx200-faq.html", tokenizer)
    assert p.headings == 6
    assert p.images == 2


def test_csv(tokenizer):
    p = profile("product-catalog.csv", tokenizer)
    assert p.kind == DocKind.CSV
    assert (p.tables, p.table_rows) == (1, 40)
    assert p.identifiers.dates == 40  # one last_updated date per row


def test_xlsx_one_table_per_sheet(tokenizer):
    p = profile("warehouse-stock.xlsx", tokenizer)
    assert (p.headings, p.tables, p.table_rows) == (2, 2, 8 + 6)


@pytest.mark.parametrize(
    ("name", "kind"),
    [("ticket_export.py", DocKind.CODE), ("wiring-diagram.png", DocKind.IMAGE)],
)
def test_other_kinds(name, kind):
    extracted = extract(CORPUS / name)
    assert extracted.kind == kind
    if kind == DocKind.CODE:
        assert extracted.blocks[0].type == BlockType.CODE
    else:
        assert extracted.images == 1


def test_broken_file_is_reported_not_raised(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    assert extract(broken).error
