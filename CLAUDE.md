# bug-free-engine — ADA document remediation app

Ingests PDF/DOCX documents and produces a WCAG 2.1 AA-compliant tagged
PDF (via an internal IR -> accessible HTML -> WeasyPrint PDF/UA-1
pipeline), plus the accessible HTML and a compliance report. Deterministic
heuristics only, no AI/LLM in the pipeline -- ambiguous judgment calls
(alt text, decorative-vs-meaningful images, heading structure) are flagged
for human review rather than guessed.

Full plan: `spike/FINDINGS.md` documents the PDF/UA feasibility spike;
`docs/` (once written) holds the WCAG checklist the pipeline is verified
against.

## Target platform

Linux server (backend) + any modern browser (frontend). No macOS/Windows
support planned; do not add OS-specific shell-outs.

## Stack

Python 3.11, FastAPI + Uvicorn, WeasyPrint, PyMuPDF, mammoth, python-docx,
pytest. Single-user local tool -- no auth, no queue/broker, background
jobs via a plain thread/process pool.

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

WeasyPrint needs system pango/cairo/gdk-pixbuf (`apt-get install
libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf2.0-0` on
Debian/Ubuntu if missing -- check first with `ldconfig -p | grep pango`).

## Run

```bash
# Feasibility spike (task 2) -- writes spike/output.pdf, prints structure evidence
python spike/pdfua_spike.py

# CLI pipeline entry point (added in later tasks)
python -m remediate <file>

# Web app (added in later tasks)
uvicorn remediate.app:app --reload
```

## Test

```bash
pytest
```
