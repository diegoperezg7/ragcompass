"""Command line interface: ``ragcompass analyze <path>``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ragcompass import __version__
from ragcompass.analyze import analyze as run_analysis
from ragcompass.report import render, to_json, to_markdown, to_yaml
from ragcompass.tokens import get_tokenizer

app = typer.Typer(
    add_completion=False, no_args_is_help=True, help="Measure a corpus and get a reasoned RAG configuration."
)
err = Console(stderr=True)


@app.command()
def analyze(
    path: Annotated[Path, typer.Argument(help="File or folder to analyse.", exists=True)],
    json_out: Annotated[bool, typer.Option("--json", help="Print the full report as JSON.")] = False,
    md_out: Annotated[bool, typer.Option("--md", help="Print the report as Markdown.")] = False,
    export: Annotated[
        Path | None, typer.Option("--export", "-o", help="Write the configuration to this YAML file.")
    ] = None,
    tokenizer: Annotated[
        str | None, typer.Option(help="cl100k_base (default), any tiktoken encoding, or 'regex'.")
    ] = None,
    all_runs: Annotated[bool, typer.Option("--all", help="Show every simulated configuration.")] = False,
    llm_summary: Annotated[
        bool, typer.Option("--llm-summary", help="Add a summary from a local Ollama model.")
    ] = False,
) -> None:
    """Profile documents, simulate chunking and recommend a RAG configuration."""
    try:
        active = get_tokenizer(tokenizer)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--tokenizer") from exc
    report = run_analysis(path, tokenizer=active)
    if llm_summary:
        from ragcompass.llm import summarize

        try:
            report.llm_summary = summarize(report)
        except Exception as exc:
            err.print(f"[yellow]LLM summary skipped: {exc}[/yellow]")
    if json_out:
        typer.echo(to_json(report))
    elif md_out:
        typer.echo(to_markdown(report), nl=False)
    else:
        render(report, Console(), verbose=all_runs)
    if export:
        export.write_text(to_yaml(report), encoding="utf-8")
        err.print(f"Configuration written to {export}")


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: Annotated[int, typer.Option(envvar="PORT")] = 8460,
) -> None:
    """Run the HTTP API (and the web app when it has been built)."""
    import uvicorn

    uvicorn.run("ragcompass.api:app", host=host, port=port)


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)
