"""Helpers for building small .docx fixtures programmatically with
python-docx, for the extractor/pipeline test suite.

Kept out of conftest.py so it can be imported directly by tests that
want to build custom variants (e.g. a docx with an explicit language)
without going through a fixture.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import docx
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches
from PIL import Image as PILImage

# A tiny in-memory 4x4 PNG, used as the fixture's "image without alt text".
def _tiny_png_bytes() -> bytes:
    img = PILImage.new("RGB", (4, 4), color=(200, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def add_hyperlink(paragraph, url: str, text: str) -> None:
    part = paragraph.part
    r_id = part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    run.append(OxmlElement("w:rPr"))
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def mark_header_row(table) -> None:
    """Set Word's 'repeat as header row' property on a table's first row."""
    tr = table.rows[0]._tr
    trPr = OxmlElement("w:trPr")
    trPr.append(OxmlElement("w:tblHeader"))
    tr.insert(0, trPr)


def add_nested_bullet_list(doc, top_text: str, nested_text: str) -> None:
    """Add a two-level nested bullet list using an explicit numId/ilvl,
    backed by a real multi-level numbering definition injected into the
    package after save() (python-docx's default template's built-in
    "List Bullet"/"List Bullet 2" styles use *separate* single-level
    numId's, not a shared multi-level list, so they don't nest under
    mammoth -- this fixture builds the real thing instead)."""
    num_id = 900

    def add_item(text: str, ilvl: int):
        p = doc.add_paragraph(text, style="List Bullet")
        pPr = p._p.get_or_add_pPr()
        numPr = OxmlElement("w:numPr")
        ilvl_el = OxmlElement("w:ilvl")
        ilvl_el.set(qn("w:val"), str(ilvl))
        numId_el = OxmlElement("w:numId")
        numId_el.set(qn("w:val"), str(num_id))
        numPr.append(ilvl_el)
        numPr.append(numId_el)
        pPr.append(numPr)

    add_item(top_text, 0)
    add_item(nested_text, 1)


_NUMBERING_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:abstractNum w:abstractNumId="900">
<w:multiLevelType w:val="hybridMultilevel"/>
<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="&#8226;"/>
<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl>
<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="o"/>
<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="1440" w:hanging="360"/></w:pPr></w:lvl>
</w:abstractNum>
<w:num w:numId="900"><w:abstractNumId w:val="900"/></w:num>
</w:numbering>"""


def _inject_numbering_part(docx_bytes: bytes) -> bytes:
    """Post-process a saved .docx's zip to add a real multi-level
    numbering.xml part (see add_nested_bullet_list docstring)."""
    zin = zipfile.ZipFile(io.BytesIO(docx_bytes), "r")
    names = zin.namelist()
    has_numbering = "word/numbering.xml" in names

    outbuf = io.BytesIO()
    zout = zipfile.ZipFile(outbuf, "w", zipfile.ZIP_DEFLATED)
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == "word/numbering.xml":
            data = _NUMBERING_XML_TEMPLATE.encode("utf-8")
        elif item.filename == "[Content_Types].xml" and not has_numbering:
            data = data.replace(
                b"</Types>",
                b'<Override PartName="/word/numbering.xml" '
                b'ContentType="application/vnd.openxmlformats-officedocument'
                b'.wordprocessingml.numbering+xml"/></Types>',
            )
        elif item.filename == "word/_rels/document.xml.rels" and not has_numbering:
            data = data.replace(
                b"</Relationships>",
                b'<Relationship Id="rIdFixtureNumbering900" '
                b'Type="http://schemas.openxmlformats.org/officeDocument/2006'
                b'/relationships/numbering" Target="numbering.xml"/></Relationships>',
            )
        zout.writestr(item, data)
    if not has_numbering:
        zout.writestr("word/numbering.xml", _NUMBERING_XML_TEMPLATE)
    zout.close()
    return outbuf.getvalue()


def build_fixture_docx(path: str | Path, set_language: str | None = None) -> Path:
    """Build a .docx covering every extraction case the test suite needs:
    a heading hierarchy with a skipped level (H1 -> H3), a nested bullet
    list, a table with an explicit header row, an image with no alt
    text, and a "click here" generic link. Language is left unset unless
    `set_language` is given.
    """
    path = Path(path)
    doc = docx.Document()

    if set_language:
        doc.core_properties.language = set_language

    doc.add_heading("Fixture Document", level=1)
    doc.add_heading("Deeply Nested Section", level=3)  # heading-skip case

    p = doc.add_paragraph("This is intro text with a ")
    run = p.add_run("bold word")
    run.bold = True
    p.add_run(".")

    link_para = doc.add_paragraph("For details, ")
    add_hyperlink(link_para, "https://example.org/details", "click here")

    add_nested_bullet_list(doc, "Top-level item", "Nested item")

    table = doc.add_table(rows=2, cols=2)
    mark_header_row(table)
    table.rows[0].cells[0].text = "Region"
    table.rows[0].cells[1].text = "Count"
    table.rows[1].cells[0].text = "North"
    table.rows[1].cells[1].text = "12"

    img_buf = io.BytesIO(_tiny_png_bytes())
    doc.add_picture(img_buf, width=Inches(0.5))  # no alt text set -> MISSING_ALT

    buf = io.BytesIO()
    doc.save(buf)
    docx_bytes = _inject_numbering_part(buf.getvalue())

    path.write_bytes(docx_bytes)
    return path


def build_minimal_docx(path: str | Path) -> Path:
    """A docx with no headings at all -- for the title-promotion case."""
    path = Path(path)
    doc = docx.Document()
    doc.add_paragraph("Just a paragraph, no headings.")
    buf = io.BytesIO()
    doc.save(buf)
    path.write_bytes(buf.getvalue())
    return path
