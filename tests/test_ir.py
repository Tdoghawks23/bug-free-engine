"""Tests for the internal document representation (src/remediate/ir.py)."""

from __future__ import annotations

import pytest

from remediate.ir import (
    Document,
    Flag,
    Heading,
    Image,
    Link,
    ListBlock,
    ListItem,
    Paragraph,
    Table,
    TableCell,
    TableRow,
    TextRun,
)


def test_heading_level_validation():
    Heading(level=1, runs=[TextRun(text="OK")])
    with pytest.raises(ValueError):
        Heading(level=0, runs=[TextRun(text="bad")])
    with pytest.raises(ValueError):
        Heading(level=7, runs=[TextRun(text="bad")])


def test_heading_and_paragraph_text_concatenation():
    heading = Heading(level=2, runs=[TextRun(text="Intro"), TextRun(text=" Section")])
    assert heading.text == "Intro Section"

    para = Paragraph(runs=[TextRun(text="Hello, "), TextRun(text="world.")])
    assert para.text == "Hello, world."


def test_text_run_with_link():
    link = Link(text="ISO 14289-1", href="https://example.org/pdfua")
    run = TextRun(text="ISO 14289-1", link=link)
    assert run.link.href == "https://example.org/pdfua"


def test_list_block_nesting():
    inner = ListBlock(ordered=False, items=[ListItem(runs=[TextRun(text="nested item")])])
    outer_item = ListItem(runs=[TextRun(text="top item")], sub_lists=[inner])
    outer = ListBlock(ordered=True, items=[outer_item])

    assert outer.ordered is True
    assert outer.items[0].sub_lists[0].items[0].runs[0].text == "nested item"


def test_table_construction_and_cell_text():
    header_row = TableRow(cells=[TableCell(runs=[TextRun(text="Region")], header=True)])
    data_row = TableRow(cells=[TableCell(runs=[TextRun(text="North")])])
    table = Table(rows=[header_row, data_row], header_row=True, caption="Widget counts")

    assert table.caption == "Widget counts"
    assert table.rows[0].cells[0].header is True
    assert table.rows[0].cells[0].text == "Region"
    assert table.rows[1].cells[0].header is False


def test_image_defaults_to_needing_review():
    img = Image()
    assert img.needs_review is True
    assert img.alt is None
    assert img.decorative is None


def test_image_with_alt_and_data():
    img = Image(alt="A red square", decorative=False, needs_review=False,
                data=b"\x89PNG", mime_type="image/png")
    assert img.alt == "A red square"
    assert img.decorative is False
    assert img.needs_review is False
    assert img.data == b"\x89PNG"


def test_document_round_trip_and_defaults():
    doc = Document(title="Spike Doc", lang="en", source_format="pdf")
    assert doc.blocks == []
    assert doc.warnings == []

    doc.blocks.append(Heading(level=1, runs=[TextRun(text="Title")]))
    doc.blocks.append(Paragraph(runs=[TextRun(text="Body text.")]))

    assert len(doc.blocks) == 2
    assert doc.source_format == "pdf"


def test_all_flags_collects_from_nested_blocks():
    flag_on_heading = Flag(code="HEADING_SKIP", wcag_sc="1.3.1", message="h1 -> h3 skip")
    flag_on_image = Flag(code="MISSING_ALT", wcag_sc="1.1.1", message="no alt text",
                          location="page 3")
    flag_on_list_item = Flag(code="AMBIGUOUS_LIST", wcag_sc="1.3.1", message="maybe not a list")
    flag_on_cell = Flag(code="AMBIGUOUS_HEADER", wcag_sc="1.3.1", message="unclear if header row")

    heading = Heading(level=3, runs=[TextRun(text="Oops")], flags=[flag_on_heading])
    image = Image(flags=[flag_on_image])
    nested_list = ListBlock(
        ordered=False,
        items=[ListItem(runs=[TextRun(text="item")], flags=[flag_on_list_item])],
    )
    table = Table(
        rows=[TableRow(cells=[TableCell(runs=[TextRun(text="cell")], flags=[flag_on_cell])])]
    )

    doc = Document(
        title="Doc with flags",
        lang="en",
        blocks=[heading, image, nested_list, table],
    )

    collected = doc.all_flags()
    codes = {f.code for f in collected}
    assert codes == {"HEADING_SKIP", "MISSING_ALT", "AMBIGUOUS_LIST", "AMBIGUOUS_HEADER"}
    assert len(collected) == 4
