"""HTTP API. Upload files (or a whole folder) and get the same report as the CLI."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from ragcompass import __version__
from ragcompass.analyze import analyze
from ragcompass.models import Report
from ragcompass.report import to_markdown, to_yaml

MAX_UPLOAD_BYTES = int(os.environ.get("RAGCOMPASS_MAX_UPLOAD_MB", "50")) * 1024 * 1024
MAX_FILES = 500
REPO = Path(__file__).resolve().parents[2]
WEB_DIST = Path(os.environ.get("RAGCOMPASS_WEB_DIST", REPO / "web" / "dist"))
SAMPLE_DIR = Path(os.environ.get("RAGCOMPASS_SAMPLE_DIR", REPO / "examples" / "corpus"))
Format = Literal["json", "md", "yaml"]

app = FastAPI(title="ragcompass", version=__version__)


def safe_relative(name: str) -> Path:
    """Keep folder structure from the upload while refusing absolute or parent paths."""
    parts = [p for p in PurePosixPath(name.replace("\\", "/")).parts if p not in ("", ".", "..", "/")]
    if not parts:
        raise HTTPException(400, "empty file name")
    return Path(*parts)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/api/analyze", response_model=None)
async def analyze_upload(
    files: Annotated[list[UploadFile], File(description="Files; folder uploads keep relative paths.")],
    format: Annotated[Format, Query()] = "json",
    llm_summary: Annotated[bool, Query()] = False,
) -> Report | PlainTextResponse:
    if not files:
        raise HTTPException(400, "no files uploaded")
    if len(files) > MAX_FILES:
        raise HTTPException(413, f"at most {MAX_FILES} files per request")
    total = 0
    with tempfile.TemporaryDirectory(prefix="ragcompass-") as tmp:
        root = Path(tmp) / "upload"
        for upload in files:
            target = root / safe_relative(upload.filename or "file")
            target.parent.mkdir(parents=True, exist_ok=True)
            data = await upload.read()
            total += len(data)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
            target.write_bytes(data)
        # A folder upload arrives as "folder/a.pdf", "folder/b.md": analyse from that folder.
        entries = list(root.iterdir())
        source = entries[0] if len(entries) == 1 and entries[0].is_dir() else root
        label = source.name if source != root else "upload"
        report = analyze(source, label=label)
    return respond(report, format, llm_summary)


@app.post("/api/sample", response_model=None)
def analyze_sample(
    format: Annotated[Format, Query()] = "json", llm_summary: Annotated[bool, Query()] = False
) -> Report | PlainTextResponse:
    """Analyse the bundled sample corpus."""
    if not SAMPLE_DIR.is_dir():
        raise HTTPException(404, "sample corpus not available")
    return respond(analyze(SAMPLE_DIR, label="sample-corpus"), format, llm_summary)


@app.post("/api/render")
def render_report(report: Report, format: Annotated[Literal["md", "yaml"], Query()]) -> PlainTextResponse:
    """Turn a report the client already has into Markdown or YAML for download."""
    return respond(report, format, False)


def respond(report: Report, format: str, llm_summary: bool) -> Report | PlainTextResponse:
    if llm_summary:
        from ragcompass.llm import summarize

        try:
            report.llm_summary = summarize(report)
        except Exception as exc:
            raise HTTPException(502, f"LLM summary failed: {exc}") from exc
    if format == "md":
        return PlainTextResponse(to_markdown(report), media_type="text/markdown")
    if format == "yaml":
        return PlainTextResponse(to_yaml(report), media_type="application/yaml")
    return report


if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
