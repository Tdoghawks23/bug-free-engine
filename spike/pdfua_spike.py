"""Feasibility spike (plan task 2).

Hand-craft a minimal accessible HTML document and render it to a tagged
PDF/UA-1 file with WeasyPrint. Then inspect the resulting PDF's low-level
object graph with PyMuPDF to confirm a structure/tag tree actually exists
(StructTreeRoot, MarkInfo/Marked, Lang, DisplayDocTitle, and StructElems for
H1/Table/Figure with Alt text).

Run: python spike/pdfua_spike.py
Writes: spike/output.pdf, prints an evidence dump, and (this script only
prints — spike/FINDINGS.md is the human-readable writeup of the results).
"""

from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

import fitz  # PyMuPDF
from weasyprint import HTML

SPIKE_DIR = Path(__file__).parent
OUTPUT_PDF = SPIKE_DIR / "output.pdf"


def make_tiny_png_data_uri() -> str:
    """Generate a tiny red 4x4 PNG in-memory (no external asset needed)."""
    from PIL import Image

    img = Image.new("RGB", (4, 4), color=(200, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def build_html() -> str:
    img_uri = make_tiny_png_data_uri()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PDF/UA Spike Document</title>
<style>
  body {{ font-family: sans-serif; color: #111; }}
  table {{ border-collapse: collapse; }}
  th, td {{ border: 1px solid #333; padding: 4px 8px; text-align: left; }}
</style>
</head>
<body>
  <h1>PDF/UA Feasibility Spike</h1>
  <p>
    This document exists to prove (or disprove) that WeasyPrint's
    <code>pdf/ua-1</code> variant produces a real tagged-PDF structure
    tree, not just visually-formatted text. It contains a heading
    hierarchy, a data table with scoped headers, an embedded image with
    alt text, and a link with descriptive text.
  </p>

  <h2>A Simple Data Table</h2>
  <table>
    <caption>Quarterly widget counts by region</caption>
    <thead>
      <tr>
        <th scope="col">Region</th>
        <th scope="col">Q1</th>
        <th scope="col">Q2</th>
      </tr>
    </thead>
    <tbody>
      <tr><td>North</td><td>120</td><td>144</td></tr>
      <tr><td>South</td><td>98</td><td>110</td></tr>
    </tbody>
  </table>

  <h2>An Embedded Image</h2>
  <p>
    <img src="{img_uri}" alt="A small solid red square used as a spike test image" width="64" height="64">
  </p>

  <h2>A Descriptive Link</h2>
  <p>
    For background on tagged PDF and PDF/UA-1 conformance, see the
    <a href="https://www.iso.org/standard/64599.html">ISO 14289-1 PDF/UA-1 standard page</a>.
  </p>
</body>
</html>"""


def render_pdf() -> None:
    html_str = build_html()
    html = HTML(string=html_str, base_url=str(SPIKE_DIR))
    # WeasyPrint 60+: pdf_variant kwarg to write_pdf, values include
    # 'pdf/ua-1' and 'pdf/ua-2' (see weasyprint/pdf/pdfua.py VARIANTS).
    html.write_pdf(target=str(OUTPUT_PDF), pdf_variant="pdf/ua-1")
    print(f"Wrote {OUTPUT_PDF} ({OUTPUT_PDF.stat().st_size} bytes)")


def dump_struct_evidence() -> dict:
    """Inspect the PDF's catalog/xref objects for PDF/UA structure evidence."""
    doc = fitz.open(OUTPUT_PDF)
    evidence: dict = {}

    catalog_xref = doc.pdf_catalog()
    catalog_obj = doc.xref_object(catalog_xref, compressed=False)
    evidence["catalog_xref"] = catalog_xref
    evidence["catalog_object"] = catalog_obj

    has_struct_tree_root = "/StructTreeRoot" in catalog_obj
    has_marked = "/Marked true" in catalog_obj or "/MarkInfo" in catalog_obj
    has_lang = "/Lang" in catalog_obj
    has_display_doc_title = "/DisplayDocTitle true" in catalog_obj
    has_viewer_prefs = "/ViewerPreferences" in catalog_obj

    evidence["has_struct_tree_root"] = has_struct_tree_root
    evidence["has_marked_or_markinfo"] = has_marked
    evidence["has_lang_in_catalog"] = has_lang
    evidence["has_display_doc_title"] = has_display_doc_title
    evidence["has_viewer_prefs"] = has_viewer_prefs

    # Walk MarkInfo object directly if present, for Marked=true confirmation.
    markinfo_evidence = None
    if "/MarkInfo" in catalog_obj:
        # Extract the indirect reference, e.g. "/MarkInfo 12 0 R"
        import re

        m = re.search(r"/MarkInfo\s+(\d+)\s+0\s+R", catalog_obj)
        if m:
            mi_xref = int(m.group(1))
            markinfo_evidence = doc.xref_object(mi_xref, compressed=False)
    evidence["markinfo_object"] = markinfo_evidence

    # Find the StructTreeRoot object and walk a bit of its /K kids array,
    # then scan ALL objects in the file for StructElem entries so we can
    # report which tags (H1, Table, TH, Figure, Alt, Link, THead...) exist,
    # even if the doc is large enough that this brute scan feels wasteful
    # (fine for a hand-crafted 1-page spike doc).
    struct_elem_tags: list[str] = []
    alt_texts: list[str] = []
    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref, compressed=False)
        except Exception:
            continue
        if "/StructElem" in obj:
            import re

            s_match = re.search(r"/S\s*/(\w+)", obj)
            if s_match:
                struct_elem_tags.append(s_match.group(1))
            alt_match = re.search(r"/Alt\s*\(([^)]*)\)", obj)
            if alt_match:
                alt_texts.append(alt_match.group(1))

    evidence["struct_elem_tags"] = struct_elem_tags
    evidence["alt_texts_found"] = alt_texts

    doc.close()
    return evidence


def main() -> int:
    render_pdf()
    evidence = dump_struct_evidence()

    print("\n=== PDF/UA structure evidence ===")
    print(f"StructTreeRoot present:      {evidence['has_struct_tree_root']}")
    print(f"Marked/MarkInfo present:     {evidence['has_marked_or_markinfo']}")
    print(f"MarkInfo object:             {evidence['markinfo_object']}")
    print(f"Lang in catalog:             {evidence['has_lang_in_catalog']}")
    print(f"DisplayDocTitle true:        {evidence['has_display_doc_title']}")
    print(f"ViewerPreferences present:   {evidence['has_viewer_prefs']}")
    print(f"StructElem /S tags found:    {sorted(set(evidence['struct_elem_tags']))}")
    print(f"  full tag list ({len(evidence['struct_elem_tags'])} elems): {evidence['struct_elem_tags']}")
    print(f"Alt text strings found:      {evidence['alt_texts_found']}")
    print("\nCatalog object dump:")
    print(evidence["catalog_object"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
