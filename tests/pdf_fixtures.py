"""Helpers for building small .pdf fixtures programmatically, for the
PDF extractor/pipeline test suite.

Two build strategies are used, deliberately:
  - Raw PyMuPDF (`fitz.Page.insert_text`/`insert_image`/`insert_link`)
    for cases that need precise control over font size/position (heading
    clustering, two-column layout, hyphenation, list lines, link
    placement, tiny-vs-large image sizing) -- WeasyPrint's layout engine
    makes this kind of pixel-exact placement fiddly to guarantee.
  - WeasyPrint (HTML -> PDF, mirroring spike/pdfua_spike.py) for cases
    that want a realistic, vector-bordered `<table>` PyMuPDF's
    `find_tables()` can actually detect, and for the end-to-end fixture.
"""

from __future__ import annotations

import io
from pathlib import Path

import fitz
from PIL import Image as PILImage
from weasyprint import HTML

_BODY_SIZE = 11
_H1_SIZE = 24
_H2_SIZE = 16


def _tiny_png_bytes(size=(4, 4), color=(200, 30, 30)) -> bytes:
    img = PILImage.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_heading_structure_pdf(path: str | Path) -> Path:
    """A single page with a clear H1 / H2 / body-text font-size
    hierarchy, for heading-inference tests."""
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Document Title", fontsize=_H1_SIZE, fontname="helv")
    page.insert_text((72, 120), "Section One", fontsize=_H2_SIZE, fontname="helv")
    page.insert_text((72, 150), "This is body text at the normal reading size.", fontsize=_BODY_SIZE, fontname="helv")
    page.insert_text((72, 166), "It spans a couple of lines of ordinary prose.", fontsize=_BODY_SIZE, fontname="helv")
    page.insert_text((72, 200), "Section Two", fontsize=_H2_SIZE, fontname="helv")
    page.insert_text((72, 230), "More ordinary body paragraph text goes here for good measure.", fontsize=_BODY_SIZE, fontname="helv")
    doc.save(str(path))
    doc.close()
    return path


def build_two_column_pdf(path: str | Path) -> Path:
    """A page with two clearly separated text columns (a real gutter),
    each with several lines, for two-column reading-order detection."""
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page()
    left_lines = [
        "Left column line one of prose.",
        "Left column line two of prose.",
        "Left column line three of prose.",
    ]
    right_lines = [
        "Right column line one of prose.",
        "Right column line two of prose.",
        "Right column line three of prose.",
    ]
    y = 100
    for line in left_lines:
        page.insert_text((72, y), line, fontsize=_BODY_SIZE, fontname="helv")
        y += 20
    y = 100
    for line in right_lines:
        page.insert_text((320, y), line, fontsize=_BODY_SIZE, fontname="helv")
        y += 20
    doc.save(str(path))
    doc.close()
    return path


def build_multi_column_pdf(path: str | Path) -> Path:
    """A page with three distinct horizontal text clusters -- outside
    the single/two-column heuristic's confidence, so it should trigger
    READING_ORDER_UNCERTAIN rather than guess at column order."""
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page()
    columns_x = [72, 250, 430]
    for col_x in columns_x:
        y = 100
        for i in range(3):
            page.insert_text((col_x, y), f"Column at x={col_x} line {i}.", fontsize=_BODY_SIZE, fontname="helv")
            y += 20
    doc.save(str(path))
    doc.close()
    return path


