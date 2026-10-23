"""File type detection and structural extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ragcompass.models import Block, DocKind

CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".hpp",
    ".cs",
    ".swift",
    ".scala",
    ".sql",
    ".sh",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp"}
TEXT_EXTENSIONS = {".txt", ".rst", ".log"}
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
HTML_EXTENSIONS = {".html", ".htm"}
IGNORED_NAMES = {".DS_Store", "ragcompass.yaml"}
IGNORED_DIRS = {".git", "node_modules", ".venv", "__pycache__"}


@dataclass
class Extracted:
    kind: DocKind
    blocks: list[Block] = field(default_factory=list)
    pages: int | None = None
    scanned_pages: int = 0
    images: int = 0
    error: str | None = None


def detect_kind(path: Path) -> DocKind:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return DocKind.PDF_TEXT  # refined to scanned or mixed after reading pages
    if ext == ".docx":
        return DocKind.DOCX
    if ext in MARKDOWN_EXTENSIONS:
        return DocKind.MARKDOWN
    if ext in HTML_EXTENSIONS:
        return DocKind.HTML
    if ext in (".csv", ".tsv"):
        return DocKind.CSV
    if ext in (".xlsx", ".xlsm"):
        return DocKind.XLSX
    if ext in CODE_EXTENSIONS:
        return DocKind.CODE
    if ext in TEXT_EXTENSIONS:
        return DocKind.TEXT
    if ext in IMAGE_EXTENSIONS:
        return DocKind.IMAGE
    return DocKind.UNSUPPORTED


def iter_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in IGNORED_NAMES:
            continue
        if any(part in IGNORED_DIRS or part.startswith(".") for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return files


def extract(path: Path) -> Extracted:
    from ragcompass.ingest import docx, html, pdf, tabular, text

    kind = detect_kind(path)
    try:
        match kind:
            case DocKind.PDF_TEXT:
                return pdf.extract(path)
            case DocKind.DOCX:
                return docx.extract(path)
            case DocKind.HTML:
                return html.extract(path)
            case DocKind.CSV:
                return tabular.extract_csv(path)
            case DocKind.XLSX:
                return tabular.extract_xlsx(path)
            case DocKind.MARKDOWN | DocKind.TEXT:
                return Extracted(kind=kind, blocks=text.parse_markdown(read_text(path)))
            case DocKind.CODE:
                return text.extract_code(path)
            case DocKind.IMAGE:
                return Extracted(kind=kind, images=1)
            case _:
                return Extracted(kind=kind)
    except Exception as exc:  # a broken file must not stop the whole corpus
        return Extracted(kind=kind, error=f"{type(exc).__name__}: {exc}")


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")
