"""Language detection and identifier density, both offline and deterministic."""

from __future__ import annotations

import re

from ragcompass.models import Identifiers

_STOPWORDS = {
    "en": "the and of to in is that for it with as was on are be by this not or from at which an have",
    "es": "de la que el en y los del se las por un para con no una su al es lo como más pero sus",
    "fr": "de la le et les des en un du une que est pour qui dans par sur pas au avec ce plus",
    "de": "der die und in den von zu das mit sich des auf für ist im dem nicht ein eine als auch",
    "pt": "de que o a do da em um para é com não uma os no se na por mais as dos como",
    "it": "di che il la e in per un del non una sono le della si con da al gli dei",
}
STOPWORDS = {lang: frozenset(words.split()) for lang, words in _STOPWORDS.items()}
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
MIN_WORDS = 20

MONTHS = (
    "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|"
    "july|august|september|october|november|december|ene|abr|ago|dic|enero|febrero|marzo|abril|"
    "mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre"
)
DATE = re.compile(
    r"\b(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}"
    rf"|\d{{1,2}}\s+(?:de\s+)?(?:{MONTHS})\.?(?:\s+(?:de\s+)?\d{{4}})?"
    rf"|(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}})\b",
    re.IGNORECASE,
)
# A code mixes letters and digits, is at least four characters long and may use - _ / . inside.
CODE = re.compile(r"(?<![\w-])(?=[\w./-]*\d)(?=[\w./-]*[A-Za-z])[A-Za-z0-9](?:[\w./-]*[A-Za-z0-9])?(?![\w-])")
NUMBER = re.compile(r"(?<![\w.,])[-+]?\d+(?:[.,]\d+)*%?(?![\w])")


def detect_language(text: str) -> str | None:
    words = [w.lower() for w in WORD.findall(text)]
    if len(words) < MIN_WORDS:
        return None
    scores = {lang: 0 for lang in STOPWORDS}
    for word in words:
        for lang, stop in STOPWORDS.items():
            if word in stop:
                scores[lang] += 1
    lang, best = max(scores.items(), key=lambda kv: (kv[1], kv[0] == "en"))
    if best / len(words) < 0.05:
        return None
    return lang


def count_identifiers(text: str, tokens: int) -> Identifiers:
    dates = DATE.findall(text)
    remaining = DATE.sub(" ", text)
    codes = [m.group(0) for m in CODE.finditer(remaining) if len(m.group(0)) >= 4]
    remaining = CODE.sub(" ", remaining)
    numbers = NUMBER.findall(remaining)
    total = len(dates) + len(codes) + len(numbers)
    scale = 1000 / tokens if tokens else 0.0
    return Identifiers(
        codes=len(codes),
        dates=len(dates),
        numbers=len(numbers),
        per_1k_tokens=round(total * scale, 1),
        codes_per_1k_tokens=round(len(codes) * scale, 1),
    )
