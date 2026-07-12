"""Tests for the accessible HTML generator (src/remediate/html_gen.py)."""

from __future__ import annotations

import lxml.html

from remediate.extractors.docx import extract_docx
from remediate.html_gen import MISSING_ALT_PLACEHOLDER, generate_html
from remediate.ir import Document, Heading, Paragraph, TextRun


def _parse(html_str: str):
    return lxml.html.fromstring(html_str)


def test_heading_skip_is_repaired(fixture_docx):
    doc = extract_docx(fixture_docx)
    result = generate_html(doc)

    tree = _parse(result.html)
    headings = tree.xpath("//h1 | //h2 | //h3 | //h4 | //h5 | //h6")
    levels = [int(h.tag[1]) for h in headings]
    # source was H1 -> H3 (a skip); must come out as H1 -> H2 with no skip
    assert levels == [1, 2]
    assert any(a.code == "HEADING_SKIP_REPAIRED" for a in result.autofixes)


def test_exactly_one_h1_when_none_present():
    doc = Document(title="No Headings Doc", lang="en")
    doc.blocks.append(Paragraph(runs=[TextRun(text="Body text only.")]))

    result = generate_html(doc)
    tree = _parse(result.html)
    h1s = tree.xpath("//h1")
    assert len(h1s) == 1
    assert h1s[0].text_content() == "No Headings Doc"
    assert any(a.code == "TITLE_PROMOTED_TO_H1" for a in result.autofixes)


def test_exactly_one_h1_when_multiple_present():
    doc = Document(title="Doc", lang="en")
    doc.blocks.append(Heading(level=1, runs=[TextRun(text="First")]))
    doc.blocks.append(Paragraph(runs=[TextRun(text="middle")]))
    doc.blocks.append(Heading(level=1, runs=[TextRun(text="Second")]))

    result = generate_html(doc)
    tree = _parse(result.html)
    h1s = tree.xpath("//h1")
    assert len(h1s) == 1
    assert h1s[0].text_content() == "First"
    h2s = tree.xpath("//h2")
    assert any(h.text_content() == "Second" for h in h2s)
    assert any(a.code == "MULTIPLE_H1_DEMOTED" for a in result.autofixes)


def test_missing_alt_gets_placeholder_and_flag(fixture_docx):
    doc = extract_docx(fixture_docx)
    result = generate_html(doc)

    tree = _parse(result.html)
    imgs = tree.xpath("//img")
    assert len(imgs) == 1
    assert imgs[0].get("alt") == MISSING_ALT_PLACEHOLDER

    from remediate.ir import Image

    image_block = next(b for b in doc.blocks if isinstance(b, Image))
    assert any(f.code == "MISSING_ALT" for f in image_block.flags)


def test_generic_link_text_is_flagged_not_rewritten(fixture_docx):
    doc = extract_docx(fixture_docx)
    result = generate_html(doc)

    tree = _parse(result.html)
    links = tree.xpath("//a")
    click_here = next(a for a in links if a.text_content() == "click here")
    assert click_here.text_content() == "click here"  # not rewritten

    flags = doc.all_flags()
    assert any(f.code == "GENERIC_LINK_TEXT" for f in flags)


def test_table_header_row_gets_th_scope_col(fixture_docx):
    doc = extract_docx(fixture_docx)
    result = generate_html(doc)
    tree = _parse(result.html)
    ths = tree.xpath("//thead//th")
    assert len(ths) == 2
    assert all(th.get("scope") == "col" for th in ths)


def test_table_without_detected_header_gets_autofix():
    doc = Document(title="Doc", lang="en")
    from remediate.ir import Table, TableCell, TableRow

    table = Table(
        rows=[
            TableRow(cells=[TableCell(runs=[TextRun(text="A")])]),
            TableRow(cells=[TableCell(runs=[TextRun(text="1")])]),
        ],
        header_row=False,
    )
    doc.blocks.append(table)

    result = generate_html(doc)
    tree = _parse(result.html)
    assert len(tree.xpath("//thead//th")) == 1
    assert any(a.code == "HEADER_ROW_AUTO_ADDED" for a in result.autofixes)


def test_html_lang_and_title_set_from_document():
    doc = Document(title="My Title", lang="es")
    doc.blocks.append(Heading(level=1, runs=[TextRun(text="H")]))

    result = generate_html(doc)
    tree = _parse(result.html)
    assert tree.get("lang") == "es"
    assert tree.xpath("//title")[0].text_content() == "My Title"


def test_stylesheet_body_contrast_meets_aa():
    from remediate.html_gen import DEFAULT_CSS

    # Extract the colors this test cares about directly rather than
    # re-parsing CSS -- asserts against the actual literal values used.
    assert "#1a1a1a" in DEFAULT_CSS  # body text
    assert "#ffffff" in DEFAULT_CSS  # background

    def luminance(hexcolor: str) -> float:
        hexcolor = hexcolor.lstrip("#")
        r, g, b = (int(hexcolor[i : i + 2], 16) / 255 for i in (0, 2, 4))

        def lin(c: float) -> float:
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = lin(r), lin(g), lin(b)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def contrast(c1: str, c2: str) -> float:
        l1, l2 = luminance(c1), luminance(c2)
        l1, l2 = max(l1, l2), min(l1, l2)
        return (l1 + 0.05) / (l2 + 0.05)

    assert contrast("#1a1a1a", "#ffffff") >= 4.5
    assert contrast("#0b4d8f", "#ffffff") >= 4.5  # link color


def test_links_are_underlined_not_color_only():
    from remediate.html_gen import DEFAULT_CSS

    assert "text-decoration: underline" in DEFAULT_CSS
