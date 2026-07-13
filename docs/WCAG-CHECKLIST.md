# WCAG 2.1 A/AA Checklist — Document Remediation Pipeline

Spec for the pipeline (extractor → IR → accessible HTML → WeasyPrint `pdf/ua-1` tagged PDF) and its compliance report. Every SC below is the full WCAG 2.1 Level A + AA list, sorted into APPLICABLE, N/A, or PARTIAL/HUMAN for a static, non-interactive rebuilt PDF (no forms, no audio/video, no scripting). Requirement IDs (R1…) are numbered for cross-reference from code, the compliance-report mapping, and QA sign-off.

**Test surface**: "the PDF" = the WeasyPrint `pdf/ua-1` output, inspectable via its tag tree (PyMuPDF or veraPDF) and `/Lang`, `/Alt`, `/StructTreeRoot`, `/MarkInfo` catalog entries. "the HTML" = the accessible-HTML intermediate, inspectable as a DOM. A test may reference either or both; the PDF is authoritative for conformance, the HTML is the earlier/cheaper checkpoint.

**Verdict types**:
- **AUTO** — pipeline guarantees this on every successful run; a failure is a pipeline bug.
- **AUTO+FLAG** — pipeline applies a deterministic best-effort fix and always adds a compliance-report entry so a human can review/override it.
- **HUMAN** — pipeline cannot determine correctness; it flags every instance in the compliance report for human resolution (document ships with the flag, not with a guess).

---

## 1. APPLICABLE

