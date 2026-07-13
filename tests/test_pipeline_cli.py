"""End-to-end tests: pipeline function, CLI, and PDF/UA structure
evidence on the actual rendered output (mirrors spike/pdfua_spike.py's
inspection approach)."""

from __future__ import annotations

import json
import subprocess
import sys

import fitz  # PyMuPDF
import pytest

from remediate.extractors.docx import DocxExtractionError
from remediate.pipeline import UnsupportedFileError, remediate_file


def test_pipeline_produces_all_four_outputs(fixture_docx, tmp_path):
    outdir = tmp_path / "out"
    result = remediate_file(fixture_docx, outdir)

    assert result.pdf_path.exists()
    assert result.html_path.exists()
    assert result.report_json_path.exists()
    assert result.report_html_path.exists()
    assert result.pdf_path.stat().st_size > 0


def test_pipeline_progress_callback_reaches_done(fixture_docx, tmp_path):
    stages = []
    remediate_file(fixture_docx, tmp_path / "out", progress_callback=lambda s, p: stages.append((s, p)))

    assert stages[0][1] == pytest.approx(0.0)
    assert stages[-1] == ("done", pytest.approx(1.0))


def test_pipeline_rejects_unsupported_extension(tmp_path):
    bogus = tmp_path / "file.txt"
    bogus.write_text("not a docx")
    with pytest.raises(UnsupportedFileError):
        remediate_file(bogus, tmp_path / "out")


def test_pipeline_rejects_corrupt_docx(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"not a real docx")
    with pytest.raises(DocxExtractionError):
        remediate_file(bad, tmp_path / "out")


def test_cli_end_to_end_run(fixture_docx, tmp_path):
    outdir = tmp_path / "cli_out"
    proc = subprocess.run(
        [sys.executable, "-m", "remediate", str(fixture_docx), "-o", str(outdir)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr

    assert (outdir / "fixture.pdf").exists()
    assert (outdir / "fixture.html").exists()
    assert (outdir / "report.json").exists()
    assert (outdir / "report.html").exists()


def test_cli_exits_nonzero_and_prints_message_on_rejection(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"not a real docx")
    outdir = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, "-m", "remediate", str(bad), "-o", str(outdir)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "error" in proc.stderr.lower()


def test_output_pdf_has_struct_tree_root_and_lang(fixture_docx, tmp_path):
    outdir = tmp_path / "out"
    result = remediate_file(fixture_docx, outdir)

    doc = fitz.open(result.pdf_path)
    try:
        catalog_xref = doc.pdf_catalog()
        catalog_obj = doc.xref_object(catalog_xref, compressed=False)

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
                import re

                m = re.search(r"/S\s*/(\w+)", obj)
                if m:
                    struct_tags.add(m.group(1))

        assert "H1" in struct_tags
        assert "H2" in struct_tags
        assert "Table" in struct_tags
        assert "TH" in struct_tags
        assert "Figure" in struct_tags
        assert "Link" in struct_tags
        assert "L" in struct_tags  # list
    finally:
        doc.close()


def test_report_flags_match_fixture_known_judgment_calls(fixture_docx, tmp_path):
    result = remediate_file(fixture_docx, tmp_path / "out")
    data = json.loads(result.report_json_path.read_text())
    codes = {item["code"] for item in data["items"]}

    assert "LANG_DETECTED" in codes  # no lang metadata, but real prose present
    assert "MISSING_ALT" in codes
    assert "GENERIC_LINK_TEXT" in codes
    assert "HEADING_SKIP_REPAIRED" in codes