def build_pull_quote_pdf(path: str | Path) -> Path:
    """A single-column page of body text with a centered, larger-font
    pull-quote (two indented lines) in the middle of the flow -- the
    QA blocker-1 regression fixture: a naive 2-cluster x-split would
    treat the differently-indented quote as "column 2" and move it to
    the end of the document instead of leaving it in its actual visual
    (y-order) position."""
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page()
    y = 100
    for i in range(1, 5):
        page.insert_text(
            (72, y), f"Body paragraph number {i} of ordinary prose content here.", fontsize=_BODY_SIZE, fontname="helv"
        )
        y += 80
    quote_y = y
    # A large vertical gap between the two quote lines keeps them as two
    # separate PyMuPDF text blocks (rather than merging into one),
    # matching the real-world case that triggered the original bug: a
    # 2-cluster x-split where *both* clusters have >=2 blocks.
    page.insert_text((250, quote_y), "This is a centered pull-quote", fontsize=18, fontname="helv")
    page.insert_text((250, quote_y + 40), "spanning two indented lines.", fontsize=18, fontname="helv")
    y = quote_y + 80
    for i in range(5, 9):
        page.insert_text(
            (72, y), f"Body paragraph number {i} of ordinary prose content here.", fontsize=_BODY_SIZE, fontname="helv"
        )
        y += 80
    doc.save(str(path))
    doc.close()
    return path


def build_low_confidence_heading_pdf(path: str | Path) -> Path:
    """A single-column page with ordinary body paragraphs and one short,
    only-slightly-larger-font odd line in the middle -- should score low
    per-heading confidence (R19) and get its own needs-human-review
    flag rather than being silently rolled into the blanket
    HEADINGS_INFERRED summary."""
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page()
    y = 100
    page.insert_text((72, y), "Body paragraph number one of ordinary prose content here.", fontsize=_BODY_SIZE, fontname="helv")
    y += 40
    page.insert_text((72, y), "Body paragraph number two of ordinary prose content here.", fontsize=_BODY_SIZE, fontname="helv")
    y += 40
    page.insert_text((72, y), "Odd note.", fontsize=_BODY_SIZE + 1, fontname="helv")
    y += 40
    page.insert_text((72, y), "Body paragraph number three of ordinary prose content here.", fontsize=_BODY_SIZE, fontname="helv")
    y += 40
    page.insert_text((72, y), "Body paragraph number four of ordinary prose content here.", fontsize=_BODY_SIZE, fontname="helv")
    doc.save(str(path))
    doc.close()
    return path


def build_table_with_tight_caption_pdf(path: str | Path) -> Path:
    """A raw-drawn bordered table whose bbox, as detected by
    `find_tables()`, comes within a couple points of a caption line
    directly below it -- the QA blocker-2 regression fixture. Without
    the cross-check against raw text blocks, the caption gets word-torn
    across the last row's cells (find_tables() absorbs it) *and*
    disappears from the normal text flow (its own bbox overlaps the
    table bbox by >=60% of its own area)."""
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Quarterly Counts", fontsize=_H2_SIZE, fontname="helv")

    x0, y0, x1, y1 = 72, 120, 260, 200
    col_mid = (x0 + x1) / 2
    row_h = (y1 - y0) / 3
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(x0, y0, x1, y1))
    for i in range(1, 3):
        shape.draw_line((x0, y0 + i * row_h), (x1, y0 + i * row_h))
    shape.draw_line((col_mid, y0), (col_mid, y1))
    shape.finish(width=1)
    shape.commit()

    cells = [
        ("Region", x0 + 4, y0 + 14),
        ("Count", col_mid + 4, y0 + 14),
        ("North", x0 + 4, y0 + row_h + 14),
        ("12", col_mid + 4, y0 + row_h + 14),
        ("South", x0 + 4, y0 + 2 * row_h + 14),
        ("9", col_mid + 4, y0 + 2 * row_h + 14),
    ]
    for text, cx, cy in cells:
        page.insert_text((cx, cy), text, fontsize=_BODY_SIZE - 1, fontname="helv")

    # Placed just 1pt below the table's bottom border -- close enough
    # that its own bbox mostly overlaps the table's bbox.
    page.insert_text((x0, y1 + 1), "Regional counts summary caption text.", fontsize=_BODY_SIZE - 2, fontname="helv")

    doc.save(str(path))
    doc.close()
    return path


