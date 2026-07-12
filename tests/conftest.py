from __future__ import annotations

import pytest

from docx_fixtures import build_fixture_docx, build_minimal_docx


@pytest.fixture
def fixture_docx(tmp_path):
    """A .docx exercising every extraction case: heading skip, nested
    list, header-row table, unlabelled image, generic link text, no
    explicit language."""
    return build_fixture_docx(tmp_path / "fixture.docx")


@pytest.fixture
def fixture_docx_with_lang(tmp_path):
    return build_fixture_docx(tmp_path / "fixture_lang.docx", set_language="fr-FR")


@pytest.fixture
def minimal_docx(tmp_path):
    """A .docx with no headings at all."""
    return build_minimal_docx(tmp_path / "minimal.docx")
