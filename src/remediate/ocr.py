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

import concurrent.futures
import shutil
from pathlib import Path

_TESSERACT_BIN = "tesseract"
_GHOSTSCRIPT_BIN = "gs"

# English-only for v1 (per plan) -- additional languages are a matter of
# installing more `tesseract-ocr-<lang>` packages and widening this list
# later, not a code change.
_LANGUAGE = "eng"

# Per-page Tesseract timeout (ocrmypdf's own `tesseract_timeout`): a page
# that blows past this is replaced with an image-only page (no text
# layer) rather than hanging the whole run -- caught downstream by the
# zero-text-recovered check (R22) rather than treated as a hard error.
_DEFAULT_TESSERACT_PAGE_TIMEOUT = 180.0  # seconds
# Overall wall-clock budget for the whole ocrmypdf call, as a cheap
# safety net against a pathological document (thousands of pages, or a
# single page that hangs ocrmypdf itself rather than Tesseract) -- the
# per-page timeout above doesn't bound ocrmypdf's own orchestration.
_DEFAULT_OVERALL_TIMEOUT = 900.0  # seconds


class OcrTimeoutError(Exception):
    """Raised when OCR exceeds its overall wall-clock budget. The
    ocrmypdf call keeps running in its worker thread (it has no
    cooperative cancellation), but the caller gets a clean, timely
    error instead of hanging indefinitely."""


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


def ocr_to_pdf(
    input_path: Path,
    output_path: Path,
    *,
    tesseract_timeout: float = _DEFAULT_TESSERACT_PAGE_TIMEOUT,
    overall_timeout: float = _DEFAULT_OVERALL_TIMEOUT,
) -> None:
    """Run ocrmypdf on `input_path`, writing the OCR'd result to
    `output_path`.

    `skip_text=True` only OCRs pages that don't already have a text
    layer, so a mixed born-digital/scanned document keeps its genuine
    text untouched. `optimize=0` skips ocrmypdf's image-recompression
    passes -- this pipeline doesn't need the smallest possible file, it
    needs the fastest turnaround, and the extractor only reads the text
    layer back out anyway. `rotate_pages=True` uses Tesseract's
    orientation-detection (OSD) to auto-correct 90/180/270-degree
    rotated scans before transcribing them -- without it, a rotated
    page OCRs into garbage under the same generic OCR_APPLIED flag as a
    correctly-oriented one.

    `tesseract_timeout` bounds how long Tesseract spends on any single
    page (ocrmypdf's own knob); a page that exceeds it comes back as an
    image-only page with no text layer -- caught downstream as
    OCR_NO_TEXT_RECOVERED rather than hanging. `overall_timeout` is a
    cheap wall-clock safety net around the whole call, raising
    `OcrTimeoutError` if ocrmypdf itself doesn't return in time.
    """
    import sys

    import ocrmypdf

    def _run() -> None:
        # ocrmypdf's logging/progress-bar setup (rich's `Live` display,
        # specifically) swaps sys.stdout/sys.stderr for its own proxy
        # objects and, in-process (not via its own CLI's normal
        # start-of-process/end-of-process lifecycle), doesn't reliably
        # put the originals back -- observed leaving sys.stderr pointed
        # at a StringIO after return, silently swallowing every later
        # print() (including this pipeline's own progress output and,
        # worse, any traceback). Save/restore around the call rather
        # than trust it.
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
                rotate_pages=True,
                tesseract_timeout=tesseract_timeout,
            )
        finally:
            sys.stdout, sys.stderr = orig_stdout, orig_stderr

    # No `with` block: the context manager's shutdown(wait=True) would
    # block right through the timeout we just enforced, waiting for the
    # un-cancellable OCR thread to finish -- the caller must get the
    # timeout error promptly. On timeout, shut down without waiting; the
    # orphaned thread runs to harmless completion in the background (see
    # OcrTimeoutError).
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(_run)
    try:
        future.result(timeout=overall_timeout)
    except concurrent.futures.TimeoutError as exc:
        pool.shutdown(wait=False)
        raise OcrTimeoutError(
            f"OCR exceeded its overall time budget ({overall_timeout:.0f}s) "
            "and was aborted."
        ) from exc
    else:
        pool.shutdown(wait=True)


__all__ = ["available", "ocr_to_pdf", "OcrTimeoutError"]
