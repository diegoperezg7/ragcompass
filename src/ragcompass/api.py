"""HTTP API. Upload files (or a whole folder) and get the same report as the CLI."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from ragcompass import __version__
from ragcompass.analyze import analyze
from ragcompass.models import Report
from ragcompass.report import localize, to_markdown, to_yaml

MAX_UPLOAD_BYTES = int(os.environ.get("RAGCOMPASS_MAX_UPLOAD_MB", "50")) * 1024 * 1024
MAX_FILES = 500
MULTIPART_OVERHEAD = 1024 * 1024  # boundaries and part headers on top of the file bytes
COPY_CHUNK = 1024 * 1024
REPO = Path(__file__).resolve().parents[2]
WEB_DIST = Path(os.environ.get("RAGCOMPASS_WEB_DIST", REPO / "web" / "dist"))
SAMPLE_DIR = Path(os.environ.get("RAGCOMPASS_SAMPLE_DIR", REPO / "examples" / "corpus"))
Format = Literal["json", "md", "yaml"]
Lang = Literal["en", "es"]


class BodyLimit:
    """Reject oversized requests while they stream in, before the multipart parser spools them.

    Checks Content-Length up front and also counts the bytes of chunked bodies. Once over the
    limit it answers 413 itself and tells the app the client went away.
    """

    def __init__(self, app, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.limit:
            return await self.reject(scope, receive, send)
        received = 0
        started = rejected = False

        async def counting_receive():
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    rejected = True
                    if not started:
                        await self.reject(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            nonlocal started
            if rejected:
                return  # the 413 has already been sent
            started = started or message["type"] == "http.response.start"
            await send(message)

        await self.app(scope, counting_receive, guarded_send)

    async def reject(self, scope, receive, send):
        megabytes = MAX_UPLOAD_BYTES // (1024 * 1024)
        response = JSONResponse({"detail": f"upload exceeds {megabytes} MB"}, status_code=413)
        await response(scope, receive, send)


app = FastAPI(title="ragcompass", version=__version__)
app.add_middleware(BodyLimit, limit=MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD)


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
    lang: Annotated[Lang, Query()] = "en",
) -> Report | PlainTextResponse:
    if not files:
        raise HTTPException(400, "no files uploaded")
    if len(files) > MAX_FILES:
        raise HTTPException(413, f"at most {MAX_FILES} files per request")
    total = 0
    with tempfile.TemporaryDirectory(prefix="ragcompass-") as tmp:
        root = Path(tmp) / "upload"
        seen: set[Path] = set()
        for upload in files:
            relative = safe_relative(upload.filename or "file")
            # "a" and "a/b" in one upload cannot both exist on disk.
            if relative in seen or any(parent in seen for parent in relative.parents):
                raise HTTPException(400, f"conflicting paths in upload: {relative.as_posix()}")
            if any(relative in other.parents for other in seen):
                raise HTTPException(400, f"conflicting paths in upload: {relative.as_posix()}")
            seen.add(relative)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as out:
                while chunk := await upload.read(COPY_CHUNK):
                    total += len(chunk)
                    if total > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, f"upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
                    out.write(chunk)
        # A folder upload arrives as "folder/a.pdf", "folder/b.md": analyse from that folder.
        entries = list(root.iterdir())
        source = entries[0] if len(entries) == 1 and entries[0].is_dir() else root
        label = source.name if source != root else "upload"
        # Parsing and chunking are CPU-bound; keep the event loop free for other requests.
        report = await run_in_threadpool(analyze, source, None, label)
    return await run_in_threadpool(respond, report, format, llm_summary, lang)


@app.post("/api/sample", response_model=None)
def analyze_sample(
    format: Annotated[Format, Query()] = "json",
    llm_summary: Annotated[bool, Query()] = False,
    lang: Annotated[Lang, Query()] = "en",
) -> Report | PlainTextResponse:
    """Analyse the bundled sample corpus."""
    if not SAMPLE_DIR.is_dir():
        raise HTTPException(404, "sample corpus not available")
    return respond(analyze(SAMPLE_DIR, label="sample-corpus"), format, llm_summary, lang)


@app.post("/api/render")
def render_report(
    report: Report,
    format: Annotated[Literal["md", "yaml"], Query()],
    lang: Annotated[Lang, Query()] = "en",
) -> PlainTextResponse:
    """Turn a report the client already has into Markdown or YAML for download."""
    return respond(report, format, False, lang)


def respond(report: Report, format: str, llm_summary: bool, lang: str = "en") -> Report | PlainTextResponse:
    localize(report, lang)
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
