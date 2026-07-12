"""CLI entry point: `python -m remediate INPUT.docx -o OUTDIR`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .extractors.docx import DocxExtractionError
from .pipeline import UnsupportedFileError, remediate_file


def _print_progress(stage: str, pct: float) -> None:
    print(f"[{pct * 100:5.1f}%] {stage}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="remediate",
        description=(
            "Remediate a DOCX document into a WCAG 2.1 AA tagged PDF/UA-1, "
            "an accessible HTML byproduct, and a compliance report."
        ),
    )
    parser.add_argument("input", help="Path to the input .docx file")
    parser.add_argument(
        "-o", "--outdir", required=True, help="Output directory (created if missing)"
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 1

    try:
        result = remediate_file(input_path, args.outdir, progress_callback=_print_progress)
    except (DocxExtractionError, UnsupportedFileError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Done. Wrote:")
    print(f"  PDF:    {result.pdf_path}")
    print(f"  HTML:   {result.html_path}")
    print(f"  Report: {result.report_json_path}")
    print(f"          {result.report_html_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
