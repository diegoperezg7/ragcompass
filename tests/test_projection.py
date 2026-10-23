import pytest

from ragcompass import embeddings
from ragcompass.analyze import run_analysis
from ragcompass.tokens import RegexTokenizer
from tests.conftest import CORPUS


def models_cached() -> bool:
    if not embeddings.available():
        return False
    name = embeddings.model_for({"en": 1, "es": 1}).split("/")[-1]
    return any(name in path.name for path in embeddings.CACHE_DIR.glob("models--*"))


def test_pca_is_deterministic_and_signed():
    np = pytest.importorskip("numpy")
    from ragcompass.projection import _pca

    rng = np.random.default_rng(0)
    matrix = rng.normal(size=(30, 8)).astype("float32")
    first, _, components, explained = _pca(matrix)
    second, *_ = _pca(matrix.copy())
    assert np.allclose(first, second)
    assert first.shape == (30, 2)
    assert all(row[np.argmax(np.abs(row))] > 0 for row in components)
    assert 0 < explained[1] <= explained[0] < 1


@pytest.mark.skipif(not models_cached(), reason="bench extra or embedding model not available")
def test_projection_of_the_sample_corpus():
    from ragcompass.projection import project

    analysis = run_analysis(CORPUS, tokenizer=RegexTokenizer())
    result = project(analysis)
    assert result == project(analysis)  # same picture every time
    points = result["points"]
    assert points and all(-1 <= p["x"] <= 1 and -1 <= p["y"] <= 1 for p in points)
    assert [p["id"] for p in points] == list(range(len(points)))
    assert result["queries"] and all(
        len(q["neighbors"]) == 5 and all(0 <= n < len(points) for n in q["neighbors"])
        for q in result["queries"]
    )


def test_projection_needs_the_extra(monkeypatch):
    from fastapi.testclient import TestClient

    from ragcompass.api import app

    client = TestClient(app)
    report_id = client.post("/api/sample").json()["id"]
    monkeypatch.setattr(embeddings, "available", lambda: False)
    response = client.get(f"/api/report/{report_id}/projection")
    assert response.status_code == 501
    assert "bench" in response.json()["detail"]
