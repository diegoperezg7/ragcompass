import json

import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from ragcompass.api import app, safe_relative
from ragcompass.cli import app as cli
from tests.conftest import CORPUS

client = TestClient(app)


def upload(*names, prefix=""):
    return [("files", (prefix + n, (CORPUS / n).read_bytes())) for n in names]


def test_health():
    assert client.get("/api/health").json()["status"] == "ok"


def test_analyze_upload_returns_report():
    response = client.post("/api/analyze", files=upload("onboarding-handbook.md", "product-catalog.csv"))
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["files"] == 2
    assert {r["key"] for r in body["recommendations"]} >= {"chunking.documents", "chunking.tables"}


def test_folder_upload_keeps_folder_name():
    response = client.post(
        "/api/analyze", files=upload("onboarding-handbook.md", "hx200-faq.html", prefix="kb/")
    )
    assert response.json()["summary"]["root"] == "kb"


def test_yaml_and_markdown_formats():
    files = upload("onboarding-handbook.md")
    config = yaml.safe_load(client.post("/api/analyze?format=yaml", files=files).text)
    assert config["chunking"]["documents"]["strategy"]
    markdown = client.post("/api/analyze?format=md", files=upload("onboarding-handbook.md")).text
    assert "# ragcompass report" in markdown


def test_upload_paths_cannot_escape():
    assert str(safe_relative("../../etc/passwd")) == "etc/passwd"
    assert str(safe_relative("/abs/file.md")) == "abs/file.md"


def test_cli_json_and_export(tmp_path):
    target = tmp_path / "ragcompass.yaml"
    result = CliRunner().invoke(
        cli, ["analyze", str(CORPUS / "onboarding-handbook.md"), "--json", "-o", str(target)]
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["summary"]["files"] == 1
    assert yaml.safe_load(target.read_text())["version"] == 1


def test_cli_table_output():
    result = CliRunner().invoke(cli, ["analyze", str(CORPUS)])
    assert result.exit_code == 0, result.output
    assert "Recommendations" in result.stdout


def test_sample_and_render_roundtrip():
    report = client.post("/api/sample").json()
    assert report["summary"]["files"] == 9
    rendered = client.post("/api/render?format=yaml", json=report)
    assert yaml.safe_load(rendered.text)["chunking"]["tables"]["strategy"] == "row"


def test_cli_rejects_unknown_tokenizer():
    result = CliRunner().invoke(
        cli, ["analyze", str(CORPUS / "onboarding-handbook.md"), "--tokenizer", "nope"]
    )
    assert result.exit_code == 2
    assert "unknown tokenizer" in result.output


def test_conflicting_paths_are_rejected():
    files = [("files", ("a", b"text")), ("files", ("a/b.md", b"# B"))]
    assert client.post("/api/analyze", files=files).status_code == 400
    files = [("files", ("x.md", b"one")), ("files", ("x.md", b"two"))]
    assert client.post("/api/analyze", files=files).status_code == 400


def test_oversized_upload_is_rejected_before_parsing(monkeypatch):
    import ragcompass.api as api

    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 1024)
    small = TestClient(api.BodyLimit(api.app, limit=2048))
    response = small.post("/api/analyze", files=[("files", ("big.txt", b"x" * 10_000))])
    assert response.status_code == 413
    # the endpoint itself also enforces the limit on the file bytes it copies
    response = client.post("/api/analyze", files=[("files", ("big.txt", b"x" * 2_000))])
    assert response.status_code == 413


def test_chunked_body_is_counted():
    import ragcompass.api as api

    small = TestClient(api.BodyLimit(api.app, limit=1024))

    def body():
        for _ in range(10):
            yield b"x" * 512

    response = small.post(
        "/api/render?format=md", content=body(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 413


def test_analysis_does_not_block_health(monkeypatch):
    import asyncio
    import time

    import httpx

    import ragcompass.api as api

    real = api.run_analysis

    def slow_analyze(*args, **kwargs):
        time.sleep(0.6)
        return real(*args, **kwargs)

    monkeypatch.setattr(api, "run_analysis", slow_analyze)

    async def scenario():
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            finished = []

            async def call(name, request):
                response = await request
                finished.append(name)
                return response

            files = {"files": ("notes.md", b"# Notes\n\nA short note.")}
            analysis = asyncio.create_task(call("analysis", http.post("/api/analyze", files=files)))
            await asyncio.sleep(0.05)  # let the upload reach the analysis step
            health = await call("health", http.get("/api/health"))
            assert health.status_code == 200
            assert (await analysis).status_code == 200
            return finished

    # health answers while the slow analysis is still running
    assert asyncio.run(scenario()) == ["health", "analysis"]


def test_cli_lang_option():
    result = CliRunner().invoke(cli, ["analyze", str(CORPUS / "product-catalog.csv"), "--md", "--lang", "es"])
    assert result.exit_code == 0, result.output
    assert "## Recomendaciones" in result.stdout
    assert "filas de datos" in result.stdout
    bad = CliRunner().invoke(cli, ["analyze", str(CORPUS / "product-catalog.csv"), "--lang", "fr"])
    assert bad.exit_code == 2


def test_api_lang_parameter():
    report = client.post("/api/sample?lang=es").json()
    assert report["lang"] == "es"
    parser = next(r for r in report["recommendations"] if r["key"] == "parser.csv")
    assert parser["reason"] == parser["reason_i18n"]["es"]
    rendered = client.post("/api/render?format=md&lang=en", json=report).text
    assert "## Recommendations" in rendered


def test_report_id_and_chunk_explorer():
    report = client.post("/api/sample").json()
    report_id = report["id"]
    assert client.get(f"/api/report/{report_id}").json()["summary"] == report["summary"]

    view = client.get(f"/api/report/{report_id}/chunks", params={"file": "onboarding-handbook.md"}).json()
    assert view["recommended"] is True
    assert view["strategy"] == view["applied_strategy"] == "heading"
    # chunks tile the text in order and their offsets point into it
    assert [c["index"] for c in view["chunks"]] == list(range(len(view["chunks"])))
    assert all(0 <= c["start"] < c["end"] <= len(view["text"]) for c in view["chunks"])
    assert view["metrics"]["chunks"] == len(view["chunks"])

    fixed = client.get(
        f"/api/report/{report_id}/chunks",
        params={"file": "hx200-maintenance-manual.pdf", "strategy": "fixed", "size": 128, "overlap": 0},
    ).json()
    kinds = {issue["kind"] for c in fixed["chunks"] for issue in c["issues"]}
    assert "sentence_cut" in kinds
    assert fixed["recommended"] is False


def test_chunk_explorer_errors():
    report_id = client.post("/api/sample").json()["id"]
    url = f"/api/report/{report_id}/chunks"
    assert client.get("/api/report/nope/chunks", params={"file": "x"}).status_code == 404
    assert client.get(url, params={"file": "missing.md"}).status_code == 422
    assert client.get(url, params={"file": "wiring-diagram.png"}).status_code == 422  # no text
    assert client.get(url, params={"file": "product-catalog.csv", "strategy": "heading"}).status_code == 422
    assert client.get(url, params={"file": "onboarding-handbook.md", "size": 4}).status_code == 422
    params = {"file": "onboarding-handbook.md", "strategy": "fixed", "size": 64, "overlap": 64}
    assert client.get(url, params=params).status_code == 422
