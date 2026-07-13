# bug-free-engine — ADA document remediation app

Takes a PDF or DOCX document and rebuilds it as a WCAG 2.1 AA tagged
PDF/UA-1, plus an accessible HTML version and a compliance report. The
pipeline is deterministic heuristics only — no AI/LLM. Judgment calls it
can't make safely (alt text content, decorative-vs-meaningful images,
whether a font-size-inferred heading is really a heading) are not
guessed: they're written into the compliance report as items for a human
to resolve. **The report's "needs human review" list is a normal, expected
part of every run, not a failure state.**

## Limitations (read before using)

- **Output is a rebuild, not a repair.** The tagged PDF uses a clean,
  contrast-compliant default stylesheet — it does not preserve the
  source document's fonts, colors, or branding.
- **Scanned or image-only PDFs are rejected**, not processed. There's no
  OCR step; a PDF with negligible extractable text fails with a clear
  error instead of producing an empty or garbled result.
- **Encrypted/password-protected PDFs are rejected** with a clear error.
  Remove the password first.
- **Complex tables and multi-column layouts are flagged, not fixed.**
  Merged/nested/irregular tables and magazine-style multi-column pages
  get a human-review flag (`TABLE_EXTRACTION_UNCERTAIN`, low reading-order
  confidence) rather than an auto-applied guess that might be wrong.
- **Single-user, local tool.** No auth, no multi-tenant job isolation, no
  batch upload. Don't expose this to the public internet as-is.
- Per-passage language tagging is out of scope — language is detected/set
  once for the whole document; mixed-language source documents get a
  flag instead of per-passage `lang` attributes.

See `docs/WCAG-CHECKLIST.md` for the full list of what's automated vs.
flagged, and `spike/FINDINGS.md` for the PDF/UA-1 output feasibility
evidence.

## Setup

Requires Python 3.11. Tested on Linux (the target platform per
`CLAUDE.md`) — if you're on macOS or Windows, the venv/pip steps below
work the same but WeasyPrint's system library names and install
mechanism differ; see WeasyPrint's own install docs.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

WeasyPrint needs system pango/cairo/gdk-pixbuf. On Debian/Ubuntu, check
first with `ldconfig -p | grep pango`, then if missing:

```bash
apt-get install libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf2.0-0
```

## Usage

### Web app

```bash
uvicorn remediate.app:app --reload
```

Open the app in a browser, upload a `.pdf` or `.docx`, and watch the
progress indicator (extracting → generating HTML → rendering PDF →
building report). When the job finishes, download links appear for:

- the tagged PDF/UA-1
- the accessible HTML
- the compliance report (HTML, human-readable)
- the compliance report (JSON, machine-readable)

Jobs run one at a time (single background worker) and are stored under
`jobs/<uuid>/` at the repo root (gitignored) — this survives a server
restart, so a completed job's downloads still work after `uvicorn`
restarts. Max upload size is 500MB.

### CLI

```bash
python -m remediate INPUT.pdf -o OUTDIR
# or
python -m remediate INPUT.docx -o OUTDIR
```

Writes four files into `OUTDIR`:

- `INPUT.pdf` — the tagged PDF/UA-1 output
- `INPUT.html` — the accessible HTML
- `report.json` — compliance report, machine-readable
- `report.html` — compliance report, human-readable

Prints progress to stderr and a summary of the four output paths to
stdout on success. Exits non-zero with an error message (no traceback)
if the input is unsupported, encrypted, or detected as scanned/image-only.

## Compliance workflow

Every WCAG 2.1 A/AA success criterion the pipeline can affect is
enumerated in `docs/WCAG-CHECKLIST.md` with a numbered requirement ID
(R1, R2, ...) and one of three verdicts:

- **AUTO** — the pipeline guarantees this on every successful run.
- **AUTO+FLAG** — the pipeline applies a deterministic best-effort fix
  *and* adds a compliance-report entry so a human can review or override
  it (e.g. a generic link-text match, a filename-fallback title).
- **HUMAN** — the pipeline can't determine correctness on its own; it
  flags every instance for human resolution instead of guessing (e.g.
  alt-text quality, decorative-vs-meaningful image judgment).

A document that ships with HUMAN-flagged items in its report is working
as intended — check the report before treating the output as fully
conformant.

## Architecture

`extractor (DOCX/PDF) → internal representation (IR) → accessible HTML →
WeasyPrint pdf/ua-1 → compliance report`. See `spike/FINDINGS.md` for the
evidence that WeasyPrint's `pdf/ua-1` output produces a real, correctly
nested PDF structure tree (verified by direct PDF object inspection) —
that finding is why this pipeline rebuilds through HTML rather than
patching the source PDF in place.

## Test

```bash
pytest
```

The large-document memory test (500+ page synthetic PDF) is marked
`slow` and runs as part of the default `pytest` invocation. To skip it
for a quick local run:

```bash
pytest -m "not slow"
```
