"""Tests for the compliance report generator (src/remediate/report.py)."""

from __future__ import annotations

import json

from remediate.extractors.docx import extract_docx
from remediate.html_gen import generate_html
from remediate.report import build_report, render_report_html


def test_report_maps_flags_and_autofixes_to_r_numbers(fixture_docx):
    doc = extract_docx(fixture_docx)
    html_result = generate_html(doc)
    report = build_report(doc, html_result.autofixes)

    by_code = {item.code: item for item in report.items}

    assert by_code["LANG_ASSUMED"].r_number == "R15"
    assert by_code["LANG_ASSUMED"].wcag_sc == "3.1.1"
    assert by_code["LANG_ASSUMED"].severity == "needs-human-review"

    assert by_code["MISSING_ALT"].r_number == "R1b"
    assert by_code["MISSING_ALT"].wcag_sc == "1.1.1"

    assert by_code["GENERIC_LINK_TEXT"].r_number == "R13"
    assert by_code["GENERIC_LINK_TEXT"].wcag_sc == "2.4.4"

    assert by_code["HEADING_SKIP_REPAIRED"].r_number == "R14"
    assert by_code["HEADING_SKIP_REPAIRED"].severity == "auto-fixed"


def test_report_json_round_trips(fixture_docx):
    doc = extract_docx(fixture_docx)
    html_result = generate_html(doc)
    report = build_report(doc, html_result.autofixes)

    data = json.loads(report.to_json())
    assert data["document_title"] == doc.title
    assert data["summary"]["total_items"] == len(report.items)
    assert len(data["items"]) == len(report.items)


def test_report_html_lists_all_items(fixture_docx):
    doc = extract_docx(fixture_docx)
    html_result = generate_html(doc)
    report = build_report(doc, html_result.autofixes)

    html_str = render_report_html(report)
    assert "Compliance report" in html_str
    for item in report.items:
        assert item.code in html_str or item.message[:20] in html_str


def test_report_counts_by_severity(fixture_docx):
    doc = extract_docx(fixture_docx)
    html_result = generate_html(doc)
    report = build_report(doc, html_result.autofixes)

    counts = report.counts
    assert counts["auto-fixed"] >= 1
    assert counts["needs-human-review"] >= 1
    assert sum(counts.values()) == len(report.items)