| ID | SC | Test (against pipeline output) | Verdict |
|----|----|----|----|
| R1 | 1.1.1 Non-text Content | Every `<img>` in the HTML has an `alt` attribute; every image `Figure`/`Artifact` structure element in the PDF has `/Alt` (or is tagged `/Artifact` if marked decorative). Alt text content itself is HUMAN (see PARTIAL section). | AUTO (presence) / see R1b below for content |
| R2 | 1.3.1 Info and Relationships | HTML uses semantic elements matching IR block types (`<h1>`–`<h6>` for headings at IR-detected level, `<table>`/`<th scope>`/`<td>` for tables, `<ul>`/`<ol>`/`<li>` for lists) — no block is emitted as styled `<div>`/`<span>` when the IR classified it as a semantic type; PDF `/StructTreeRoot` reflects the same tag types (`/H1`-`/H6`, `/Table`, `/TH`, `/L`). | AUTO |
| R3 | 1.3.2 Meaningful Sequence | HTML DOM order matches the IR's ordered block sequence (post reading-order heuristic); PDF tag tree traversal order matches DOM order (WeasyPrint preserves source order — verify no CSS reordering is used in the stylesheet). | AUTO |
| R4 | 1.3.4 Orientation | N/A rationale below — but included here because output is a document, not a device UI: no orientation lock is possible in a static PDF/HTML; page is always renderable in any viewer orientation. | AUTO (trivially satisfied — nothing to lock) |
| R5 | 1.4.1 Use of Color | Default stylesheet conveys no information (headings, links, table headers) by color alone — headings differ by size/weight/tag, links are underlined, `<th>` cells are bold/bordered not just colored. Verified by asserting the default stylesheet's CSS does not use `color` as the sole differentiator for any semantic class. | AUTO |
| R6 | 1.4.3 Contrast (Minimum) | Default stylesheet body/heading text vs. background computed contrast ratio ≥ 4.5:1 (≥3:1 for large text ≥18pt/14pt-bold). Computed once at build time against the fixed stylesheet (no user-supplied colors in v1), asserted in a stylesheet unit test. | AUTO |
| R7 | 1.4.4 Resize Text | HTML uses relative units (`em`/`rem`/`%`) for font-size and layout width in the default stylesheet, not fixed `px`, so browser/HTML zoom to 200% doesn't clip or truncate content. (PDF is fixed-layout by nature — see PDF-applicability note below.) | AUTO |
| R8 | 1.4.5 Images of Text | Extractor does not rasterize text content into images; all text blocks from source DOCX/PDF are emitted as real text in HTML/PDF, not as image screenshots of text. A whole-document scanned PDF is OCR'd (R22) so its text ships as real text, not an image; extracted images that are themselves text-as-image *within* an otherwise born-digital document (e.g. a letterhead graphic) are passed through as images with alt text obligations (R1), not converted to text. | AUTO (no new images-of-text introduced) / AUTO+FLAG (pre-existing ones flagged) |
| R9 | 1.4.10 Reflow | HTML applies with no horizontal scrolling / no 2D scrolling loss of content at 320px-equivalent zoom (relative units, no fixed-width containers). Applies to the HTML byproduct. **PDF is explicitly out of scope for reflow** — fixed-layout PDF pagination is an accepted WCAG PDF Techniques exception; the report notes this. | AUTO (HTML) / N/A (PDF, by PDF-Techniques convention) |
| R10 | 1.4.11 Non-text Contrast | UI-like graphical elements the pipeline itself renders (table borders, list markers, focus/visual dividers) meet 3:1 contrast against adjacent color in the default stylesheet. Source-document images are out of scope (pipeline doesn't alter their contrast). | AUTO (pipeline-rendered chrome only) |
| R11 | 1.4.12 Text Spacing | Default stylesheet does not use fixed heights/hard clipping that would break if a reader overrides line-height (1.5x), paragraph spacing (2x), letter-spacing (0.12x), word-spacing (0.16x) — no `overflow:hidden` on text containers, no fixed-height text boxes. Applies to HTML byproduct. | AUTO (HTML) |
| R12 | 2.4.2 Page Titled | HTML `<title>` is non-empty and set from IR document title (source metadata title, or filename fallback flagged in report); PDF `/Title` in the Info/XMP metadata matches. | AUTO+FLAG (filename fallback flagged) |
| R13 | 2.4.4 Link Purpose (In Context) | Every extracted `<a>` has non-empty link text; link text matching a generic-phrase blocklist ("click here", "here", "read more", "link", "more", a bare URL) is flagged, not silently passed. Deterministic detection only — see PARTIAL section for ambiguous cases. | AUTO+FLAG |
| R14 | 2.4.6 Headings and Labels | Every heading IR block, after heading-skip repair (no level jumps, e.g. H2→H4), has non-empty text content; table `<th>` cells (used as row/column labels) have non-empty text. | AUTO |
| R15 | 3.1.1 Language of Page | HTML `<html lang="...">` is set from IR document language: source metadata wins if present (`/Lang` for PDF, `docProps` core.xml `dc:language` for DOCX, used as-is, no flag). If absent, the pipeline runs deterministic content-based detection (py3langid) against the extracted text; a confident detection (enough text, confidence ≥ threshold) sets `lang` to the detected BCP-47 code and adds a `LANG_DETECTED` flag with the code + confidence for human confirmation. If the text is too short or the detector isn't confident, the pipeline falls back to `lang="en"` and adds a prominent `LANG_ASSUMED` human-review flag — it does **not** hard-reject the document; a rejection is worse UX for a single-user tool than a document that ships with a loud, unmissable flag. PDF catalog `/Lang` matches with a valid BCP-47 tag. | AUTO+FLAG (both the detected-fallback and the assumed-`en`-fallback cases) |
| R16 | 4.1.1 Parsing | N/A in WCAG 2.2 (deprecated as obsolete/always-true for modern parsers) but retained here for 2.1 completeness: generated HTML is valid (no duplicate `id` attributes, all tags properly nested/closed) — verified by running the output through an HTML validator in CI/tests. PDF structure tree has no orphaned/duplicate structure element IDs (verified by veraPDF if installed). | AUTO |
| R17 | 4.1.2 Name, Role, Value | Every structural/interactive-equivalent element (links, headings, table cells) has the tag-implied role and accessible name available from its text content or `/Alt`; no custom-widget states apply (static document, no forms/JS in v1 scope). | AUTO |

### R1 continued — 1.1.1 content quality (split entry)

| ID | SC | Test | Verdict |
|----|----|----|----|
| R1b | 1.1.1 Non-text Content (alt text *quality* / decorative determination) | Pipeline cannot judge whether generated/placeholder alt text is meaningful, or whether an image is truly decorative vs. informative. Every image gets a placeholder alt (`"[UNVERIFIED: image N — describe or mark decorative]"`) or a heuristic decorative flag (e.g. detected as a repeating header/footer graphic), and every one is listed in the compliance report for human confirmation before the document is considered fully conformant. | HUMAN |

---

## 2. N/A (static, non-interactive, single-language-target document — one-line rationale each)

| SC | Rationale |
|----|----|
| 1.2.1 Audio-only and Video-only (Prerecorded) | No audio/video content type in scope. |
| 1.2.2 Captions (Prerecorded) | No video content type in scope. |
| 1.2.3 Audio Description or Media Alternative | No video content type in scope. |
| 1.2.4 Captions (Live) | No live media in scope. |
| 1.2.5 Audio Description (Prerecorded) | No video content type in scope. |
| 1.3.3 Sensory Characteristics | No instructions authored by the pipeline that rely on shape/position/sound; source-document instructional text is passed through unmodified and is a source-authoring concern, not a pipeline output concern. |
| 1.4.2 Audio Control | No auto-playing audio; static document. |
| 1.4.13 Content on Hover or Focus | No hover/focus-triggered content; static document, no scripting. |
| 2.1.1 Keyboard | No custom interactive controls; document navigation uses the PDF/browser viewer's native keyboard support, outside pipeline scope. |
| 2.1.2 No Keyboard Trap | No focusable custom widgets introduced by the pipeline. |
| 2.1.4 Character Key Shortcuts | No keyboard shortcuts implemented by the pipeline output. |
| 2.2.1 Timing Adjustable | No time limits in a static document. |
| 2.2.2 Pause, Stop, Hide | No moving/auto-updating content. |
| 2.3.1 Three Flashes or Below Threshold | No animation/flashing content generated; source images passed through are not altered for flash and are out of pipeline control. |
| 2.5.1 Pointer Gestures | No gesture-based interaction; static document. |
| 2.5.2 Pointer Cancellation | No pointer-activated functions generated. |
| 2.5.3 Label in Name | No custom-labeled interactive controls generated (links use their own visible text as accessible name by construction, covered by R17). |
| 2.5.4 Motion Actuation | No motion-actuated functions. |
| 3.2.1 On Focus | No focus-triggered context changes; static document. |
| 3.2.2 On Input | No form inputs in v1 scope. |
| 3.2.3 Consistent Navigation | No repeated multi-page navigation UI is generated by the pipeline beyond standard PDF bookmarks (see R2/heading structure), which are structurally, not visually, consistent by construction. |
| 3.2.4 Consistent Identification | No repeated interactive-component set across the single generated document. |
| 3.3.1 Error Identification | No form inputs in v1 scope. |
| 3.3.2 Labels or Instructions | No form inputs in v1 scope. |
| 3.3.3 Error Suggestion | No form inputs in v1 scope. |
| 3.3.4 Error Prevention (Legal, Financial, Data) | No form inputs/transactions in v1 scope. |

**Explicitly out of scope, not "N/A"**: 3.1.2 Language of Parts (per-passage language tagging) is descoped for v1 per the implementation plan — document-level language only (R15); mixed-language source documents get a HUMAN flag rather than a per-passage `lang` attribute. Treat as a known gap, not a satisfied N/A.

---

## 3. PARTIAL/HUMAN (pipeline flags, human resolves)

| ID | SC | What the pipeline can/can't determine | Verdict |
|----|----|----|----|
| R1b | 1.1.1 Non-text Content | See above — alt text content/decorative judgment. | HUMAN |
| R13b | 2.4.4 Link Purpose (In Context) | Deterministic blocklist catches known-generic phrases (R13); it cannot verify that non-generic link text ("View the 2024 report") actually matches its target or makes sense out of context. Every link that *made it into the output* is listed in the report with its text + resolved URL for human spot-check; only blocklist matches are auto-flagged as *likely* failing. Links the extractor couldn't associate with any output text at all are a distinct case -- see R21, not this row. | AUTO+FLAG (blocklist) / HUMAN (semantic correctness, spot-check list only) |
| R18 | 1.3.1 Info and Relationships — table complexity | Simple grid tables get `<th scope>` auto-applied (R2, AUTO). Merged/nested/irregular tables (out of scope per plan) are flagged for manual remediation rather than auto-tagged, since incorrect `scope`/`headers` attributes are worse than none. PDF extraction additionally cross-checks each detected table's cell content against the page's raw text blocks: if a nearby element (e.g. a caption sitting just below the border) only partially overlaps the table and its text can't be reconciled with what `find_tables()` put in the cells, the table is flagged `TABLE_EXTRACTION_UNCERTAIN` (rather than shipping cells that may have absorbed foreign text) and the nearby text stays in the normal flow instead of disappearing. | AUTO+FLAG (simple) / HUMAN (complex or extraction-uncertain, explicitly flagged "not auto-fixed") |
| R19 | 2.4.6 Headings and Labels — heading level *correctness* | Pipeline repairs level *skips* (AUTO, R14) but cannot verify a font-size-inferred heading is semantically correct (e.g. a large pull-quote misclassified as a heading in PDF extraction). Every font-size-inferred (not source-tagged) heading gets a per-instance confidence score (from its size gap vs. the body-text cluster, how rare its size tier is, and length sanity); low-confidence headings each get their own needs-human-review flag naming the specific heading, while high-confidence ones are rolled into a single document-level summary flag (count + confidence range) rather than one flag per heading. | AUTO+FLAG |
| R20 | 1.3.1 / 4.1.2 — reading order on multi-column or complex-layout source PDFs | Single-column and basic two-column detection is heuristic (per plan, task 8); any page where column/order confidence is low (3+ horizontal clusters, or a bimodal 2-way split that doesn't look like a genuine page-wide two-column layout) is flagged rather than silently emitted in a possibly-wrong order. | AUTO+FLAG |
| R21 | 2.4.4 / 1.3.2 — source links that couldn't be associated with any output text | A source hyperlink whose region doesn't overlap any extracted text or image run is dropped rather than attached with invented link text; every dropped link is listed in the report (with its target URL) so a human can decide whether to add it back manually. Distinct from R13b (which covers link text whose *wording* needs a spot-check) -- here the link's very presence in the output is what's uncertain. | AUTO+FLAG |
| R22 | 1.1.1 Non-text Content — OCR of scanned/image-only PDFs | A PDF detected as scanned/image-only is run through OCR (English, via ocrmypdf/tesseract) rather than rejected, so its text ships as real, extractable text instead of an inaccessible page image. The pipeline cannot verify OCR transcription accuracy, so every OCR'd document gets a document-level `OCR_APPLIED` flag naming this. Separately, each page's full-page scan-raster image is excluded from the output (it's a processing artifact, not content) with a single document-level `SCAN_IMAGES_EXCLUDED` info flag noting that any figures/photos embedded *within* the scan couldn't be extracted as discrete images. OCR tooling is a normal dependency of this deployment; if it's genuinely absent at runtime, the pipeline falls back to the pre-OCR rejection behavior rather than silently skipping OCR. | AUTO+FLAG (OCR applied, transcription unverifiable) / INFO (scan-image exclusion) |

---

## 4. PDF/UA-1 relationship (one paragraph)

PDF/UA-1 (ISO 14289-1) is the *tagging mechanism* the pipeline uses to produce a machine-verifiable structured PDF (via WeasyPrint's `pdf/ua-1` output variant); WCAG 2.1 AA is the *target standard* this checklist verifies against. They overlap heavily (both require tag structure, alt text, language, reading order) but are not identical — PDF/UA-1 conformance (checkable with veraPDF, task 2/9 milestones) is necessary evidence for several SCs above (R2, R3, R15, R17) but does not by itself prove SCs that PDF/UA doesn't cover (contrast R6, resize/reflow R7/R9, link-purpose semantics R13b). Passing veraPDF is a strong AUTO signal for the structural SCs; it is not a substitute for this full checklist.
