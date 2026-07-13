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

from pdf_fixtures import (
    build_mixed_scanned_pdf,
    build_mixed_scanned_with_born_digital_full_page_image_pdf,
    build_noise_scan_pdf,
    build_rotated_scanned_text_pdf,
    build_scanned_pdf,
    build_scanned_text_pdf,
)
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


# ---------------------------------------------------------------------------
# QA blocker 1: per-page scan detection on mixed real-text + scanned docs.
# A document-wide average must not hide a single scanned page.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("real_page_count", [1, 5])
def test_mixed_document_ocrs_the_scanned_page_and_keeps_real_text(tmp_path, real_page_count):
    mixed = build_mixed_scanned_pdf(tmp_path / "mixed.pdf", real_page_count=real_page_count)
    doc = extract_pdf(mixed)

    all_text = " ".join(b.text for b in doc.blocks if isinstance(b, (Heading, Paragraph)))
    # The scanned page's content was actually transcribed.
    assert "accessibility" in all_text.lower()
    # Every real page's text survived verbatim.
    for i in range(real_page_count):
        assert f"Real Page {i + 1} Heading" in all_text
        assert f"Body paragraph content for real page {i + 1}" in all_text

    assert any(f.code == "OCR_APPLIED" for f in doc.all_flags())


def test_mixed_document_suppresses_scan_image_only_on_the_scanned_page(tmp_path):
    fixture = build_mixed_scanned_with_born_digital_full_page_image_pdf(
        tmp_path / "mixed_with_image.pdf"
    )
    doc = extract_pdf(fixture)

    # The born-digital page's genuine full-page image must survive as
    # real content (MISSING_ALT), not be suppressed as a scan artifact.
    images = [b for b in doc.blocks if isinstance(b, Image)]
    assert len(images) == 1
    assert any(f.code == "MISSING_ALT" for f in images[0].flags)

    flags = doc.all_flags()
    assert any(f.code == "OCR_APPLIED" for f in flags)
    assert any(f.code == "SCAN_IMAGES_EXCLUDED" for f in flags)
    # One flag for the whole document, still.
    assert len([f for f in flags if f.code == "SCAN_IMAGES_EXCLUDED"]) == 1


# ---------------------------------------------------------------------------
# QA blocker 2: zero-yield OCR must not look like a resolved transcription.
# ---------------------------------------------------------------------------


def test_blank_scan_gets_no_text_recovered_flag(tmp_path):
    blank = build_scanned_pdf(tmp_path / "blank.pdf", page_count=1)
    doc = extract_pdf(blank)

    flags = doc.all_flags()
    assert any(f.code == "OCR_APPLIED" for f in flags)
    no_text_flags = [f for f in flags if f.code == "OCR_NO_TEXT_RECOVERED"]
    assert len(no_text_flags) == 1
    assert "page(s) 1" in no_text_flags[0].message

    report = build_report(doc, [])
    item = next(i for i in report.items if i.code == "OCR_NO_TEXT_RECOVERED")
    assert item.severity == "needs-human-review"
    assert item.r_number == "R22"


def test_noise_scan_gets_no_text_recovered_flag(tmp_path):
    noise = build_noise_scan_pdf(tmp_path / "noise.pdf")
    doc = extract_pdf(noise)

    flags = doc.all_flags()
    assert any(f.code == "OCR_APPLIED" for f in flags)
    assert any(f.code == "OCR_NO_TEXT_RECOVERED" for f in flags)


def test_legible_scan_does_not_get_no_text_recovered_flag(tmp_path):
    scanned = build_scanned_text_pdf(tmp_path / "legible.pdf")
    doc = extract_pdf(scanned)

    assert not any(f.code == "OCR_NO_TEXT_RECOVERED" for f in doc.all_flags())


# ---------------------------------------------------------------------------
# QA should-fix 3: OCR timeout guard.
# ---------------------------------------------------------------------------


def test_ocr_overall_timeout_raises_clean_error(tmp_path, monkeypatch):
    import time

    import ocrmypdf

    from remediate import ocr as ocr_module

    def _slow_ocr(*args, **kwargs):
        time.sleep(2)

    monkeypatch.setattr(ocrmypdf, "ocr", _slow_ocr)

    with pytest.raises(ocr_module.OcrTimeoutError, match="time budget"):
        ocr_module.ocr_to_pdf(
            tmp_path / "in.pdf", tmp_path / "out.pdf", overall_timeout=0.1
        )


def test_pdf_extraction_wraps_ocr_timeout_in_extraction_error(tmp_path, monkeypatch):
    from remediate import ocr as ocr_module
    from remediate.extractors import pdf as pdf_module

    def _timeout_ocr_to_pdf(input_path, output_path):
        raise ocr_module.OcrTimeoutError("OCR exceeded its overall time budget (0s) and was aborted.")

    monkeypatch.setattr(pdf_module._ocr, "ocr_to_pdf", _timeout_ocr_to_pdf)

    scanned = build_scanned_text_pdf(tmp_path / "scan.pdf")
    with pytest.raises(pdf_module.PdfExtractionError, match="OCR failed"):
        extract_pdf(scanned)


# ---------------------------------------------------------------------------
# QA should-fix 4: rotated scans -- ocrmypdf's rotate_pages (Tesseract OSD).
# ---------------------------------------------------------------------------


def test_rotated_scan_transcribes_correctly_via_orientation_correction(tmp_path):
    rotated = build_rotated_scanned_text_pdf(tmp_path / "rotated.pdf", rotation=90)
    doc = extract_pdf(rotated)

    all_text = " ".join(
        b.text for b in doc.blocks if isinstance(b, (Heading, Paragraph))
    ).lower()
    assert "accessibility" in all_text
    assert not any(f.code == "OCR_NO_TEXT_RECOVERED" for f in doc.all_flags())