def build_hyphenation_pdf(path: str | Path) -> Path:
    """A paragraph whose PDF line-wrap splits a word with a trailing
    hyphen, for the hyphenated-line-break join test."""
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Section Heading", fontsize=_H1_SIZE, fontname="helv")
    page.insert_text((72, 120), "This paragraph contains a hy-", fontsize=_BODY_SIZE, fontname="helv")
    page.insert_text((72, 136), "phenated word wrap right here in the middle.", fontsize=_BODY_SIZE, fontname="helv")
    doc.save(str(path))
    doc.close()
    return path


def build_list_pdf(path: str | Path) -> Path:
    """A page with a bullet list rendered as literal bullet-prefixed
    lines (the common Word-PDF pattern) inside what PyMuPDF will treat
    as a single text block."""
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Grocery List", fontsize=_H1_SIZE, fontname="helv")
    y = 120
    for item in ["First bullet item in a list", "Second bullet item in a list", "Third bullet item in a list"]:
        page.insert_text((72, y), f"• {item}", fontsize=_BODY_SIZE, fontname="helv")
        y += 16
    doc.save(str(path))
    doc.close()
    return path


def build_link_pdf(path: str | Path) -> Path:
    """A page with a text run wrapped in a URI link, and a second,
    unassociated link that doesn't overlap any text (LINK_UNASSOCIATED
    regression fixture)."""
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "For details, visit our website.", fontsize=_BODY_SIZE, fontname="helv")
    # PyMuPDF puts this whole short line in a single span, so the link
    # association is span-granular here -- cover (almost) the full
    # span's bbox to guarantee the >=50% overlap match.
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 58, 215, 78), "uri": "https://example.org/details"})
    # A link placed far away from any text -- should stay unassociated.
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 400, 200, 420), "uri": "https://example.org/orphan"})
    doc.save(str(path))
    doc.close()
    return path


def build_image_pdf(path: str | Path) -> Path:
    """A page with a tiny (icon-sized) image and a large (content-sized)
    image, for the decorative-vs-real-content size heuristic."""
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Images", fontsize=_H1_SIZE, fontname="helv")
    tiny_png = _tiny_png_bytes((4, 4))
    large_png = _tiny_png_bytes((300, 300), color=(30, 90, 200))
    page.insert_image(fitz.Rect(72, 100, 82, 110), stream=tiny_png)  # 10x10pt -> tiny
    page.insert_image(fitz.Rect(72, 130, 272, 330), stream=large_png)  # 200x200pt -> real content
    doc.save(str(path))
    doc.close()
    return path


def build_repeated_logo_pdf(path: str | Path, page_count: int = 4) -> Path:
    """The same image xref placed on every page (a logo/watermark) --
    decorative-by-repetition regression fixture."""
    path = Path(path)
    doc = fitz.open()
    logo_png = _tiny_png_bytes((100, 40), color=(10, 10, 10))
    # Embed the logo once, into the first page, then reuse its xref on
    # every subsequent page via Page.insert_image(..., xref=...) so all
    # pages genuinely share one xref (mirrors how real authoring tools
    # embed a repeated header/footer graphic once).
    xref = 0
    for i in range(page_count):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1} body content here.", fontsize=_BODY_SIZE, fontname="helv")
        if xref == 0:
            page.insert_image(fitz.Rect(72, 700, 172, 740), stream=logo_png)
            xref = page.get_images(full=True)[0][0]
        else:
            page.insert_image(fitz.Rect(72, 700, 172, 740), stream=logo_png, xref=xref)
    doc.save(str(path))
    doc.close()
    return path


def build_scanned_pdf(path: str | Path, page_count: int = 3) -> Path:
    """Pages that are each a single full-page image with no extractable
    text -- the scanned/image-only *tooling-missing fallback* fixture
    (no real text baked into the raster, so it's not useful for
    exercising OCR transcription itself -- see build_scanned_text_pdf)."""
    path = Path(path)
    doc = fitz.open()
    page_png = _tiny_png_bytes((50, 70), color=(220, 220, 210))
    for _ in range(page_count):
        page = doc.new_page()
        page.insert_image(page.rect, stream=page_png)
    doc.save(str(path))
    doc.close()
    return path


