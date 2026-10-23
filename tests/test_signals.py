from ragcompass.signals import count_identifiers, detect_language


def test_identifier_counts_by_hand():
    text = "Order RLY-4471-B on 2025-11-04 for 132.00 CHF, ticket E-415 and 3 units."
    ids = count_identifiers(text, tokens=100)
    assert ids.dates == 1  # 2025-11-04
    assert ids.codes == 2  # RLY-4471-B, E-415
    assert ids.numbers == 2  # 132.00, 3
    assert ids.per_1k_tokens == 50.0
    assert ids.codes_per_1k_tokens == 20.0


def test_spanish_and_textual_dates():
    ids = count_identifiers("Pedido del 1 de enero de 2025 y del 03/02/2025.", tokens=10)
    assert ids.dates == 2
    assert ids.numbers == 0


def test_plain_words_are_not_codes():
    assert count_identifiers("The fan blows towards the rear of the case.", tokens=10).codes == 0


def test_language_detection():
    english = "The instrument must be verified every year and the result is recorded in the log " * 2
    spanish = (
        "El instrumento debe verificarse cada año y el resultado se anota en el registro de la empresa " * 2
    )
    assert detect_language(english) == "en"
    assert detect_language(spanish) == "es"
    assert detect_language("too short to tell") is None
