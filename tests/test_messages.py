import string

import pytest

from ragcompass.analyze import analyze
from ragcompass.messages import LABELS, LANGUAGES, MESSAGES, Formatter, render_message
from ragcompass.report import localize
from ragcompass.tokens import RegexTokenizer
from tests.conftest import CORPUS


def fields(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


@pytest.mark.parametrize("table", [MESSAGES, LABELS], ids=["messages", "labels"])
def test_every_key_exists_in_every_language(table):
    keys = {lang: set(table[lang]) for lang in LANGUAGES}
    assert keys["en"] == keys["es"]
    for key in keys["en"]:
        assert fields(table["en"][key]) == fields(table["es"][key]), key


def test_every_reason_renders_in_every_language(tmp_path):
    (tmp_path / "words.txt").write_text(" ".join(["word"] * 3000))  # exercises the overlap message
    reports = [
        analyze(CORPUS, tokenizer=RegexTokenizer()),
        analyze(CORPUS / "scanned-invoice.pdf", tokenizer=RegexTokenizer()),
        analyze(tmp_path, tokenizer=RegexTokenizer()),
    ]
    used = set()
    for report in reports:
        for rec in report.recommendations:
            assert set(rec.reason_i18n) == set(LANGUAGES)
            assert all(text and "{" not in text for text in rec.reason_i18n.values())
            assert rec.reason_i18n["en"] != rec.reason_i18n["es"]
            used |= {part.id for part in rec.reason_parts}
    assert used <= set(MESSAGES["en"])


def test_localize_switches_reason_text():
    report = localize(analyze(CORPUS / "product-catalog.csv", tokenizer=RegexTokenizer()), "es")
    parser = next(r for r in report.recommendations if r.key == "parser.csv")
    assert parser.reason.startswith("40 filas de datos")
    assert parser.reason_parts[0].id == "parser.tabular"
    assert parser.reason_parts[0].params == {"rows": 40}


def test_formatter_plurals_and_numbers():
    assert Formatter("en").format("{n} {n:file|files}", n=1) == "1 file"
    assert Formatter("es").format("{n} {n:fichero|ficheros}", n=3) == "3 ficheros"
    assert Formatter("en").format("{x}", x=12345.5) == "12,345.5"
    assert Formatter("es").format("{x}", x=12345.5) == "12.345,5"
    assert Formatter("es").format("{x}", x=1024) == "1024"
    assert Formatter("es").format("{b:bytes}", b=126_772) == "123,8 KiB"
    assert (
        Formatter("en").format("{o}", o=[["fixed", 191.0], ["recursive", 25.0]])
        == "fixed 191.0, recursive 25.0"
    )


def test_unknown_message_is_an_error():
    with pytest.raises(KeyError):
        render_message("does.not.exist", {}, "en")
