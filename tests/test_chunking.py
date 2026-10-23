from ragcompass import chunking
from ragcompass.models import Block, BlockType

P, H, T = BlockType.PARAGRAPH, BlockType.HEADING, BlockType.TABLE


def texts(layout, chunks):
    return [layout.text[c.start : c.end] for c in chunks]


def test_fixed_windows_with_overlap(layout):
    doc = layout((P, "a b c d e f g h i j"))  # 10 tokens
    chunks = chunking.fixed(doc, size=4, overlap=1)  # windows start at 0, 3, 6
    assert [t.strip() for t in texts(doc, chunks)] == ["a b c d", "d e f g", "g h i j"]


def test_fixed_without_overlap_keeps_short_tail(layout):
    doc = layout((P, "a b c d e f g h i j"))
    assert len(chunking.fixed(doc, size=4)) == 3  # 4 + 4 + 2 tokens


def test_recursive_packs_paragraphs(layout):
    # 4, 3 and 5 tokens
    doc = layout((P, "Alpha beta gamma."), (P, "Delta epsilon."), (P, "Zeta eta theta iota."))
    chunks = chunking.recursive(doc, size=8)
    assert texts(doc, chunks) == ["Alpha beta gamma.\n\nDelta epsilon.\n\n", "Zeta eta theta iota."]


def test_recursive_overlap_carries_previous_piece(layout):
    doc = layout((P, "Alpha beta gamma."), (P, "Delta epsilon."), (P, "Zeta eta theta iota."))
    chunks = chunking.recursive(doc, size=8, overlap=3)
    assert texts(doc, chunks)[1] == "Delta epsilon.\n\nZeta eta theta iota."


def test_heading_packs_small_sections(layout):
    # sections: "Intro" + 4 tokens = 5, "Part" + 5 tokens = 6
    doc = layout((H, "Intro"), (P, "One two three."), (H, "Part"), (P, "Four five six seven."))
    assert len(chunking.heading(doc, size=20)) == 1
    assert len(chunking.heading(doc, size=6)) == 2


def test_heading_split_inside_section_can_orphan_heading(layout):
    doc = layout((H, "Intro"), (P, "One two three."), (H, "Part"), (P, "Four five six seven."))
    chunks = chunking.heading(doc, size=4)
    first = chunks[0]
    assert doc.text[first.start : first.end].strip() == "Intro"
    assert doc.ends_with_heading(first.start, first.end)


def table(rows):
    text = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return Block(type=T, text=text, rows=rows)


def test_row_strategy_repeats_header(layout):
    # every line "| x | y |" is 5 tokens
    doc = layout(table([["a", "b"], ["1", "x"], ["2", "y"], ["3", "z"], ["4", "w"]]))
    chunks = chunking.row(doc, size=15)
    assert len(chunks) == 2
    assert [c.extra_tokens for c in chunks] == [0, 5]  # second group gets the header back
    assert [doc.tokens.count(c.start, c.end) + c.extra_tokens for c in chunks] == [15, 15]
    assert not any(doc.headerless(c.start, c.end, c.extra_tokens) for c in chunks)


def test_recursive_on_table_loses_header(layout):
    doc = layout(table([["a", "b"], ["1", "x"], ["2", "y"], ["3", "z"], ["4", "w"]]))
    chunks = chunking.recursive(doc, size=15)
    assert len(chunks) == 2
    assert doc.headerless(chunks[1].start, chunks[1].end)


def test_row_keeps_sheet_name_with_table(layout):
    doc = layout((H, "Zurich"), table([["a", "b"], ["1", "x"]]))
    chunks = chunking.row(doc, size=40)
    assert len(chunks) == 1
    assert doc.text[chunks[0].start : chunks[0].end].startswith("Zurich")


def test_page_strategy_groups_blocks_by_page(layout):
    doc = layout(
        Block(type=P, text="Page one text.", page=1),
        Block(type=P, text="Still page one.", page=1),
        Block(type=P, text="Page two.", page=2),
    )
    assert len(chunking.page(doc, size=100)) == 2


def test_boundary_classification(layout):
    doc = layout((P, "Hello world. Bye now."), table([["a", "b"], ["1", "x"]]))
    assert doc.boundary(len("Hello world. ")) == "clean"
    assert doc.boundary(len("Hello wo")) == "sentence"
    table_start = doc.spans[1].start
    assert doc.boundary(table_start + len("| a | b |\n")) == "clean"
    assert doc.boundary(table_start + 3) == "table_row"


CODE_SOURCE = '''import math


@cache
def area(radius):
    """Area of a circle."""
    value = math.pi * radius ** 2
    return round(value, 2)


def perimeter(radius):
    """Perimeter of a circle."""
    value = 2 * math.pi * radius
    return round(value, 2)


class Circle:
    def __init__(self, radius):
        self.radius = radius

    def area(self):
        return area(self.radius)
'''


def code_layout(layout):
    return layout((BlockType.CODE, CODE_SOURCE))


def test_code_splits_before_definitions(layout):
    doc = code_layout(layout)
    chunks = chunking.recursive(doc, size=40, separators=chunking.CODE_SEPARATORS)  # a function is ~36 tokens
    starts = [doc.text[c.start : c.end].lstrip().split("\n", 1)[0] for c in chunks]
    assert starts == ["import math", "def perimeter(radius):", "class Circle:"]
    assert any("@cache\ndef area" in t for t in texts(doc, chunks))  # decorator kept with its function
    assert all(t.strip() not in ("def", "class") for t in texts(doc, chunks))
    assert all(doc.boundary(c.start) == "clean" for c in chunks)


def test_code_boundary_classification(layout):
    doc = code_layout(layout)
    text = doc.text
    assert doc.boundary(text.index("def perimeter")) == "clean"
    assert doc.boundary(text.index("def area")) == "code"  # between decorator and def
    assert doc.boundary(text.index("    value = 2")) == "code"  # inside a function body
    assert doc.boundary(text.index("math.pi * radius ** 2")) == "code"  # mid-line
    assert doc.boundary(text.index("    def area(self)")) == "clean"  # between methods


def test_fixed_windows_cut_code(layout):
    from ragcompass.models import DocKind
    from ragcompass.simulate import Doc, measure

    doc = Doc(kind=DocKind.CODE, layout=code_layout(layout))
    fixed = measure("code", "fixed", 40, 0, [doc], lambda d: chunking.fixed(d.layout, 40))
    split = measure(
        "code",
        "recursive",
        40,
        0,
        [doc],
        lambda d: chunking.recursive(d.layout, 40, separators=chunking.CODE_SEPARATORS),
    )
    assert fixed.code_cut_pct > 50
    assert split.code_cut_pct == 0


def test_histogram_bins():
    from ragcompass.simulate import histogram

    result = histogram([10, 120, 250, 256, 300], 256)
    assert result.edges[0] == 0 and result.edges[-1] == 256 and len(result.edges) == 11
    assert sum(result.counts) == 5
    assert result.counts[0] == 1  # 10
    assert result.counts[-1] == 3  # 250, 256 and the oversized 300


def test_utf16_offsets():
    from ragcompass.explorer import utf16_offsets

    to16 = utf16_offsets("a\U0001f600b")  # an astral character takes two UTF-16 units
    assert [to16(i) for i in range(4)] == [0, 1, 3, 4]
