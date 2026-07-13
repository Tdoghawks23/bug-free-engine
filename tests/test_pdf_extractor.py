from __future__ import annotations

import pytest

from pdf_fixtures import (
    build_encrypted_pdf,
    build_heading_structure_pdf,
    build_hyphenation_pdf,
    build_image_pdf,
    build_link_pdf,
    build_list_pdf,
    build_low_confidence_heading_pdf,
    build_multi_column_pdf,
    build_pull_quote_pdf,
    build_repeated_logo_pdf,
    build_scanned_pdf,
    build_table_pdf,
    build_table_with_tight_caption_pdf,
    build_two_column_pdf,
)
from remediate.extractors.pdf import PdfExtractionError, extract_pdf
from remediate.ir import Heading, Image, ListBlock, Paragraph, Table


def test_heading_sizes_inferred_from_font_clustering(tmp_path):
    doc = extract_pdf(build_heading_structure_pdf(tmp_path / "h.pdf"))

    headings = [b for b in doc.blocks if isinstance(b, Heading)]
    assert [h.text for h in headings] == ["Document Title", "Section One", "Section Two"]
    # The title (biggest font) should end up at a numerically lower
    # (more significant) level than the subsections.
    assert headings[0].level < headings[1].level == headings[2].level

    paragraphs = [b for b in doc.blocks if isinstance(b, Paragraph)]
    assert any("ordinary prose" in p.text for p in paragraphs)

    codes = {f.code for f in doc.all_flags()}
    assert "HEADINGS_INFERRED" in codes


def test_low_confidence_heading_gets_individual_flag(tmp_path):
    # R19: a short, only-slightly-larger-font odd line among ordinary
    # body paragraphs -- pull-quote-style -- should score low
    # per-heading confidence and get its own needs-human-review flag
    # naming it, distinct from the blanket HEADINGS_INFERRED summary.
    doc = extract_pdf(build_low_confidence_heading_pdf(tmp_path / "lowconf.pdf"))
    headings = [b for b in doc.blocks if isinstance(b, Heading)]
    odd = next(h for h in headings if h.text == "Odd note.")
    codes = {f.code for f in odd.flags}
    assert "HEADING_LOW_CONFIDENCE" in codes
    flag = next(f for f in odd.flags if f.code == "HEADING_LOW_CONFIDENCE")
    assert "Odd note." in flag.message


def test_two_column_reading_order(tmp_path):
    doc = extract_pdf(build_two_column_pdf(tmp_path / "2col.pdf"))
    paragraphs = [b for b in doc.blocks if isinstance(b, Paragraph)]
    texts = [p.text for p in paragraphs]

    # Left column top-to-bottom, then right column top-to-bottom -- not
    # interleaved by raw y-position (which would alternate left/right).
    assert texts == [
        "Left column line one of prose.",
        "Left column line two of prose.",
        "Left column line three of prose.",
        "Right column line one of prose.",
        "Right column line two of prose.",
        "Right column line three of prose.",
    ]
    codes = {f.code for f in doc.all_flags()}
    assert "READING_ORDER_UNCERTAIN" not in codes


def test_pull_quote_stays_in_visual_order_not_moved_to_document_end(tmp_path):
    # QA blocker-1 regression: a centered, larger-font pull-quote
    # indented away from the body creates a bimodal 2-cluster x-split,
    # but it isn't a genuine page-wide two-column layout -- it must stay
    # in its actual y-order position in the middle of the flow, not get
    # treated as "column 2" and moved after every body paragraph.
    doc = extract_pdf(build_pull_quote_pdf(tmp_path / "pullquote.pdf"))
    texts = [b.text for b in doc.blocks if isinstance(b, (Paragraph, Heading))]

    assert texts == [
        "Body paragraph number 1 of ordinary prose content here.",
        "Body paragraph number 2 of ordinary prose content here.",
        "Body paragraph number 3 of ordinary prose content here.",
        "Body paragraph number 4 of ordinary prose content here.",
        "This is a centered pull-quote",
        "spanning two indented lines.",
        "Body paragraph number 5 of ordinary prose content here.",
        "Body paragraph number 6 of ordinary prose content here.",
        "Body paragraph number 7 of ordinary prose content here.",
        "Body paragraph number 8 of ordinary prose content here.",
    ]

    # The x-distribution really was bimodal/ambiguous -- flagged for
    # human review rather than silently reordered.
    codes = {f.code for f in doc.all_flags()}
    assert "READING_ORDER_UNCERTAIN" in codes


