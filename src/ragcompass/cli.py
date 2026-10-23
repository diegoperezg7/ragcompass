"""Command line interface: ``ragcompass analyze <path>``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ragcompass import __version__
from ragcompass.analyze import analyze as run_analysis
from ragcompass.messages import LANGUAGES, label
from ragcompass.report import localize, render, to_json, to_markdown, to_yaml
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
    lang: Annotated[str, typer.Option(help="Language of the reasons and labels: en or es.")] = "en",
) -> None:
    """Profile documents, simulate chunking and recommend a RAG configuration."""
    if lang not in LANGUAGES:
        raise typer.BadParameter(f"choose one of: {', '.join(LANGUAGES)}", param_hint="--lang")
    try:
        active = get_tokenizer(tokenizer)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--tokenizer") from exc
    report = localize(run_analysis(path, tokenizer=active), lang)
    if llm_summary:
        from ragcompass.llm import summarize

        try:
            report.llm_summary = summarize(report)
        except Exception as exc:
            err.print(f"[yellow]{label('llm_skipped', lang, error=exc)}[/yellow]")
    if json_out:
        typer.echo(to_json(report))
    elif md_out:
        typer.echo(to_markdown(report), nl=False)
    else:
        render(report, Console(), verbose=all_runs)
    if export:
        export.write_text(to_yaml(report), encoding="utf-8")
        err.print(label("written", lang, path=export))


@app.command()
def bench(
    path: Annotated[Path, typer.Argument(help="File or folder to benchmark.", exists=True)],
    queries: Annotated[
        str, typer.Option(help="How queries are written: template or llm (local Ollama).")
    ] = "template",
    num_queries: Annotated[int, typer.Option("--num-queries", "-n", help="Number of queries.")] = 60,
    queries_file: Annotated[
        Path | None,
        typer.Option(
            "--queries-file",
            exists=True,
            help='Your own queries: JSON list or JSON Lines of {"text", "answer", "file"?, "id"?}.',
        ),
    ] = None,
    seed: Annotated[int, typer.Option(help="Seed for queries and bootstrap intervals.")] = 13,
    k: Annotated[
        int | None, typer.Option(help="Cut-off for the headline metrics (default: recommended top-k).")
    ] = None,
    dense: Annotated[
        bool, typer.Option(help="Measure dense and hybrid retrieval when the bench extra is installed.")
    ] = True,
    export_evalsmith: Annotated[
        Path | None, typer.Option("--export-evalsmith", help="Write qrels, runs and an evalsmith.yaml here.")
    ] = None,
    export: Annotated[
        Path | None, typer.Option("--export", "-o", help="Write the measured configuration as YAML.")
    ] = None,
    json_out: Annotated[
        bool, typer.Option("--json", help="Print the full report, benchmark included, as JSON.")
    ] = False,
    md_out: Annotated[bool, typer.Option("--md", help="Print the report as Markdown.")] = False,
    tokenizer: Annotated[
        str | None, typer.Option(help="cl100k_base (default), any tiktoken encoding, or 'regex'.")
    ] = None,
    lang: Annotated[str, typer.Option(help="Language of the reasons and labels: en or es.")] = "en",
) -> None:
    """Measure retrieval with generated queries and let the measurements correct the rules."""
    from ragcompass import bench as benchmark
    from ragcompass.analyze import run_analysis as analysis_of
    from ragcompass.report import render_bench

    if lang not in LANGUAGES:
        raise typer.BadParameter(f"choose one of: {', '.join(LANGUAGES)}", param_hint="--lang")
    if queries not in ("template", "llm"):
        raise typer.BadParameter("choose template or llm", param_hint="--queries")
    try:
        active = get_tokenizer(tokenizer)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--tokenizer") from exc
    analysis = analysis_of(path, tokenizer=active)
    try:
        run = benchmark.run_bench(analysis, num_queries, seed, k, queries, dense, queries_file)
    except ValueError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    benchmark.apply(analysis, run)
    report = localize(analysis.report, lang)
    if json_out:
        typer.echo(to_json(report))
    elif md_out:
        typer.echo(to_markdown(report), nl=False)
    else:
        render_bench(report, Console())
    if export_evalsmith:
        benchmark.export_evalsmith(run, export_evalsmith)
        err.print(label("exported", lang, path=export_evalsmith))
    if export:
        export.write_text(to_yaml(report), encoding="utf-8")
        err.print(label("written", lang, path=export))


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
