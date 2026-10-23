"""Local dense embeddings through fastembed (ONNX, no API keys). Optional: the ``bench`` extra."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

ENGLISH_MODEL = "BAAI/bge-small-en-v1.5"
# multilingual-e5-small is not packaged by fastembed; this is its closest small multilingual option.
MULTILINGUAL_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CACHE_DIR = Path(
    os.environ.get("RAGCOMPASS_MODEL_CACHE", Path.home() / ".cache" / "ragcompass" / "fastembed")
)
INSTALL_HINT = "dense retrieval needs the bench extra: pip install 'ragcompass[bench]'"


class EmbeddingsUnavailable(RuntimeError):
    pass


def available() -> bool:
    try:
        import fastembed  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False
    return os.environ.get("RAGCOMPASS_DISABLE_DENSE") != "1"


def model_for(languages: dict[str, int]) -> str:
    """English-only corpora get an English model; anything else a multilingual one."""
    if not languages or set(languages) == {"en"}:
        return ENGLISH_MODEL
    return MULTILINGUAL_MODEL


class Embedder:
    def __init__(self, model: str) -> None:
        if not available():
            raise EmbeddingsUnavailable(INSTALL_HINT)
        from fastembed import TextEmbedding

        self.name = model
        self._model = TextEmbedding(model, cache_dir=str(CACHE_DIR))
        self._cache: dict[str, object] = {}

    def embed(self, texts: list[str]):
        """L2-normalised vectors as a numpy array, one row per text. Repeated texts are embedded once."""
        import numpy as np

        missing = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if missing:
            for text, vector in zip(missing, self._model.embed(missing), strict=True):
                norm = float(np.linalg.norm(vector)) or 1.0
                self._cache[text] = np.asarray(vector, dtype=np.float32) / norm
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        return np.stack([self._cache[t] for t in texts])


@lru_cache(maxsize=2)
def get_embedder(model: str) -> Embedder:
    return Embedder(model)
