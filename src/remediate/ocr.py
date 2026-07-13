"""Optional OCR integration for scanned/image-only PDFs (plan task 2).

`ocrmypdf` (and its system deps: tesseract, ghostscript) is a normal
dependency of this project (see pyproject.toml), but the import stays
lazy here and every entry point re-checks `available()` at runtime: a
deployment missing the system-level tesseract/ghostscript binaries (or
running an environment where the package was deliberately stripped)
should degrade to the pre-OCR "scanned PDFs are rejected" behavior
instead of crashing the whole app on import. `extractors/pdf.py` is the
only caller.
"""

from __future__ import annotations

import shutil
from pathlib import Path

_TESSERACT_BIN = "tesseract"
_GHOSTSCRIPT_BIN = "gs"

# English-only for v1 (per plan) -- additional languages are a matter of
# installing more `tesseract-ocr-<lang>` packages and widening this list
# later, not a code change.
_LANGUAGE = "eng"


def available() -> bool:
    """True if the full OCR tool chain -- the `ocrmypdf` package plus
    its `tesseract`/`ghostscript` system binaries -- is present. False
    means the caller should fall back to rejecting the scanned PDF."""
    if shutil.which(_TESSERACT_BIN) is None or shutil.which(_GHOSTSCRIPT_BIN) is None:
        return False
    try:
        import ocrmypdf  # noqa: F401
    except ImportError:
        return False
    return True


def ocr_to_pdf(input_path: Path, output_path: Path) -> None:
    """Run ocrmypdf on `input_path`, writing the OCR'd result to
    `output_path`.

    `skip_text=True` only OCRs pages that don't already have a text
    layer, so a mixed born-digital/scanned document keeps its genuine
    text untouched. `optimize=0` skips ocrmypdf's image-recompression
    passes -- this pipeline doesn't need the smallest possible file, it
    needs the fastest turnaround, and the extractor only reads the text
    layer back out anyway.
    """
    import sys

    import ocrmypdf

    # ocrmypdf's logging/progress-bar setup (rich's `Live` display,
    # specifically) swaps sys.stdout/sys.stderr for its own proxy
    # objects and, in-process (not via its own CLI's normal
    # start-of-process/end-of-process lifecycle), doesn't reliably put
    # the originals back -- observed leaving sys.stderr pointed at a
    # StringIO after return, silently swallowing every later print()
    # (including this pipeline's own progress output and, worse, any
    # traceback). Save/restore around the call rather than trust it.
    orig_stdout, orig_stderr = sys.stdout, sys.stderr
    try:
        ocrmypdf.ocr(
            str(input_path),
            str(output_path),
            language=_LANGUAGE,
            skip_text=True,
            optimize=0,
            progress_bar=False,
            output_type="pdf",
        )
    finally:
        sys.stdout, sys.stderr = orig_stdout, orig_stderr


__all__ = ["available", "ocr_to_pdf"]
