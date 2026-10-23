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


TECHNICAL_MANUAL = (
    "Connect the 220V supply at 50Hz and fix the bracket with M8x20 bolts on a 10mm plate. "
    "Use a 2.5mm hex key, 3x20 fuses and 1kV leads. Logs are written as utf-8 and kept in "
    "ISO-8859-1 for the legacy viewer. During covid-19 the lab on the 21st floor moved to the 3rd. "
    "Order fan HX-FAN-118, relay RLY-4471-B and battery CR2032 for unit HX20481736."
)


def test_units_and_names_are_not_codes():
    ids = count_identifiers(TECHNICAL_MANUAL, tokens=100)
    # only the four part numbers are identifiers worth an exact-match index
    assert ids.codes == 4


def test_catalan_is_not_spanish():
    catalan = (
        "La política de devolucions explica com es tramiten les reparacions dels instruments i "
        "quins terminis s'apliquen a cada cas. El client pot retornar el producte amb tots els "
        "accessoris i amb el certificat de calibratge per a la seva revisió."
    )
    spanish = (
        "La política de devoluciones explica cómo se tramitan las reparaciones de los instrumentos y "
        "qué plazos se aplican a cada caso. El cliente puede devolver el producto con todos los "
        "accesorios y con el certificado de calibración para su revisión."
    )
    assert detect_language(catalan) == "ca"
    assert detect_language(spanish) == "es"
