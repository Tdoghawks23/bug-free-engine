"""Tests for the DOCX extractor (src/remediate/extractors/docx.py)."""

from __future__ import annotations

import pytest

from remediate.extractors.docx import DocxExtractionError, extract_docx
from remediate.ir import Heading, Image, ListBlock, Paragraph, Table


def test_extract_ir_shape(fixture_docx):
    doc = extract_docx(fixture_docx)

    assert doc.source_format == "docx"
    assert doc.title == "Fixture Document"

    headings = [b for b in doc.blocks if isinstance(b, Heading)]
    assert [h.level for h in headings] == [1, 3]
    assert headings[0].text == "Fixture Document"
    assert headings[1].text == "Deeply Nested Section"

    lists = [b for b in doc.blocks if isinstance(b, ListBlock)]
    assert len(lists) == 1
    assert lists[0].items[0].runs[0].text == "Top-level item"
    assert lists[0].items[0].sub_lists[0].items[0].runs[0].text == "Nested item"

    tables = [b for b in doc.blocks if isinstance(b, Table)]
    assert len(tables) == 1
    assert tables[0].header_row is True
    assert tables[0].rows[0].cells[0].header is True
    assert tables[0].rows[0].cells[0].text == "Region"
    assert tables[0].rows[1].cells[0].text == "North"

    images = [b for b in doc.blocks if isinstance(b, Image)]
    assert len(images) == 1
    assert images[0].mime_type == "image/png"
    assert images[0].data


def test_rich_run_bold_and_link(fixture_docx):
    doc = extract_docx(fixture_docx)
    paragraphs = [b for b in doc.blocks if isinstance(b, Paragraph)]

    intro = next(p for p in paragraphs if "intro text" in p.text)
    bold_runs = [r for r in intro.runs if r.bold]
    assert bold_runs and bold_runs[0].text == "bold word"

    link_para = next(p for p in paragraphs if any(r.link for r in p.runs))
    link_run = next(r for r in link_para.runs if r.link)
    assert link_run.link.text == "click here"
    assert link_run.link.href == "https://example.org/details"


def test_missing_alt_flagged(fixture_docx):
    doc = extract_docx(fixture_docx)
    images = [b for b in doc.blocks if isinstance(b, Image)]
    image = images[0]
    assert image.needs_review is True
    codes = {f.code for f in image.flags}
    assert "MISSING_ALT" in codes


def test_language_detected_from_content_when_metadata_missing(fixture_docx):
    # fixture_docx has plenty of real English prose and no dc:language
    # metadata -- content-based detection should find it confidently
    # rather than silently guessing "en".
    doc = extract_docx(fixture_docx)
    assert doc.lang == "en"
    codes = {f.code for f in doc.flags}
    assert "LANG_DETECTED" in codes
    assert "LANG_ASSUMED" not in codes


def test_language_detected_from_french_content(french_text_docx):
    doc = extract_docx(french_text_docx)
    assert doc.lang == "fr"
    flag = next(f for f in doc.flags if f.code == "LANG_DETECTED")
    assert flag.wcag_sc == "3.1.1"
    assert "fr" in flag.message


def test_language_assumed_when_text_too_short_to_detect(near_empty_docx):
    doc = extract_docx(near_empty_docx)
    assert doc.lang == "en"
    codes = {f.code for f in doc.flags}
    assert "LANG_ASSUMED" in codes
    assert "LANG_DETECTED" not in codes


def test_language_used_when_present(fixture_docx_with_lang):
    doc = extract_docx(fixture_docx_with_lang)
    assert doc.lang == "fr-FR"
    codes = {f.code for f in doc.flags}
    assert "LANG_ASSUMED" not in codes
    assert "LANG_DETECTED" not in codes


def test_title_falls_back_to_filename_when_no_metadata_or_heading(minimal_docx):
    doc = extract_docx(minimal_docx)
    assert doc.title == "minimal"
    codes = {f.code for f in doc.flags}
    assert "TITLE_FROM_FILENAME" in codes


def test_header_row_detected_from_repeat_header_property(fixture_docx):
    doc = extract_docx(fixture_docx)
    tables = [b for b in doc.blocks if isinstance(b, Table)]
    assert tables[0].header_row is True
    assert not any(f.code == "NO_HEADER_ROW_DETECTED" for f in tables[0].flags)


def test_image_wrapped_in_hyperlink_is_not_dropped(linked_image_docx):
    doc = extract_docx(linked_image_docx)
    images = [b for b in doc.blocks if isinstance(b, Image)]
    assert len(images) == 1
    image = images[0]
    assert image.data
    assert image.link is not None
    assert image.link.href == "https://example.org/home"


def test_filename_like_alt_is_treated_as_missing(filename_alt_docx):
    doc = extract_docx(filename_alt_docx)
    images = [b for b in doc.blocks if isinstance(b, Image)]
    assert len(images) == 1
    image = images[0]
    assert image.alt == "Picture1.jpg"  # raw value still captured...
    assert image.needs_review is True  # ...but flagged as not meaningful
    assert any(f.code == "MISSING_ALT" for f in image.flags)


def test_merged_table_cells_flagged_and_spans_preserved(merged_table_docx):
    doc = extract_docx(merged_table_docx)
    table = next(b for b in doc.blocks if isinstance(b, Table))
    assert any(f.code == "COMPLEX_TABLE_STRUCTURE" for f in table.flags)

    header_row = table.rows[0]
    assert header_row.cells[0].colspan == 2  # merged header cell
    body_col_widths = [table.rows[1].cells[1].rowspan]
    assert body_col_widths == [2]  # merged data cell spans two rows


def test_encrypted_or_corrupt_file_is_rejected(tmp_path):
    bad_file = tmp_path / "not_really_a_docx.docx"
    bad_file.write_bytes(b"this is not a zip or an OOXML package")
    with pytest.raises(DocxExtractionError):
        extract_docx(bad_file)
