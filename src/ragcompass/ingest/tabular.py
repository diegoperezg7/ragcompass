"""CSV and Excel workbooks."""

from __future__ import annotations

import contextlib
import csv
import io
from pathlib import Path

from ragcompass.ingest.text import table_block
from ragcompass.models import Block, BlockType, DocKind

# Cells read per file before stopping. A small, highly compressed workbook can declare millions
# of rows; this keeps memory bounded and the profile still representative.
MAX_TABLE_CELLS = 1_000_000


class CellBudget:
    def __init__(self, limit: int | None = None) -> None:
        self.limit = limit or MAX_TABLE_CELLS
        self.left = self.limit
        self.exhausted = False

    def take(self, cells: int) -> bool:
        """Consume ``cells``; False once the budget is spent."""
        if self.left - cells < 0:
            self.exhausted = True
            return False
        self.left -= cells
        return True

    def warning(self) -> list[str]:
        return [f"truncated after {self.limit:,} table cells"] if self.exhausted else []


def _clean(rows: list[list[str]]) -> list[list[str]]:
    rows = [[cell.strip() for cell in row] for row in rows]
    rows = [row for row in rows if any(row)]
    width = max((len(row) for row in rows), default=0)
    while width and all(len(row) < width or not row[width - 1] for row in rows):
        width -= 1
    return [row[:width] + [""] * (width - len(row)) for row in rows]


def extract_csv(path: Path):
    from ragcompass.ingest import Extracted, read_text

    source = read_text(path)
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    if delimiter == ",":
        with contextlib.suppress(csv.Error):
            delimiter = csv.Sniffer().sniff(source[:4096], delimiters=",;\t|").delimiter
    budget = CellBudget()
    raw = []
    for row in csv.reader(io.StringIO(source), delimiter=delimiter):
        if not budget.take(len(row)):
            break
        raw.append(row)
    rows = _clean(raw)
    blocks = [table_block(rows)] if rows else []
    return Extracted(kind=DocKind.CSV, blocks=blocks, warnings=budget.warning())


def extract_xlsx(path: Path):
    from openpyxl import load_workbook

    from ragcompass.ingest import Extracted

    workbook = load_workbook(path, read_only=True, data_only=True)
    budget = CellBudget()
    blocks: list[Block] = []
    for sheet in workbook.worksheets:
        raw = []
        for row in sheet.iter_rows(values_only=True):
            if not budget.take(len(row)):
                break
            raw.append(["" if v is None else str(v) for v in row])
        rows = _clean(raw)
        if rows:
            blocks.append(Block(type=BlockType.HEADING, text=sheet.title, level=1))
            blocks.append(table_block(rows))
        if budget.exhausted:
            break
    workbook.close()
    return Extracted(kind=DocKind.XLSX, blocks=blocks, warnings=budget.warning())
