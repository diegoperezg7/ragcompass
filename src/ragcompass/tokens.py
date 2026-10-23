"""Token counting with tiktoken and a deterministic offline fallback.

Chunkers need token positions, not only counts, so every tokenizer exposes
the character offset where each token starts.
"""

from __future__ import annotations

import os
import re
from bisect import bisect_left
from functools import lru_cache

_SIMPLE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


class Tokenizer:
    name: str

    def starts(self, text: str) -> list[int]:
        raise NotImplementedError

    def count(self, text: str) -> int:
        return len(self.starts(text))


class RegexTokenizer(Tokenizer):
    """One token per word and per punctuation mark. Used offline and in tests."""

    name = "regex-words"

    def starts(self, text: str) -> list[int]:
        return [m.start() for m in _SIMPLE.finditer(text)]


class TiktokenTokenizer(Tokenizer):
    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        import tiktoken

        self._enc = tiktoken.get_encoding(encoding_name)
        self.name = encoding_name

    def starts(self, text: str) -> list[int]:
        tokens = self._enc.encode(text, disallowed_special=())
        if not tokens:
            return []
        _, offsets = self._enc.decode_with_offsets(tokens)
        return offsets

    def count(self, text: str) -> int:
        return len(self._enc.encode(text, disallowed_special=()))


@lru_cache(maxsize=4)
def get_tokenizer(name: str | None = None) -> Tokenizer:
    """Return the requested tokenizer, falling back to the regex one offline.

    ``RAGCOMPASS_TOKENIZER=regex`` forces the fallback, which keeps counts
    reproducible by hand.
    """
    name = name or os.environ.get("RAGCOMPASS_TOKENIZER", "cl100k_base")
    if name in ("regex", RegexTokenizer.name):
        return RegexTokenizer()
    import tiktoken

    if name not in tiktoken.list_encoding_names():
        choices = ", ".join(sorted(tiktoken.list_encoding_names()) + ["regex"])
        raise ValueError(f"unknown tokenizer {name!r}; choose one of: {choices}")
    try:
        return TiktokenTokenizer(name)
    except Exception:  # a valid encoding whose files are not cached and cannot be downloaded
        return RegexTokenizer()


class TokenIndex:
    """Token start offsets of one text, for fast span counting."""

    def __init__(self, text: str, tokenizer: Tokenizer) -> None:
        self.text = text
        self.starts = tokenizer.starts(text)

    def __len__(self) -> int:
        return len(self.starts)

    def count(self, start: int, end: int) -> int:
        return bisect_left(self.starts, end) - bisect_left(self.starts, start)

    def offset(self, token: int) -> int:
        """Character offset where ``token`` starts (end of text past the last one)."""
        if token >= len(self.starts):
            return len(self.text)
        return self.starts[token]