def build_scanned_text_pdf(
    path: str | Path,
    text: str = "This is a scanned document about accessibility remediation",
    page_count: int = 1,
) -> Path:
    """A scanned/image-only PDF whose page image is a rasterized page of
    real, clearly legible text (30pt+, per the OCR test plan) -- for
    exercising the OCR-transcription path end-to-end. Built by rendering
    text into a normal PDF page with `insert_textbox` (so it wraps within
    the page instead of running off the edge), rasterizing that page to
    a PNG via PyMuPDF, then wrapping the PNG as a full-page image on a
    fresh, textless page -- the same "image-only PDF" shape as
    `build_scanned_pdf`, just with real transcribable content."""
    path = Path(path)
    text_doc = fitz.open()
    text_page = text_doc.new_page()
    rect = fitz.Rect(72, 250, text_page.rect.width - 72, 500)
    text_page.insert_textbox(rect, text, fontsize=30, fontname="helv", align=1)
    page_png = text_page.get_pixmap(dpi=150).tobytes("png")
    text_doc.close()

    doc = fitz.open()
    for _ in range(page_count):
        page = doc.new_page()
        page.insert_image(page.rect, stream=page_png)
    doc.save(str(path))
    doc.close()
    return path


def build_mixed_scanned_pdf(
    path: str | Path,
    real_page_count: int = 5,
    scan_text: str = "This is a scanned signature page about accessibility",
) -> Path:
    """`real_page_count` born-digital text pages followed by one
    scanned/image-only page -- the QA blocker-1 regression fixture: a
    document-wide average must not hide a single scanned page mixed
    into an otherwise normal document. Covers both the 1+1 and 5+1
    cases the reviewer reproduced (pass `real_page_count=1` for the
    former)."""
    path = Path(path)
    text_doc = fitz.open()
    text_page = text_doc.new_page()
    rect = fitz.Rect(72, 250, text_page.rect.width - 72, 500)
    text_page.insert_textbox(rect, scan_text, fontsize=30, fontname="helv", align=1)
    page_png = text_page.get_pixmap(dpi=150).tobytes("png")
    text_doc.close()

    doc = fitz.open()
    for i in range(real_page_count):
        page = doc.new_page()
        page.insert_text((72, 72), f"Real Page {i + 1} Heading", fontsize=_H1_SIZE, fontname="helv")
        page.insert_text(
            (72, 120),
            f"Body paragraph content for real page {i + 1} of ordinary prose text.",
            fontsize=_BODY_SIZE,
            fontname="helv",
        )
    scan_page = doc.new_page()
    scan_page.insert_image(scan_page.rect, stream=page_png)
    doc.save(str(path))
    doc.close()
    return path


def build_noise_scan_pdf(path: str | Path, page_count: int = 1) -> Path:
    """A page whose image is random pixel noise (no legible text at
    all) -- the zero-yield-OCR regression fixture (QA blocker-2):
    should OCR to (near-)empty text, distinct from a page with genuine,
    if fuzzy, transcribable content."""
    import random

    path = Path(path)
    rng = random.Random(0)
    img = PILImage.new("RGB", (200, 260))
    pixels = img.load()
    for x in range(img.width):
        for y in range(img.height):
            pixels[x, y] = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    page_png = buf.getvalue()

    doc = fitz.open()
    for _ in range(page_count):
        page = doc.new_page()
        page.insert_image(page.rect, stream=page_png)
    doc.save(str(path))
    doc.close()
    return path


