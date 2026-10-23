from pathlib import Path

import pytest

from ragcompass.layout import Layout
from ragcompass.models import Block, BlockType
from ragcompass.tokens import RegexTokenizer

CORPUS = Path(__file__).resolve().parents[1] / "examples" / "corpus"


@pytest.fixture
def tokenizer():
    return RegexTokenizer()


@pytest.fixture
def layout(tokenizer):
    def build(*blocks: tuple[BlockType, str] | Block) -> Layout:
        items = [b if isinstance(b, Block) else Block(type=b[0], text=b[1]) for b in blocks]
        return Layout(items, tokenizer)

    return build
