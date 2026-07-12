from __future__ import annotations

import pytest

from docx_fixtures import (
    build_docx_with_filename_alt,
    build_docx_with_linked_image,
    build_docx_with_merged_table,
    build_fixture_docx,
    build_french_text_docx,
    build_minimal_docx,
    build_near_empty_docx,
)
from pdf_fixtures import build_fixture_pdf


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


@pytest.fixture
def linked_image_docx(tmp_path):
    """A .docx whose only content is an image wrapped in a hyperlink."""
    return build_docx_with_linked_image(tmp_path / "linked_image.docx")


@pytest.fixture
def filename_alt_docx(tmp_path):
    """A .docx with an image whose alt text is just its own filename."""
    return build_docx_with_filename_alt(tmp_path / "filename_alt.docx")


@pytest.fixture
def merged_table_docx(tmp_path):
    """A .docx with a table containing merged cells (colspan/rowspan)."""
    return build_docx_with_merged_table(tmp_path / "merged_table.docx")


@pytest.fixture
def french_text_docx(tmp_path):
    """A .docx with real French prose and no language metadata."""
    return build_french_text_docx(tmp_path / "french.docx")


@pytest.fixture
def near_empty_docx(tmp_path):
    """A .docx with almost no text -- too little for language detection."""
    return build_near_empty_docx(tmp_path / "near_empty.docx")


@pytest.fixture
def fixture_pdf(tmp_path):
    """A .pdf exercising every extraction case: headings, a paragraph
    with a link, a table, and a real content-sized image."""
    return build_fixture_pdf(tmp_path / "fixture.pdf")


@pytest.fixture
def fixture_pdf_with_lang(tmp_path):
    return build_fixture_pdf(tmp_path / "fixture_lang.pdf", set_lang="fr")
