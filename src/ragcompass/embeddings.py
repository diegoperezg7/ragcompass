"""Local dense embeddings through fastembed (ONNX, no API keys). Optional: the ``bench`` extra.

Small models read a fixed number of tokens per pass (128 for the multilingual MiniLM, 512 for
bge-small) and silently truncate the rest. A chunk longer than that is split into windows with the
model's own tokenizer, each window is embedded, and the normalised vectors are averaged, so the
whole chunk counts.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

ENGLISH_MODEL = "BAAI/bge-small-en-v1.5"
# multilingual-e5-small is not packaged by fastembed; this is its closest small multilingual option.
MULTILINGUAL_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CACHE_DIR = Path(
    os.environ.get("RAGCOMPASS_MODEL_CACHE", Path.home() / ".cache" / "ragcompass" / "fastembed")
)
INSTALL_HINT = "dense retrieval needs the bench extra: pip install 'ragcompass[bench]'"
CACHE_ENTRIES = 20_000  # about 30 MB of 384-dim float32 vectors
SPECIAL_TOKENS = 2  # [CLS] and [SEP] take two positions of the window


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
    """English-only corpora get an English model; anything else a multilingual one.

    ``RAGCOMPASS_DENSE_MODEL`` overrides the choice with any fastembed model name.
    """
    if override := os.environ.get("RAGCOMPASS_DENSE_MODEL"):
        return override
    if not languages or set(languages) == {"en"}:
        return ENGLISH_MODEL
    return MULTILINGUAL_MODEL


class Embedder:
    def __init__(self, model: str, cache_entries: int = CACHE_ENTRIES) -> None:
        if not available():
            raise EmbeddingsUnavailable(INSTALL_HINT)
        from fastembed import TextEmbedding

        self.name = model
        self._model = TextEmbedding(model, cache_dir=str(CACHE_DIR))
        self._cache: OrderedDict[str, object] = OrderedDict()
        self.cache_entries = cache_entries
        self._tokenizer = None
        self.max_tokens = 512
        inner = getattr(self._model, "model", None)
        tokenizer = getattr(inner, "tokenizer", None)
        if tokenizer is not None:
            from tokenizers import Tokenizer

            self.max_tokens = int((tokenizer.truncation or {}).get("max_length", 512))
            self._tokenizer = Tokenizer.from_str(tokenizer.to_str())  # a copy that never truncates
            self._tokenizer.no_truncation()
            self._tokenizer.no_padding()
        self.windowed = 0  # texts that needed more than one window

    def token_count(self, text: str) -> int:
        if self._tokenizer is None:
            return len(text.split())
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def windows(self, text: str) -> list[str]:
        """Pieces of ``text`` that each fit the model's window."""
        if self._tokenizer is None:
            return [text]
        encoding = self._tokenizer.encode(text, add_special_tokens=False)
        step = max(self.max_tokens - SPECIAL_TOKENS - 4, 8)  # margin: re-tokenising a piece can add one
        if len(encoding.ids) <= step:
            return [text]
        offsets = encoding.offsets
        pieces = []
        for first in range(0, len(offsets), step):
            last = min(first + step, len(offsets)) - 1
            pieces.append(text[offsets[first][0] : offsets[last][1]])
        return [p for p in pieces if p.strip()] or [text]

    def _compute(self, texts: list[str]):
        import numpy as np

        windows = [self.windows(t) for t in texts]
        flat = [w for group in windows for w in group]
        vectors = [np.asarray(v, dtype=np.float32) for v in self._model.embed(flat)]
        out, position = [], 0
        for group in windows:
            block = np.stack(vectors[position : position + len(group)])
            position += len(group)
            block /= np.linalg.norm(block, axis=1, keepdims=True).clip(min=1e-12)
            mean = block.mean(axis=0)
            out.append(mean / (float(np.linalg.norm(mean)) or 1.0))
            if len(group) > 1:
                self.windowed += 1
        return out

    def embed(self, texts: list[str], cache: bool = True):
        """L2-normalised vectors, one row per text. ``cache=False`` always computes (fair timings)."""
        import numpy as np

        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        if not cache:
            return np.stack(self._compute(texts))
        missing = [t for t in dict.fromkeys(texts) if t not in self._cache]
        for text, vector in zip(missing, self._compute(missing) if missing else [], strict=True):
            self._cache[text] = vector
        rows = []
        for text in texts:
            vector = self._cache.get(text)
            if vector is None:  # evicted while this call was filling the cache
                vector = self._compute([text])[0]
            else:
                self._cache.move_to_end(text)
            rows.append(vector)
        while len(self._cache) > self.cache_entries:
            self._cache.popitem(last=False)
        return np.stack(rows)

    def warm_up(self) -> None:
        """Run the model once so the first timed call does not pay for loading the ONNX session."""
        self._compute(["warm up"])


@lru_cache(maxsize=2)
def get_embedder(model: str) -> Embedder:
    return Embedder(model)
