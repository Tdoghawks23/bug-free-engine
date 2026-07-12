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
    text -- the scanned/image-only rejection fixture."""
    path = Path(path)
    doc = fitz.open()
    page_png = _tiny_png_bytes((50, 70), color=(220, 220, 210))
    for _ in range(page_count):
        page = doc.new_page()
        page.insert_image(page.rect, stream=page_png)
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
