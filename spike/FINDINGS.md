# Task 2 — PDF/UA Feasibility Spike: Findings

**Script:** `spike/pdfua_spike.py` — run with `python spike/pdfua_spike.py`
(from an environment with the project deps installed, e.g. `.venv`).

**Environment:** WeasyPrint 69.0, PyMuPDF (fitz) 1.28.0, Python 3.11.15,
Linux, system pango/cairo/gdk-pixbuf present (no apt-get needed).

## What was built

A single hand-crafted HTML document (`build_html()` in the spike script)
with: `<title>`, `<html lang="en">`, an H1 -> H2 heading hierarchy, a
paragraph, a `<table>` with `<caption>`, `<thead>`/`<th scope="col">`, an
embedded image (`<img>` with a base64 PNG generated in-memory via Pillow,
plus a descriptive `alt`), and a link with descriptive anchor text.
Rendered via `HTML(string=...).write_pdf(target=..., pdf_variant='pdf/ua-1')`
-- confirmed API for WeasyPrint 69.0 by reading `weasyprint/pdf/pdfua.py`
(`VARIANTS = {'pdf/ua-1': ..., 'pdf/ua-2': ...}`).

## Evidence dump (via PyMuPDF raw xref inspection)

```
StructTreeRoot present:      True
Marked/MarkInfo present:     True   (/MarkInfo << /Marked true >>)
Lang in catalog:             True   (/Lang (en))
DisplayDocTitle true:        True   (/ViewerPreferences << /DisplayDocTitle true >>)
ViewerPreferences present:   True
StructElem /S tags found:    Caption, Document, Figure, H1, H2, Link, NonStruct,
                              P, Span, TBody, TD, TH, THead, TR, Table
Alt text on Figure elem:     "A small solid red square used as a spike test image"
Document title (Info/XMP):   "PDF/UA Spike Document"
```

Full catalog object:

```
<<
  /Type /Catalog
  /Pages 1 0 R
  /Outlines 13 0 R
  /Lang (en)
  /StructTreeRoot 32 0 R
  /ViewerPreferences << /DisplayDocTitle true >>
  /MarkInfo << /Marked true >>
  /Metadata 86 0 R
>>
```

## What's correctly tagged

- **Structure tree exists and is real**, not just a flat tag list: 51
  `StructElem` objects with a proper parent/kid hierarchy (`/P`, `/K`)
  mirroring the HTML DOM (Document -> H1/P/H2/Table/Figure/Link, Table ->
  THead/TBody -> TR -> TH/TD).
- **Document-level metadata required by PDF/UA-1** is present: `/Lang`,
  `/MarkInfo /Marked true`, `/ViewerPreferences /DisplayDocTitle true`,
  document `/Title` in both the Info dict and XMP metadata.
- **Heading hierarchy** (H1, H2) is tagged as real `StructElem`s, not just
  styled text -- a screen reader can navigate by heading.
- **Table header association is correct, and uses the *better* PDF
  mechanism, not literal `/Scope`.** WeasyPrint does not copy the HTML
  `scope` attribute onto the tag as a `/Scope` key (PDF tagging has no such
  key -- that's an HTML/ARIA-only concept). Instead it implements the actual
  PDF/UA-recommended `Headers`/`ID` association algorithm
  (`weasyprint/pdf/tags.py:280-315`): each `TH` gets a unique `/ID`, and
  each `TD` gets `/A << /O /Table /Headers [ (that TH's ID) ] >>` pointing
  at its column header. Verified directly in the object dump -- every `TD`
  in the spike table correctly references its `TH`'s ID. This is the
  correct, spec-preferred mechanism, so **table headers are tagged
  correctly**, contrary to a first-glance assumption that "no literal
  `/Scope` string" would mean a gap.
- **Image alt text**: the `Figure` `StructElem` carries `/Alt (A small
  solid red square used as a spike test image)` -- verified directly, not
  just present as free text somewhere in the file.
- **Link** is tagged as its own `StructElem` (`/S /Link`) rather than
  collapsing into plain text.

## What's missing or weak

- **Row-header tables (`scope="row"`), `rowspan`/`colspan`, `rowgroup`/
  `colgroup` scope values are explicitly `# TODO` in WeasyPrint's own
  source** (`tags.py:294`, `:301`). Simple column-header tables (the common
  case for this project's DOCX/PDF source tables) work; anything with
  merged cells or row headers will not get correct `Headers` associations
  and needs to be flagged for manual review, not trusted blindly. This
  matches the plan's existing out-of-scope call on complex/merged tables --
  no new risk, just confirms that call was correct.
- **veraPDF (Java CLI) could not be evaluated.** Java 21 is installed and
  functional. Attempting to fetch veraPDF's release from `github.com`
  through the environment's egress proxy returned HTTP 403 -- an
  organization policy denial (confirmed via
  `$HTTPS_PROXY/__agentproxy/status` and its README: 403/407 are policy
  denials, not to be retried or worked around). Per the plan's own
  instruction ("if Java or the download isn't available, note it and move
  on -- don't burn time"), this was not pursued further. **This means the
  spike's structure-tree evidence is verified by direct PDF object
  inspection only, not cross-checked against an independent PDF/UA
  validator.** Recommend re-attempting veraPDF in an environment with open
  internet access before the final task-11 acceptance pass, or downloading
  it out-of-band and adding it to the environment manually.
- No accessibility check was done on WeasyPrint's *reading order* for
  multi-column layouts -- out of scope for this spike (single-column
  hand-crafted doc), relevant later for the PDF extractor's two-column
  detection (task 8).

## VERDICT

**WeasyPrint's `pdf/ua-1` variant is adequate as the tagged-PDF backend.**
It produces a genuine, correctly nested structure tree with the metadata
PDF/UA-1 requires (`Lang`, `MarkInfo/Marked`, `DisplayDocTitle`, `Title`),
correct heading tags, correct image alt-text attachment, and correct
(better-than-naively-expected) table header association for the simple
case this project targets. The one confirmed gap -- complex table headers
(`scope="row"`, spans, groups) -- is already out of scope per the plan's own
"complex/merged tables... flagged for manual remediation" call, so it does
not change the verdict. veraPDF cross-validation is outstanding due to a
sandboxed network policy, not due to any WeasyPrint deficiency; flagged as
a follow-up rather than a blocker.

**Proceed to task 3.**
