import pytest

from ragcompass.tokens import RegexTokenizer, TokenIndex, get_tokenizer


def test_regex_tokenizer_counts_words_and_punctuation():
    tokenizer = RegexTokenizer()
    # Hello , world !
    assert tokenizer.count("Hello, world!") == 4
    assert tokenizer.starts("Hello, world!") == [0, 5, 7, 12]


def test_token_index_counts_spans():
    index = TokenIndex("a b c d e", RegexTokenizer())
    assert len(index) == 5
    assert index.count(0, 3) == 2  # "a b"
    assert index.count(2, 9) == 4  # "b c d e"
    assert index.offset(5) == 9  # past the last token: end of text


def test_forced_regex_tokenizer(monkeypatch):
    get_tokenizer.cache_clear()
    monkeypatch.setenv("RAGCOMPASS_TOKENIZER", "regex")
    assert get_tokenizer().name == "regex-words"
    get_tokenizer.cache_clear()


def test_unknown_tokenizer_is_an_error():
    with pytest.raises(ValueError, match="unknown tokenizer"):
        get_tokenizer("cl100k_typo")


def test_fallback_only_when_encoding_cannot_load(monkeypatch):
    import ragcompass.tokens as tokens

    def offline(_name):
        raise ConnectionError("no network")

    monkeypatch.setattr(tokens, "TiktokenTokenizer", offline)
    get_tokenizer.cache_clear()
    assert get_tokenizer("o200k_base").name == "regex-words"
    get_tokenizer.cache_clear()
