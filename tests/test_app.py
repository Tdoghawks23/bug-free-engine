"""Web app tests (plan task 10): upload -> poll -> download flow, and the
error/validation paths (bad extension, unknown job, path traversal on the
artifact name, a rejected scanned PDF)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from docx_fixtures import build_fixture_docx
from pdf_fixtures import build_scanned_pdf
from remediate import app as app_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "JOBS_ROOT", tmp_path / "jobs")
    with TestClient(app_module.app) as test_client:
        yield test_client


def _poll_until_finished(client: TestClient, job_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["state"] in ("done", "error"):
            return body
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def test_upload_poll_download_docx(client, tmp_path):
    docx_path = build_fixture_docx(tmp_path / "fixture.docx")

    with docx_path.open("rb") as f:
        resp = client.post(
            "/jobs",
            files={"file": ("fixture.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert resp.status_code == 200
    job_id = resp.json()["id"]

    status = _poll_until_finished(client, job_id)
    assert status["state"] == "done"
    assert status["summary"]["total_items"] > 0
    assert "auto-fixed" in status["summary"]
    assert "needs-human-review" in status["summary"]

    expected_content_types = {
        "pdf": "application/pdf",
        "html": "text/html",
        "report.html": "text/html",
        "report.json": "application/json",
    }
    for artifact, expected_ct in expected_content_types.items():
        dl = client.get(f"/jobs/{job_id}/download/{artifact}")
        assert dl.status_code == 200, artifact
        assert dl.headers["content-type"].startswith(expected_ct), artifact
        assert len(dl.content) > 0
        assert "content-disposition" in dl.headers


def test_upload_rejects_bad_extension(client):
    resp = client.post("/jobs", files={"file": ("notes.txt", b"just text", "text/plain")})
    assert resp.status_code == 400


def test_unknown_job_returns_404(client):
    resp = client.get("/jobs/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_malformed_job_id_returns_404(client):
    resp = client.get("/jobs/not-a-uuid")
    assert resp.status_code == 404


def test_scanned_pdf_ends_in_error_state_when_ocr_tooling_missing(client, tmp_path, monkeypatch):
    # Scanned PDFs are OCR'd automatically when tooling is present (see
    # test_ocr.py); this exercises the tooling-missing fallback.
    monkeypatch.setattr("remediate.ocr.available", lambda: False)
    scanned_path = build_scanned_pdf(tmp_path / "scan.pdf")

    with scanned_path.open("rb") as f:
        resp = client.post("/jobs", files={"file": ("scan.pdf", f, "application/pdf")})
    assert resp.status_code == 200
    job_id = resp.json()["id"]

    status = _poll_until_finished(client, job_id)
    assert status["state"] == "error"
    assert "ocr tooling" in status["error"].lower()


def test_path_traversal_on_artifact_name_is_rejected(client, tmp_path):
    docx_path = build_fixture_docx(tmp_path / "fixture.docx")
    with docx_path.open("rb") as f:
        resp = client.post("/jobs", files={"file": ("fixture.docx", f, "application/octet-stream")})
    job_id = resp.json()["id"]
    _poll_until_finished(client, job_id)

    dl = client.get(f"/jobs/{job_id}/download/..%2F..%2F..%2Fetc%2Fpasswd")
    assert dl.status_code in (404, 422)
    assert "content-disposition" not in dl.headers


def test_index_page_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Upload" in resp.text
