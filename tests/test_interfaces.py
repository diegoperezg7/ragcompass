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
    assert markdown.startswith("# ragcompass report")


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
