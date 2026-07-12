"""End-to-end PDF tests: pipeline function, CLI, PDF/UA structure
evidence, and large-document memory-bounded extraction (plan task 9)."""

from __future__ import annotations

import json
import re
import resource
import subprocess
import sys

import fitz  # PyMuPDF
import pytest

from pdf_fixtures import build_large_pdf
from remediate.extractors.pdf import PdfExtractionError
from remediate.pipeline import remediate_file

# A generous ceiling -- the point of this test is to catch "materialize
# every page's raw dict simultaneously" regressions (which would scale
# with page count into the GBs), not to pin an exact number.
_MAX_RSS_MB = 1500


def test_pipeline_produces_all_four_outputs(fixture_pdf, tmp_path):
    result = remediate_file(fixture_pdf, tmp_path / "out")

    assert result.pdf_path.exists()
    assert result.html_path.exists()
    assert result.report_json_path.exists()
    assert result.report_html_path.exists()
    assert result.pdf_path.stat().st_size > 0


def test_pipeline_progress_callback_reports_extraction_progress(fixture_pdf, tmp_path):
    stages = []
    remediate_file(fixture_pdf, tmp_path / "out", progress_callback=lambda s, p: stages.append((s, p)))

    assert stages[0][1] == pytest.approx(0.0)
    assert stages[-1] == ("done", pytest.approx(1.0))
    assert any(s == "extracting" for s, _ in stages)


def test_cli_end_to_end_run_on_pdf(fixture_pdf, tmp_path):
    outdir = tmp_path / "cli_out"
    proc = subprocess.run(
        [sys.executable, "-m", "remediate", str(fixture_pdf), "-o", str(outdir)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr

    assert (outdir / "fixture.pdf").exists()
    assert (outdir / "fixture.html").exists()
    assert (outdir / "report.json").exists()
    assert (outdir / "report.html").exists()


def test_cli_rejects_scanned_pdf_with_clean_message(tmp_path):
    from pdf_fixtures import build_scanned_pdf

    scanned = build_scanned_pdf(tmp_path / "scan.pdf")
    outdir = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, "-m", "remediate", str(scanned), "-o", str(outdir)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "scanned" in proc.stderr.lower()


def test_output_pdf_has_struct_tree_root_and_lang(fixture_pdf, tmp_path):
    result = remediate_file(fixture_pdf, tmp_path / "out")

    doc = fitz.open(result.pdf_path)
    try:
        catalog_obj = doc.xref_object(doc.pdf_catalog(), compressed=False)
        assert "/StructTreeRoot" in catalog_obj
        assert "/Lang (en)" in catalog_obj
        assert "/MarkInfo" in catalog_obj
        assert "/DisplayDocTitle true" in catalog_obj

        struct_tags = set()
        for xref in range(1, doc.xref_length()):
            try:
                obj = doc.xref_object(xref, compressed=False)
            except Exception:
                continue
            if "/StructElem" in obj:
                m = re.search(r"/S\s*/(\w+)", obj)
                if m:
                    struct_tags.add(m.group(1))

        assert "H1" in struct_tags
        assert "H2" in struct_tags
        assert "Table" in struct_tags
        assert "TH" in struct_tags
        assert "Figure" in struct_tags
        assert "Link" in struct_tags
    finally:
        doc.close()


def test_report_flags_match_pdf_fixture_known_judgment_calls(fixture_pdf, tmp_path):
    result = remediate_file(fixture_pdf, tmp_path / "out")
    data = json.loads(result.report_json_path.read_text())
    codes = {item["code"] for item in data["items"]}

    assert "HEADINGS_INFERRED" in codes
    assert "MISSING_ALT" in codes
    assert "NO_HEADER_ROW_DETECTED" in codes


def test_pdf_extraction_error_propagates_through_pipeline(tmp_path):
    from pdf_fixtures import build_encrypted_pdf

    encrypted = build_encrypted_pdf(tmp_path / "enc.pdf")
    with pytest.raises(PdfExtractionError):
        remediate_file(encrypted, tmp_path / "out")


def test_large_pdf_pipeline_completes_quick_variant(tmp_path):
    """Always-run smaller variant of the large-document test, so CI
    catches an extraction regression even without `-m slow`."""
    large = build_large_pdf(tmp_path / "medium.pdf", page_count=40)
    result = remediate_file(large, tmp_path / "out")
    assert result.pdf_path.exists()


@pytest.mark.slow
def test_large_pdf_pipeline_completes_within_bounded_memory(tmp_path):
    large = build_large_pdf(tmp_path / "large.pdf", page_count=550)

    result = remediate_file(large, tmp_path / "out")

    assert result.pdf_path.exists()
    assert result.pdf_path.stat().st_size > 0

    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_mb = peak_rss_kb / 1024
    assert peak_rss_mb < _MAX_RSS_MB, f"peak RSS {peak_rss_mb:.0f}MB exceeded {_MAX_RSS_MB}MB budget"
