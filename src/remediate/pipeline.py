"""End-to-end DOCX -> tagged-PDF pipeline (plan task 7).

`remediate_file` is a plain function so both the CLI (`__main__.py`) and
the future web app (task 10) can call it directly -- no CLI-specific
state, just a path in, an output directory, and an optional progress
callback.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from weasyprint import HTML

from .extractors.docx import DocxExtractionError, extract_docx
from .html_gen import generate_html
from .report import build_report, render_report_html

ProgressCallback = Callable[[str, float], None]

_SUPPORTED_EXTENSIONS = {".docx"}


class UnsupportedFileError(Exception):
    """Raised for input files this pipeline doesn't (yet) support."""


@dataclass
class PipelineResult:
    pdf_path: Path
    html_path: Path
    report_json_path: Path
    report_html_path: Path


def remediate_file(
    input_path: str | Path,
    outdir: str | Path,
    progress_callback: ProgressCallback | None = None,
) -> PipelineResult:
    """Run the full extractor -> HTML -> PDF/UA -> report pipeline.

    Raises DocxExtractionError / UnsupportedFileError on rejected input
    (encrypted, corrupt, unsupported format) -- callers should catch
    these and surface a clean message rather than a traceback.
    """
    input_path = Path(input_path)
    outdir = Path(outdir)

    def report_progress(stage: str, pct: float) -> None:
        if progress_callback is not None:
            progress_callback(stage, pct)

    suffix = input_path.suffix.lower()
    if suffix not in _SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(
            f"Unsupported file type '{suffix or input_path.name}'. "
            f"Supported: {', '.join(sorted(_SUPPORTED_EXTENSIONS))}."
        )

    report_progress("extracting", 0.0)
    document = extract_docx(input_path)

    # Only create the output directory once we know the input is valid --
    # a rejected/unsupported input shouldn't leave an empty outdir behind.
    outdir.mkdir(parents=True, exist_ok=True)

    report_progress("generating_html", 0.35)
    html_result = generate_html(document)

    basename = input_path.stem
    html_path = outdir / f"{basename}.html"
    html_path.write_text(html_result.html, encoding="utf-8")

    report_progress("rendering_pdf", 0.6)
    pdf_path = outdir / f"{basename}.pdf"
    HTML(string=html_result.html, base_url=str(input_path.parent)).write_pdf(
        target=str(pdf_path), pdf_variant="pdf/ua-1"
    )

    report_progress("building_report", 0.9)
    compliance_report = build_report(document, html_result.autofixes)
    report_json_path = outdir / "report.json"
    report_json_path.write_text(compliance_report.to_json(), encoding="utf-8")
    report_html_path = outdir / "report.html"
    report_html_path.write_text(render_report_html(compliance_report), encoding="utf-8")

    report_progress("done", 1.0)

    return PipelineResult(
        pdf_path=pdf_path,
        html_path=html_path,
        report_json_path=report_json_path,
        report_html_path=report_html_path,
    )


__all__ = [
    "remediate_file",
    "PipelineResult",
    "ProgressCallback",
    "UnsupportedFileError",
    "DocxExtractionError",
]
