"""Tests for OCR of scanned/image-only PDFs (plan tasks 2-3): the
transcription path itself, the tooling-missing fallback, and page-scan
image suppression. The tooling-missing/CLI/app-level fallback cases live
in test_pdf_extractor.py / test_pdf_pipeline_cli.py / test_app.py
(existing scanned-rejection tests, updated for the new behavior) -- this
file covers the OCR-specific mechanics."""

from __future__ import annotations

import subprocess
import sys

import fitz
import pytest

from pdf_fixtures import build_scanned_text_pdf
from remediate.extractors.pdf import extract_pdf
from remediate.ir import Heading, Image, Paragraph
from remediate.report import build_report


def test_ocr_transcribes_scanned_text_and_flags_for_review(tmp_path):
    scanned = build_scanned_text_pdf(tmp_path / "scan.pdf")
    doc = extract_pdf(scanned)

    all_text = " ".join(
        b.text for b in doc.blocks if isinstance(b, (Heading, Paragraph))
    ).lower()
    # OCR is fuzzy -- match on a single distinctive word rather than the
    # full source string.
    assert "accessibility" in all_text

    assert any(f.code == "OCR_APPLIED" for f in doc.all_flags())

    report = build_report(doc, [])
    ocr_items = [i for i in report.items if i.code == "OCR_APPLIED"]
    assert len(ocr_items) == 1
    assert ocr_items[0].severity == "needs-human-review"
    assert ocr_items[0].r_number == "R22"


def test_ocr_excludes_full_page_scan_images_without_missing_alt_flood(tmp_path):
    scanned = build_scanned_text_pdf(tmp_path / "scan.pdf", page_count=3)
    doc = extract_pdf(scanned)

    images = [b for b in doc.blocks if isinstance(b, Image)]
    assert images == []

    flags = doc.all_flags()
    assert not any(f.code == "MISSING_ALT" for f in flags)
    scan_excluded = [f for f in flags if f.code == "SCAN_IMAGES_EXCLUDED"]
    # One flag for the whole document, not one per page.
    assert len(scan_excluded) == 1


def test_cli_end_to_end_on_scanned_fixture_produces_all_artifacts(tmp_path):
    scanned = build_scanned_text_pdf(tmp_path / "scan.pdf")
    outdir = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, "-m", "remediate", str(scanned), "-o", str(outdir)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr

    pdf_path = outdir / "scan.pdf"
    assert pdf_path.exists()
    assert (outdir / "scan.html").exists()
    assert (outdir / "report.json").exists()
    assert (outdir / "report.html").exists()

    doc = fitz.open(pdf_path)
    try:
        catalog_obj = doc.xref_object(doc.pdf_catalog(), compressed=False)
        assert "/StructTreeRoot" in catalog_obj
    finally:
        doc.close()

    html_text = (outdir / "scan.html").read_text(encoding="utf-8").lower()
    assert "accessibility" in html_text


def test_mixed_document_with_real_text_is_not_treated_as_scanned(fixture_pdf):
    # A normal, born-digital PDF (the shared fixture) has plenty of real
    # text -- it should never hit the OCR path, and should keep the
    # pre-OCR full-page-image behavior (no scan-image suppression).
    stages = []
    doc = extract_pdf(fixture_pdf, progress_callback=lambda s, p: stages.append(s))
    assert not any(f.code == "OCR_APPLIED" for f in doc.all_flags())
    assert not any(f.code == "SCAN_IMAGES_EXCLUDED" for f in doc.all_flags())
    assert "ocr" not in stages
