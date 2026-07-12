"""Tests for the accessible HTML generator (src/remediate/html_gen.py)."""

from __future__ import annotations

import html5lib
import lxml.html

from remediate.extractors.docx import extract_docx
from remediate.html_gen import MISSING_ALT_PLACEHOLDER, generate_html
from remediate.ir import Document, Heading, Image, Link, Paragraph, TextRun


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


def test_image_wrapped_in_hyperlink_renders_as_linked_img(linked_image_docx):
    doc = extract_docx(linked_image_docx)
    result = generate_html(doc)
    tree = _parse(result.html)

    imgs = tree.xpath("//img")
    assert len(imgs) == 1
    # the image's containing <a> is the one carrying the link's href --
    # it must not have been silently dropped.
    anchor = imgs[0].getparent()
    assert anchor.tag == "a"
    assert anchor.get("href") == "https://example.org/home"


def test_filename_like_alt_never_ships_verbatim(filename_alt_docx):
    doc = extract_docx(filename_alt_docx)
    result = generate_html(doc)
    tree = _parse(result.html)

    imgs = tree.xpath("//img")
    assert len(imgs) == 1
    assert imgs[0].get("alt") == MISSING_ALT_PLACEHOLDER
    assert "Picture1.jpg" not in result.html


def test_needs_review_alt_substitution_is_single_source_of_truth():
    # Any image with needs_review=True gets the placeholder, regardless
    # of what junk happens to be sitting in `alt` -- html_gen must not
    # re-derive its own "is this filename-like" heuristic.
    from remediate.html_gen import _render_image

    image = Image(alt="whatever-junk-value.png", needs_review=True)
    rendered = _render_image(image, [])
    assert MISSING_ALT_PLACEHOLDER in rendered
    assert "whatever-junk-value.png" not in rendered


def test_merged_table_cells_flagged_and_spans_rendered_consistently(merged_table_docx):
    doc = extract_docx(merged_table_docx)
    codes = {f.code for f in doc.all_flags()}
    assert "COMPLEX_TABLE_STRUCTURE" in codes

    result = generate_html(doc)
    tree = _parse(result.html)
    table = tree.xpath("//table")[0]

    header_cells = table.xpath(".//thead//tr[1]/th")
    header_total = sum(int(th.get("colspan", "1")) for th in header_cells)

    body_rows = table.xpath(".//tbody/tr")
    first_body_total = sum(
        int(cell.get("colspan", "1")) for cell in body_rows[0].xpath("./td|./th")
    )
    # The header row's column count (accounting for colspan) must match
    # the first body row's -- otherwise the grid is misaligned.
    assert header_total == first_body_total

    assert any(th.get("colspan") == "2" for th in header_cells)
    rowspans = [
        cell.get("rowspan")
        for row in body_rows
        for cell in row.xpath("./td|./th")
        if cell.get("rowspan")
    ]
    assert "2" in rowspans


def test_image_with_data_but_unknown_mime_type_is_flagged_not_silently_blank():
    image = Image(data=b"\x00\x01", mime_type=None, alt="A description", needs_review=False)
    from remediate.html_gen import _render_image

    rendered = _render_image(image, [])
    assert 'src=""' in rendered
    assert any(f.code == "IMAGE_UNKNOWN_MIME_TYPE" for f in image.flags)


def test_generated_html_is_valid_and_has_no_duplicate_ids(fixture_docx):
    doc = extract_docx(fixture_docx)
    result = generate_html(doc)

    # Strict parse (raises on parse errors when strict=True) -- R16.
    parser = html5lib.HTMLParser(strict=True)
    parser.parse(result.html)

    tree = _parse(result.html)
    ids = tree.xpath("//@id")
    assert len(ids) == len(set(ids))