def test_genuine_two_column_layout_still_detected_after_pull_quote_fix(tmp_path):
    # (b) from the blocker-1 fix: a real two-column page (both clusters
    # spanning the full vertical extent, each with a real item share)
    # must still be detected and ordered as two columns.
    doc = extract_pdf(build_two_column_pdf(tmp_path / "2col.pdf"))
    paragraphs = [b for b in doc.blocks if isinstance(b, Paragraph)]
    texts = [p.text for p in paragraphs]
    assert texts == [
        "Left column line one of prose.",
        "Left column line two of prose.",
        "Left column line three of prose.",
        "Right column line one of prose.",
        "Right column line two of prose.",
        "Right column line three of prose.",
    ]
    codes = {f.code for f in doc.all_flags()}
    assert "READING_ORDER_UNCERTAIN" not in codes


def test_multi_column_layout_flagged_uncertain_not_guessed(tmp_path):
    doc = extract_pdf(build_multi_column_pdf(tmp_path / "3col.pdf"))
    codes = {f.code for f in doc.all_flags()}
    assert "READING_ORDER_UNCERTAIN" in codes
    # Still emits every line of text -- just in y-order, not invented.
    paragraphs = [b for b in doc.blocks if isinstance(b, Paragraph)]
    assert len(paragraphs) == 9


def test_hyphenated_line_wrap_joined(tmp_path):
    doc = extract_pdf(build_hyphenation_pdf(tmp_path / "hy.pdf"))
    paragraphs = [b for b in doc.blocks if isinstance(b, Paragraph)]
    assert any("hyphenated word wrap right here in the middle." in p.text for p in paragraphs)
    assert not any("hy- phenated" in p.text for p in paragraphs)


def test_bullet_list_detected(tmp_path):
    doc = extract_pdf(build_list_pdf(tmp_path / "list.pdf"))
    lists = [b for b in doc.blocks if isinstance(b, ListBlock)]
    assert len(lists) == 1
    items = ["".join(r.text for r in item.runs) for item in lists[0].items]
    assert items == [
        "First bullet item in a list",
        "Second bullet item in a list",
        "Third bullet item in a list",
    ]
    assert not lists[0].ordered


def test_link_associated_with_overlapping_text_run(tmp_path):
    doc = extract_pdf(build_link_pdf(tmp_path / "link.pdf"))
    paragraphs = [b for b in doc.blocks if isinstance(b, Paragraph)]
    linked = [r for p in paragraphs for r in p.runs if r.link is not None]
    assert len(linked) == 1
    assert linked[0].link.href == "https://example.org/details"

    codes = [f.code for f in doc.all_flags()]
    assert codes.count("LINK_UNASSOCIATED") == 1  # only the orphaned link


def test_table_extracted_via_find_tables(tmp_path):
    doc = extract_pdf(build_table_pdf(tmp_path / "table.pdf"))
    tables = [b for b in doc.blocks if isinstance(b, Table)]
    assert len(tables) == 1
    table = tables[0]
    assert [c.text for c in table.rows[0].cells] == ["Region", "Count"]
    assert all(c.header for c in table.rows[0].cells)
    assert table.rows[1].cells[0].text == "North"
    assert not table.rows[1].cells[0].header

    codes = {f.code for f in table.flags}
    assert "NO_HEADER_ROW_DETECTED" in codes

    # Table text isn't duplicated into a separate paragraph.
    paragraphs = [b for b in doc.blocks if isinstance(b, Paragraph)]
    assert not any("Region" in p.text for p in paragraphs)