def build_rotated_scanned_text_pdf(
    path: str | Path,
    text: str = "This is a scanned document about accessibility remediation",
    rotation: int = 90,
) -> Path:
    """Same shape as `build_scanned_text_pdf`, but the rasterized page
    image is rotated before being embedded -- the QA blocker-4
    regression fixture for ocrmypdf's `rotate_pages` orientation
    correction (Tesseract OSD)."""
    path = Path(path)
    text_doc = fitz.open()
    text_page = text_doc.new_page()
    rect = fitz.Rect(72, 250, text_page.rect.width - 72, 500)
    text_page.insert_textbox(rect, text, fontsize=30, fontname="helv", align=1)
    page_png = text_page.get_pixmap(dpi=150).tobytes("png")
    text_doc.close()

    img = PILImage.open(io.BytesIO(page_png))
    rotated = img.rotate(-rotation, expand=True)
    buf = io.BytesIO()
    rotated.save(buf, format="PNG")
    rotated_png = buf.getvalue()

    doc = fitz.open()
    page = doc.new_page()
    # `keep_proportion=False` (the rotated image's aspect ratio no
    # longer matches the page's) so the placed image still fills (near)
    # the whole page area -- otherwise PyMuPDF letterboxes it and the
    # scan-detection heuristic's "big image" check never fires.
    page.insert_image(page.rect, stream=rotated_png, keep_proportion=False)
    doc.save(str(path))
    doc.close()
    return path


def build_mixed_scanned_with_born_digital_full_page_image_pdf(path: str | Path) -> Path:
    """A born-digital page with its own genuine full-page image (real
    content, not a scan artifact) followed by a scanned/image-only
    page -- regression fixture for scoping `SCAN_IMAGES_EXCLUDED`
    suppression to only the pages actually classified as scanned: the
    born-digital page's full-page image must still come through as a
    normal (MISSING_ALT) content image."""
    path = Path(path)
    text_doc = fitz.open()
    text_page = text_doc.new_page()
    rect = fitz.Rect(72, 250, text_page.rect.width - 72, 500)
    text_page.insert_textbox(rect, "This is a scanned page about accessibility", fontsize=30, fontname="helv", align=1)
    page_png = text_page.get_pixmap(dpi=150).tobytes("png")
    text_doc.close()

    doc = fitz.open()
    born_digital = doc.new_page()
    born_digital.insert_text((72, 72), "Real Page Heading", fontsize=_H1_SIZE, fontname="helv")
    born_digital.insert_text(
        (72, 120), "Plenty of ordinary body prose sits on this born-digital page.", fontsize=_BODY_SIZE, fontname="helv"
    )
    full_page_png = _tiny_png_bytes((400, 500), color=(60, 120, 40))
    born_digital.insert_image(born_digital.rect, stream=full_page_png)

    scan_page = doc.new_page()
    scan_page.insert_image(scan_page.rect, stream=page_png)

    doc.save(str(path))
    doc.close()
    return path


def build_encrypted_pdf(path: str | Path) -> Path:
    """A password-protected PDF -- the encrypted-PDF rejection
    fixture."""
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Secret content.", fontsize=_BODY_SIZE, fontname="helv")
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-pw",
        user_pw="user-pw",
    )
    doc.close()
    return path


def build_table_pdf(path: str | Path) -> Path:
    """A page with a real vector-bordered `<table>`, via WeasyPrint, so
    PyMuPDF's `find_tables()` can detect a simple grid."""
    path = Path(path)
    html = """<html lang="en"><head><style>
    body { font-family: sans-serif; }
    table { border-collapse: collapse; }
    th, td { border: 1px solid #000; padding: 4px 8px; }
    </style></head><body>
    <h1>Quarterly Counts</h1>
    <table>
    <tr><th>Region</th><th>Count</th></tr>
    <tr><td>North</td><td>12</td></tr>
    <tr><td>South</td><td>9</td></tr>
    </table>
    </body></html>"""
    HTML(string=html).write_pdf(str(path))
    return path


