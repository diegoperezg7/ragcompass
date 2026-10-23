"""Optional plain-language summary through a local Ollama model.

Off by default. The summary only rephrases the report: recommendations always
come from the deterministic rules.
"""

from __future__ import annotations

import os

import httpx

from ragcompass.models import Report

PROMPT = """You are reviewing a RAG configuration report. In at most six short sentences,
explain the main recommendations and the evidence behind them to an engineer.
Do not invent numbers; only use the ones below.

{recommendations}
"""


def summarize(report: Report, model: str | None = None, host: str | None = None) -> str:
    host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    model = model or os.environ.get("RAGCOMPASS_OLLAMA_MODEL", "llama3.2")
    lines = "\n".join(f"- {r.key}: {r.value} ({r.reason})" for r in report.recommendations)
    response = httpx.post(
        f"{host.rstrip('/')}/api/generate",
        json={"model": model, "prompt": PROMPT.format(recommendations=lines), "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["response"].strip()