def test_table_with_tight_caption_preserves_caption_and_flags_uncertain(tmp_path):
    # QA blocker-2 regression: a caption sitting a couple points below
    # the table border must not silently disappear from the output --
    # either the cells stay clean and the caption survives as a
    # paragraph, or (as here, since find_tables()'s own extraction
    # already absorbed/mangled some of it) the caption still survives
    # as a paragraph *and* the table is flagged for human review rather
    # than shipping corrupted cells silently.
    doc = extract_pdf(build_table_with_tight_caption_pdf(tmp_path / "captioned_table.pdf"))

    tables = [b for b in doc.blocks if isinstance(b, Table)]
    assert len(tables) == 1
    table = tables[0]

    paragraphs = [b for b in doc.blocks if isinstance(b, Paragraph)]
    assert any("Regional counts summary caption text." in p.text for p in paragraphs), (
        "caption text must not disappear from the document -- it should "
        "remain in the normal text flow, not be silently swallowed by "
        "the table's bbox-overlap exclusion"
    )

    codes = {f.code for f in table.flags}
    assert "TABLE_EXTRACTION_UNCERTAIN" in codes


def test_clean_table_not_flagged_extraction_uncertain(tmp_path):
    # No caption nearby -- the reconciliation check must not produce
    # false positives on an ordinary clean table.
    doc = extract_pdf(build_table_pdf(tmp_path / "table.pdf"))
    tables = [b for b in doc.blocks if isinstance(b, Table)]
    codes = {f.code for f in tables[0].flags}
    assert "TABLE_EXTRACTION_UNCERTAIN" not in codes


def test_image_decorative_heuristics(tmp_path):
    doc = extract_pdf(build_image_pdf(tmp_path / "img.pdf"))
    images = [b for b in doc.blocks if isinstance(b, Image)]
    assert len(images) == 2

    tiny, large = images
    assert tiny.decorative is True
    assert any(f.code == "DECORATIVE_ASSUMED" for f in tiny.flags)

    assert large.decorative is None
    assert large.needs_review is True
    assert any(f.code == "MISSING_ALT" for f in large.flags)
    assert large.data  # bytes were actually extracted


def test_repeated_logo_marked_decorative(tmp_path):
    doc = extract_pdf(build_repeated_logo_pdf(tmp_path / "logo.pdf", page_count=4))
    images = [b for b in doc.blocks if isinstance(b, Image)]
    assert len(images) == 4
    assert all(img.decorative is True for img in images)
    assert all(any(f.code == "DECORATIVE_ASSUMED" for f in img.flags) for img in images)
    # Bytes extracted once and reused, not re-decoded per occurrence,
    # but every occurrence still gets its own Image IR node.
    assert all(img.data == images[0].data for img in images)


def test_scanned_pdf_rejected_when_ocr_tooling_missing(tmp_path, monkeypatch):
    # Scanned PDFs are now OCR'd automatically when the tooling is
    # present (see test_ocr.py); this is the graceful-degradation case.
    monkeypatch.setattr("remediate.ocr.available", lambda: False)
    with pytest.raises(PdfExtractionError, match="OCR tooling"):
        extract_pdf(build_scanned_pdf(tmp_path / "scan.pdf"))


def test_encrypted_pdf_rejected(tmp_path):
    with pytest.raises(PdfExtractionError, match="password-protected"):
        extract_pdf(build_encrypted_pdf(tmp_path / "enc.pdf"))


def test_title_from_first_heading_when_no_metadata(tmp_path):
    doc = extract_pdf(build_heading_structure_pdf(tmp_path / "h.pdf"))
    assert doc.title == "Document Title"
    assert not any(f.code == "TITLE_FROM_FILENAME" for f in doc.flags)


def test_title_falls_back_to_filename(tmp_path):
    doc = extract_pdf(build_two_column_pdf(tmp_path / "no_heading.pdf"))
    assert doc.title == "no_heading"
    assert any(f.code == "TITLE_FROM_FILENAME" for f in doc.flags)


def test_catalog_lang_metadata_used_when_present(fixture_pdf_with_lang):
    doc = extract_pdf(fixture_pdf_with_lang)
    assert doc.lang == "fr"
    codes = {f.code for f in doc.flags}
    assert "LANG_ASSUMED" not in codes
    assert "LANG_DETECTED" not in codes