def build_fixture_pdf(path: str | Path, set_lang: str | None = None) -> Path:
    """An end-to-end fixture covering headings, a paragraph, a table, a
    real content-sized image, and a link -- for the CLI/pipeline E2E
    test (mirrors docx_fixtures.build_fixture_docx)."""
    path = Path(path)
    img = _tiny_png_bytes((300, 300), color=(30, 90, 200))
    b64 = __import__("base64").b64encode(img).decode("ascii")
    lang_attr = f' lang="{set_lang}"' if set_lang else ""
    html = f"""<html{lang_attr}><head><style>
    body {{ font-family: sans-serif; }}
    table {{ border-collapse: collapse; }}
    th, td {{ border: 1px solid #000; padding: 4px 8px; }}
    </style></head><body>
    <h1>Fixture Report</h1>
    <p>Intro paragraph with a <a href="https://example.org/details">link to details</a> and enough
    surrounding prose to be realistic body text content for the pipeline test.</p>
    <h2>Data</h2>
    <table>
    <tr><th>Region</th><th>Count</th></tr>
    <tr><td>North</td><td>12</td></tr>
    <tr><td>South</td><td>9</td></tr>
    </table>
    <img src="data:image/png;base64,{b64}" style="width:200px;height:200px;">
    </body></html>"""
    HTML(string=html).write_pdf(str(path))
    return path


def build_large_pdf(path: str | Path, page_count: int = 550) -> Path:
    """A large multi-hundred-page PDF with mixed headings/paragraphs and
    occasional images, for the large-document / memory-bounded
    extraction test (task 9). Built with raw PyMuPDF rather than
    WeasyPrint -- rendering 500+ pages through a full CSS layout engine
    is orders of magnitude slower than placing text directly."""
    path = Path(path)
    doc = fitz.open()
    logo_png = _tiny_png_bytes((60, 30), color=(80, 80, 80))
    xref = 0
    for i in range(page_count):
        page = doc.new_page()
        page.insert_text((72, 72), f"Chapter {i + 1}", fontsize=_H1_SIZE, fontname="helv")
        page.insert_text((72, 110), "A subsection heading", fontsize=_H2_SIZE, fontname="helv")
        page.insert_text((72, 140), f"Body paragraph text for page {i + 1} of the large test document.", fontsize=_BODY_SIZE, fontname="helv")
        page.insert_text((72, 156), "It continues with a second line of ordinary prose content.", fontsize=_BODY_SIZE, fontname="helv")
        if i % 10 == 0:
            if xref == 0:
                page.insert_image(fitz.Rect(72, 200, 172, 260), stream=logo_png)
                xref = page.get_images(full=True)[0][0]
            else:
                page.insert_image(fitz.Rect(72, 200, 172, 260), stream=logo_png, xref=xref)
    doc.save(str(path))
    doc.close()
    return path


def build_wrapped_link_pdf(path: str | Path) -> Path:
    """A link annotation whose rect covers TWO text lines (wrapped link
    text) -- regression fixture: every intersecting span must carry the
    href, not just the first."""
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Read the accessibility guidance", fontsize=_BODY_SIZE, fontname="helv")
    page.insert_text((72, 88), "published by the access board", fontsize=_BODY_SIZE, fontname="helv")
    # One annotation spanning both lines' bboxes.
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 58, 260, 94), "uri": "https://example.org/guidance"})
    doc.save(str(path))
    doc.close()
    return path


def build_intro_numbered_list_pdf(path: str | Path) -> Path:
    """A single text block that starts with a non-list intro line
    followed by numbered items -- regression fixture: the list must be
    classified ordered from its first ITEM line, not the intro line."""
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in ["Follow these steps carefully:", "1. Open the document panel", "2. Choose the tagged export", "3. Save the result"]:
        page.insert_text((72, y), line, fontsize=_BODY_SIZE, fontname="helv")
        y += 16
    doc.save(str(path))
    doc.close()
    return path
