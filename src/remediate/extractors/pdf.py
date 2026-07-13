"""PDF -> IR extractor (plan task 8).

PDFs carry none of the semantic structure DOCX gets almost for free from
mammoth -- there's no reliable "this is a heading" or "this is a list"
tag, just positioned text runs, drawn lines, and embedded images. Every
piece of structure below is a deterministic heuristic inferred from
layout (font size/weight clustering for headings, block position for
reading order, PyMuPDF's own line-grid detection for tables). Per the
plan, this is the highest-risk extractor in the pipeline: uncertain
structure is flagged for human review, never guessed silently.

Extraction is page-by-page and lazy (task 9): only one page's
`get_text("dict")` result is held at a time, dropped once its blocks are
converted to IR, so multi-hundred-page documents don't balloon memory.
Embedded image bytes are extracted once per unique xref and cached, since
the same logo/watermark image is often reused across many pages.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Callable

import fitz  # PyMuPDF

# PyMuPDF prints a one-time stdout hint recommending its optional
# pymupdf_layout package the first time find_tables()/layout analysis
# runs. Noise in a CLI pipeline's stdout, not an error -- use the
# library's own documented opt-out rather than filtering stdout after
# the fact.
fitz.no_recommend_layout()

from .common import determine_language
from ..ir import (
    Document,
    Flag,
    Heading,
    Image,
    Link,
    ListBlock,
    ListItem,
    Paragraph,
    Table,
    TableCell,
    TableRow,
    TextRun,
)

ProgressCallback = Callable[[str, float], None]


class PdfExtractionError(Exception):
    """Raised when a PDF can't or won't be processed: encrypted/password
    protected, or detected as a scanned/image-only PDF (OCR is out of
    scope -- see the plan's "out of scope" list). The caller (pipeline/
    CLI) is expected to turn this into a clean exit, not a traceback."""


# PyMuPDF span "flags" bitfield: bit 0 = superscript, bit 1 = italic,
# bit 2 = serifed, bit 3 = monospaced, bit 4 = bold.
_ITALIC_FLAG_BIT = 1 << 1
_BOLD_FLAG_BIT = 1 << 4

# How many pages to sample for the (cheap but not free) heading-size and
# scanned-document checks -- sampling instead of scanning all pages keeps
# rejection/setup fast even on a multi-thousand-page document.
_HEADING_SAMPLE_PAGES = 25
_SCAN_SAMPLE_PAGES = 10
_SCAN_CHARS_PER_PAGE_THRESHOLD = 25

_MAX_HEADING_LEVELS = 4
# A cluster of text only counts as a heading candidate if its font size
# is meaningfully larger than the detected body-text size -- a few
# rounding-noise points bigger isn't a heading.
_HEADING_SIZE_MARGIN = 1.08
_HEADING_LOW_CONFIDENCE_CHARS = 120  # unusually long for a real heading

# Per-heading confidence (R19): a blend of how far the heading's font
# size stands out from the body-text cluster, how well-represented that
# size tier is across the sampled document (a one-off tier is more
# likely a misclassified pull-quote than a real heading style), and
# whether the text length is heading-shaped. Below the threshold, the
# heading gets its own needs-human-review flag naming it specifically;
# at or above it, the heading is only counted in the document-level
# HEADINGS_INFERRED summary.
_HEADING_LOW_CONFIDENCE_THRESHOLD = 0.5
# Size-gap score reaches 1.0 once the heading's size exceeds the body
# size by this much beyond the minimum heading-candidate margin.
_HEADING_SIZE_GAP_FULL_CONFIDENCE_DELTA = 0.5
# Tier-rarity score reaches 1.0 once this size tier accounts for at
# least this many sampled characters somewhere in the document.
_HEADING_TIER_RARITY_FULL_CONFIDENCE_CHARS = 20

_TINY_IMAGE_PX = 24
_REPEATED_IMAGE_PAGE_FRACTION = 0.5
_REPEATED_IMAGE_MIN_PAGES = 4
# A "big image" fills most of a page -- used only for scanned-PDF
# detection (a full-page scan raster), not for the per-image decorative
# heuristic above.
_BIG_IMAGE_PAGE_AREA_FRACTION = 0.5

_BULLET_RE = re.compile(r"^[•‣◦⁃∙·\-–]\s+")
_NUMBERED_RE = re.compile(r"^(\d{1,3}|[a-zA-Z])[.\)]\s+")

_WORD_TITLE_RE = re.compile(r"^Microsoft Word - (.+?)(\.docx?|\.rtf)?$", re.IGNORECASE)

_EXT_TO_MIME = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "jp2": "image/jp2",
    "jpx": "image/jp2",
    "webp": "image/webp",
}


def extract_pdf(path: str | Path, progress_callback: ProgressCallback | None = None) -> Document:
    """Extract a .pdf file into the internal Document representation.

    Raises PdfExtractionError for encrypted or scanned/image-only input
    -- the caller is expected to turn that into a clean exit, not a
    traceback.
    """
    path = Path(path)

    def report(stage: str, pct: float) -> None:
        if progress_callback is not None:
            progress_callback(stage, pct)

    try:
        pdf = fitz.open(str(path))
    except Exception as exc:
        raise PdfExtractionError(f"Cannot open '{path.name}': {exc}") from exc

    if pdf.needs_pass:
        pdf.close()
        raise PdfExtractionError(
            f"Cannot open '{path.name}': this PDF is password-protected. "
            "Remove the password and try again -- encrypted PDFs are out "
            "of scope for this tool."
        )

    page_count = pdf.page_count
    if page_count == 0:
        pdf.close()
        raise PdfExtractionError(f"'{path.name}' has no pages.")

    _reject_if_scanned(pdf, path)

    doc_flags: list[Flag] = []

    body_size, size_to_level, size_char_counts = _infer_heading_sizes(pdf)

    image_page_counts = _prescan_image_page_counts(pdf)
    image_bytes_cache: dict[int, tuple[bytes, str | None]] = {}

    blocks: list = []
    lang_text_parts: list[str] = []
    high_confidence_headings: list[float] = []

    for page_num in range(page_count):
        page = pdf[page_num]
        page_items, page_flags, page_high_confidence = _process_page(
            pdf,
            page,
            page_num,
            page_count,
            body_size,
            size_to_level,
            size_char_counts,
            image_page_counts,
            image_bytes_cache,
        )
        blocks.extend(page_items)
        doc_flags.extend(page_flags)
        high_confidence_headings.extend(page_high_confidence)
        for item in page_items:
            text = _block_plain_text(item)
            if text:
                lang_text_parts.append(text)
        report("extracting", (page_num + 1) / page_count)

    pdf_lang = _read_catalog_lang(pdf)

    metadata_title = (pdf.metadata or {}).get("title") or ""
    pdf.close()

    if any(isinstance(b, Heading) for b in blocks):
        if high_confidence_headings:
            range_msg = (
                f" of the {len(high_confidence_headings)} not individually "
                f"flagged, confidence ranged {min(high_confidence_headings):.2f}"
                f"-{max(high_confidence_headings):.2f}."
            )
        else:
            range_msg = " -- every inferred heading was low-confidence and individually flagged above."
        doc_flags.append(
            Flag(
                code="HEADINGS_INFERRED",
                wcag_sc="1.3.1",
                message=(
                    "This PDF has no semantic heading tags; heading levels "
                    "were inferred from font size/weight clustering. Review "
                    "the inferred heading structure for correctness"
                    f"{range_msg}"
                ),
            )
        )

    lang, lang_flag = determine_language(pdf_lang, " ".join(lang_text_parts), "the source PDF")
    if lang_flag is not None:
        doc_flags.append(lang_flag)

    title, title_flag = _determine_title(metadata_title, blocks, path)
    if title_flag is not None:
        doc_flags.append(title_flag)

    return Document(
        title=title,
        lang=lang,
        blocks=blocks,
        source_format="pdf",
        flags=doc_flags,
    )


# ---------------------------------------------------------------------------
# Rejection gate.
# ---------------------------------------------------------------------------


def _sample_page_indices(page_count: int, sample_size: int) -> list[int]:
    if page_count <= sample_size:
        return list(range(page_count))
    if sample_size <= 1:
        return [0]
    step = (page_count - 1) / (sample_size - 1)
    return sorted({round(i * step) for i in range(sample_size)})


def _reject_if_scanned(pdf: fitz.Document, path: Path) -> None:
    sample = _sample_page_indices(pdf.page_count, _SCAN_SAMPLE_PAGES)
    total_chars = 0
    pages_with_big_image = 0
    for idx in sample:
        page = pdf[idx]
        total_chars += len(page.get_text("text").strip())
        page_area = page.rect.width * page.rect.height
        if page_area <= 0:
            continue
        for info in page.get_images(full=True):
            xref = info[0]
            big = any(
                rect.get_area() >= _BIG_IMAGE_PAGE_AREA_FRACTION * page_area
                for rect in page.get_image_rects(xref)
            )
            if big:
                pages_with_big_image += 1
                break

    avg_chars = total_chars / len(sample) if sample else 0
    if avg_chars < _SCAN_CHARS_PER_PAGE_THRESHOLD and pages_with_big_image >= max(1, len(sample) // 2):
        raise PdfExtractionError(
            f"Cannot process '{path.name}': this looks like a scanned or "
            "image-only PDF (sampled pages are dominated by full-page "
            "images with negligible extractable text). OCR is out of "
            "scope for this tool -- run it through an OCR step first if "
            "you need this content remediated."
        )


# ---------------------------------------------------------------------------
# Heading-size inference (sampled once, up front).
# ---------------------------------------------------------------------------


def _infer_heading_sizes(pdf: fitz.Document) -> tuple[float, dict[float, int], Counter]:
    """Cluster (rounded) font sizes across a sample of pages by total
    character count. The dominant cluster is the body-text baseline;
    clusters meaningfully larger than that, in descending size order, map
    to heading levels 1..N (capped). Conservative by construction: a
    size that doesn't clearly stand out from body text is never promoted
    to a heading.

    The raw `size_char_counts` is also returned for per-heading
    confidence scoring (R19): a size tier backed by only a handful of
    sampled characters anywhere in the document is a weaker signal --
    more likely a one-off pull-quote/emphasis than a real, repeated
    heading style -- than a tier that recurs substantially."""
    size_char_counts: Counter[float] = Counter()
    for idx in _sample_page_indices(pdf.page_count, _HEADING_SAMPLE_PAGES):
        page = pdf[idx]
        page_dict = page.get_text("dict")
        for block in page_dict["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    stripped = span["text"].strip()
                    if not stripped:
                        continue
                    size_char_counts[_round_size(span["size"])] += len(stripped)
        del page_dict

    if not size_char_counts:
        return 12.0, {}, Counter()

    body_size = size_char_counts.most_common(1)[0][0]
    candidate_sizes = sorted(
        (s for s in size_char_counts if s > body_size * _HEADING_SIZE_MARGIN),
        reverse=True,
    )
    size_to_level = {size: level for level, size in enumerate(candidate_sizes[:_MAX_HEADING_LEVELS], start=1)}
    return body_size, size_to_level, size_char_counts


def _round_size(size: float) -> float:
    return round(size * 2) / 2


# ---------------------------------------------------------------------------
# Image xref bookkeeping (task 9: extract each unique image once).
# ---------------------------------------------------------------------------


def _prescan_image_page_counts(pdf: fitz.Document) -> Counter:
    """How many distinct pages each image xref appears on, for the
    repeated-logo/watermark decorative heuristic. A cheap pass -- just
    the image xref list per page, not the full text/layout dict."""
    counts: Counter = Counter()
    for page in pdf:
        seen_this_page = set()
        for info in page.get_images(full=True):
            xref = info[0]
            if xref not in seen_this_page:
                counts[xref] += 1
                seen_this_page.add(xref)
    return counts


# ---------------------------------------------------------------------------
# Per-page processing.
# ---------------------------------------------------------------------------


def _process_page(
    pdf: fitz.Document,
    page: fitz.Page,
    page_num: int,
    page_count: int,
    body_size: float,
    size_to_level: dict[float, int],
    size_char_counts: Counter,
    image_page_counts: Counter,
    image_bytes_cache: dict[int, tuple[bytes, str | None]],
) -> tuple[list, list[Flag], list[float]]:
    page_flags: list[Flag] = []
    high_confidence_headings: list[float] = []
    page_dict = page.get_text("dict")
    tables_result = page.find_tables()
    tables = list(tables_result.tables)
    raw_links = page.get_links()
    link_pool = [
        {"rect": fitz.Rect(link["from"]), "uri": link["uri"], "matched": False}
        for link in raw_links
        if link.get("uri")
    ]

    table_rects = [fitz.Rect(t.bbox) for t in tables]
    raw_text_blocks = [b for b in page_dict["blocks"] if b["type"] == 0]
    text_blocks, table_inside_blocks = _partition_table_blocks(raw_text_blocks, table_rects)
    del page_dict

    items: list[dict] = []
    for block in text_blocks:
        items.append({"kind": "text", "bbox": block["bbox"], "data": block})
    for table, inside_blocks in zip(tables, table_inside_blocks):
        items.append({"kind": "table", "bbox": table.bbox, "data": table, "inside_blocks": inside_blocks})

    placed_images = _placed_images_on_page(page, image_page_counts)
    for img in placed_images:
        items.append({"kind": "image", "bbox": img["rect"], "data": img})

    ordered_items, order_uncertain = _order_items(items, page.rect.width)
    if order_uncertain:
        page_flags.append(
            Flag(
                code="READING_ORDER_UNCERTAIN",
                wcag_sc="1.3.2",
                message=(
                    f"Page {page_num + 1} has a layout this heuristic isn't "
                    "confident about (either 3+ distinct horizontal text "
                    "positions, or an ambiguous 2-way split that didn't "
                    "look like a genuine page-wide two-column layout); "
                    "content was emitted in top-to-bottom order without "
                    "column reconstruction. Verify reading order manually."
                ),
                location=f"page {page_num + 1}",
            )
        )

    built_items: list = []
    for item in ordered_items:
        if item["kind"] == "text":
            new_items = _build_text_item(item["data"], body_size, size_to_level, size_char_counts, link_pool, page_num)
            for new_item in new_items:
                if isinstance(new_item, Heading) and not any(f.code == "HEADING_LOW_CONFIDENCE" for f in new_item.flags):
                    high_confidence_headings.append(new_item._confidence)
            built_items.extend(new_items)
        elif item["kind"] == "table":
            built_items.append(_build_table(item["data"], item["inside_blocks"], page_num))
        else:
            image = _build_image(
                pdf,
                item["data"],
                image_page_counts,
                page_count,
                image_bytes_cache,
                link_pool,
            )
            built_items.append(image)

    for link in link_pool:
        if not link["matched"]:
            page_flags.append(
                Flag(
                    code="LINK_UNASSOCIATED",
                    wcag_sc="2.4.4",
                    message=(
                        f"A hyperlink to '{link['uri']}' on page "
                        f"{page_num + 1} could not be confidently "
                        "associated with any extracted text or image, so "
                        "it was not attached to the document content "
                        "(inventing link text was avoided). Add it "
                        "manually if needed."
                    ),
                    location=f"page {page_num + 1}",
                )
            )

    final_items = _group_lists(built_items)
    return final_items, page_flags, high_confidence_headings


# A block only counts as genuinely "part of" a detected table if
# (near-)all of its own area falls inside the table's bbox. Anything
# less -- a block that straddles the border, like a caption sitting a
# couple points below the last row -- is left in the normal text flow
# rather than silently swallowed, even though find_tables()'s own cell
# extraction may (wrongly) have pulled some of that text into a cell;
# see _cells_reconcile_with_inside_blocks for the corresponding check on
# the extracted cell content itself.
_TABLE_INSIDE_OVERLAP_RATIO = 0.95


def _partition_table_blocks(
    blocks: list[dict], table_rects: list[fitz.Rect]
) -> tuple[list[dict], list[list[dict]]]:
    """Split raw text blocks into (a) those that stay in the normal text
    flow and (b) per-table lists of blocks that are genuinely inside
    each table's bbox, for the cell-content reconciliation check."""
    text_blocks: list[dict] = []
    inside_blocks: list[list[dict]] = [[] for _ in table_rects]
    for block in blocks:
        rect = fitz.Rect(block["bbox"])
        consumed = False
        for idx, table_rect in enumerate(table_rects):
            if _overlap_ratio(rect, table_rect) >= _TABLE_INSIDE_OVERLAP_RATIO:
                inside_blocks[idx].append(block)
                consumed = True
                break
        if not consumed:
            text_blocks.append(block)
    return text_blocks, inside_blocks


def _overlap_ratio(rect: fitz.Rect, other: fitz.Rect) -> float:
    """Fraction of `rect`'s own area that falls inside `other`."""
    if rect.get_area() <= 0:
        return 0.0
    inter = rect & other
    if inter.is_empty:
        return 0.0
    return inter.get_area() / rect.get_area()


# ---------------------------------------------------------------------------
# Reading order.
# ---------------------------------------------------------------------------


_TWO_COLUMN_MIN_Y_COVERAGE = 0.6  # each column must span this much of the
# page's text-bearing vertical extent -- a short, centered pull-quote
# that happens to be indented differently from the body only occupies a
# small slice of that extent, so it fails this check.
_TWO_COLUMN_MIN_ITEM_SHARE = 0.3  # and hold a real share of the page's
# items, not just one or two odd elements.


def _order_items(items: list[dict], page_width: float) -> tuple[list[dict], bool]:
    """Single-column baseline: sort by (y, x). Basic two-column
    detection: a clear bimodal x-clustering of block left-edges with a
    real gutter between them, where both clusters look like genuine
    page-wide columns (see `_looks_like_genuine_two_column`) -- order
    left column top-to-bottom, then right column. Anything with 3+
    distinct horizontal clusters, or a 2-cluster split that doesn't look
    like a real two-column layout (e.g. a centered pull-quote indented
    differently from the surrounding body text), is outside this
    heuristic's confidence: fall back to plain y-order and flag it (R20)
    rather than guess at the layout."""
    if len(items) < 4:
        return sorted(items, key=lambda i: (i["bbox"][1], i["bbox"][0])), False

    xs = sorted(i["bbox"][0] for i in items)
    gutter_min = page_width * 0.04
    clusters: list[list[float]] = [[xs[0]]]
    for x in xs[1:]:
        if x - clusters[-1][-1] > gutter_min:
            clusters.append([x])
        else:
            clusters[-1].append(x)

    if len(clusters) == 2 and len(clusters[0]) >= 2 and len(clusters[1]) >= 2:
        left_max = clusters[0][-1]
        right_min = clusters[1][0]
        if right_min - left_max >= page_width * 0.03:
            split_x = (left_max + right_min) / 2
            left = [i for i in items if i["bbox"][0] < split_x]
            right = [i for i in items if i["bbox"][0] >= split_x]
            if _looks_like_genuine_two_column(items, left, right):
                left_sorted = sorted(left, key=lambda i: i["bbox"][1])
                right_sorted = sorted(right, key=lambda i: i["bbox"][1])
                return left_sorted + right_sorted, False
            # Bimodal x-split exists but doesn't look like a real
            # page-wide two-column layout -- e.g. a pull-quote indented
            # away from the body. Emitting it as "column 2" would move
            # it out of its actual reading position, so fall back to
            # plain y-order; the x-distribution was genuinely bimodal so
            # this is flagged uncertain rather than treated as a clean
            # single column.
            return sorted(items, key=lambda i: (i["bbox"][1], i["bbox"][0])), True

    uncertain = len(clusters) >= 3
    return sorted(items, key=lambda i: (i["bbox"][1], i["bbox"][0])), uncertain


def _looks_like_genuine_two_column(items: list[dict], left: list[dict], right: list[dict]) -> bool:
    """A real two-column layout has both columns running the (near)
    full vertical extent of the page's text-bearing content, each
    holding a real share of the page's items -- not one dominant body
    column plus a single odd, differently-indented element like a
    pull-quote or a marginal callout."""
    total_top = min(i["bbox"][1] for i in items)
    total_bottom = max(i["bbox"][3] for i in items)
    total_extent = total_bottom - total_top
    if total_extent <= 0:
        return False
    for cluster in (left, right):
        if len(cluster) / len(items) < _TWO_COLUMN_MIN_ITEM_SHARE:
            return False
        cluster_top = min(i["bbox"][1] for i in cluster)
        cluster_bottom = max(i["bbox"][3] for i in cluster)
        coverage = (cluster_bottom - cluster_top) / total_extent
        if coverage < _TWO_COLUMN_MIN_Y_COVERAGE:
            return False
    return True


# ---------------------------------------------------------------------------
# Text block -> Heading/Paragraph/ListBlock.
#
# List detection operates per *line* (not per already-merged paragraph),
# per the plan: "detect bullet/number prefixes on consecutive lines" --
# a real-world (e.g. Word-authored) PDF commonly renders an entire
# bulleted list as a single PyMuPDF text block, with each list item as
# one line inside it, so line-level splitting is required to recover
# individual list items instead of emitting the whole list as one
# run-on paragraph.
# ---------------------------------------------------------------------------


def _build_text_item(
    block: dict,
    body_size: float,
    size_to_level: dict[float, int],
    size_char_counts: Counter,
    link_pool: list[dict],
    page_num: int,
) -> list:
    line_run_lists: list[list[TextRun]] = []
    size_counts: Counter[float] = Counter()
    for line in block["lines"]:
        line_runs = _spans_to_line_runs(line, link_pool)
        if not line_runs:
            continue
        line_run_lists.append(line_runs)
        for span in line["spans"]:
            stripped = span["text"].strip()
            if stripped:
                size_counts[_round_size(span["size"])] += len(stripped)

    if not line_run_lists:
        return []

    rep_size = size_counts.most_common(1)[0][0] if size_counts else body_size
    level = size_to_level.get(rep_size)

    line_texts = ["".join(r.text for r in lr).strip() for lr in line_run_lists]
    is_list_line = [_is_list_item_text(t) for t in line_texts]

    if level or not any(is_list_line):
        runs = _merge_line_runs(line_run_lists)
        if not runs or not "".join(r.text for r in runs).strip():
            return []
        if level:
            heading_text = "".join(r.text for r in runs)
            return [_make_heading(level, runs, page_num, rep_size, body_size, size_char_counts, heading_text)]
        return [Paragraph(runs=runs)]

    # Mixed/list content: split into groups starting at each
    # bullet/number-prefixed line; non-prefixed lines continue the
    # current group (a wrapped list item), or -- before the first
    # bullet is seen -- form a small leading paragraph.
    leading: list[list[TextRun]] = []
    groups: list[list[list[TextRun]]] = []
    for line_runs, starts_item in zip(line_run_lists, is_list_line):
        if starts_item:
            groups.append([line_runs])
        elif groups:
            groups[-1].append(line_runs)
        else:
            leading.append(line_runs)

    result: list = []
    if leading:
        runs = _merge_line_runs(leading)
        if runs and "".join(r.text for r in runs).strip():
            result.append(Paragraph(runs=runs))
    if groups:
        ordered = bool(_NUMBERED_RE.match(line_texts[0]))
        items = []
        for group_lines in groups:
            runs = _merge_line_runs(group_lines)
            runs = _strip_list_prefix(runs)
            if runs:
                items.append(ListItem(runs=runs))
        if items:
            result.append(ListBlock(ordered=ordered, items=items))
    return result


def _heading_confidence(rep_size: float, body_size: float, size_char_counts: Counter, text: str) -> float:
    """Blend size gap vs. body cluster, tier rarity, and length sanity
    into a single 0..1 confidence score (see R19 in
    docs/WCAG-CHECKLIST.md)."""
    if body_size > 0:
        gap = (rep_size / body_size) - _HEADING_SIZE_MARGIN
        size_gap_score = max(0.0, min(1.0, gap / _HEADING_SIZE_GAP_FULL_CONFIDENCE_DELTA))
    else:
        size_gap_score = 1.0

    tier_chars = size_char_counts.get(rep_size, 0)
    rarity_score = max(0.0, min(1.0, tier_chars / _HEADING_TIER_RARITY_FULL_CONFIDENCE_CHARS))

    text_len = len(text)
    if text_len <= _HEADING_LOW_CONFIDENCE_CHARS:
        length_score = 1.0
    else:
        overshoot = text_len - _HEADING_LOW_CONFIDENCE_CHARS
        length_score = max(0.0, 1.0 - overshoot / _HEADING_LOW_CONFIDENCE_CHARS)

    return (size_gap_score + rarity_score + length_score) / 3


def _make_heading(
    level: int,
    runs: list[TextRun],
    page_num: int,
    rep_size: float,
    body_size: float,
    size_char_counts: Counter,
    text: str,
) -> Heading:
    heading = Heading(level=level, runs=runs)
    confidence = _heading_confidence(rep_size, body_size, size_char_counts, text)
    heading._confidence = confidence  # noqa: SLF001 -- internal signal for _process_page's summary stats, not part of the IR contract
    if confidence < _HEADING_LOW_CONFIDENCE_THRESHOLD:
        heading.flags.append(
            Flag(
                code="HEADING_LOW_CONFIDENCE",
                wcag_sc="2.4.6",
                message=(
                    f"Text on page {page_num + 1} ('{text[:60]}"
                    f"{'...' if len(text) > 60 else ''}') was classified "
                    f"as a level-{level} heading based on font size, but "
                    f"scored low confidence ({confidence:.2f}) -- could be "
                    "a misclassified pull-quote or emphasized paragraph. "
                    "Verify this is really a heading."
                ),
                location=f"page {page_num + 1}",
            )
        )
    return heading


def _spans_to_line_runs(line: dict, link_pool: list[dict]) -> list[TextRun]:
    line_runs: list[TextRun] = []
    for span in line["spans"]:
        text = span["text"]
        if not text:
            continue
        bold = bool(span["flags"] & _BOLD_FLAG_BIT)
        italic = bool(span["flags"] & _ITALIC_FLAG_BIT)
        href = _match_link(fitz.Rect(span["bbox"]), link_pool)
        link = Link(text=text, href=href) if href else None
        line_runs.append(TextRun(text=text, bold=bold, italic=italic, link=link))
    return line_runs


def _merge_line_runs(line_run_lists: list[list[TextRun]]) -> list[TextRun]:
    """Join a sequence of per-line run lists into one paragraph's worth
    of runs: adjacent lines get a space between them, except a
    conservative hyphenated-word-wrap join (see `_try_hyphen_join`)."""
    out: list[TextRun] = []
    for line_runs in line_run_lists:
        if not line_runs:
            continue
        if out:
            joined = _try_hyphen_join(out[-1], line_runs[0])
            if joined is not None:
                out[-1] = joined
                line_runs = line_runs[1:]
            else:
                out.append(TextRun(text=" "))
        out.extend(line_runs)
    return [r for r in out if r.text]


def _try_hyphen_join(prev: TextRun, nxt: TextRun) -> TextRun | None:
    """Conservative hyphenated-line-break join: only when the previous
    run ends in a letter-hyphen with no trailing space and no link
    boundary is being crossed, and the next run starts with a lowercase
    letter (a genuine word continuation, not e.g. a new sentence or a
    hyphenated list marker)."""
    if prev.link is not None or nxt.link is not None:
        return None
    prev_text = prev.text
    if not prev_text or not prev_text[-1] == "-":
        return None
    if len(prev_text) < 2 or not prev_text[-2].isalpha():
        return None
    nxt_text = nxt.text
    if not nxt_text or not nxt_text[0].isalpha() or not nxt_text[0].islower():
        return None
    return TextRun(text=prev_text[:-1] + nxt_text, bold=prev.bold, italic=prev.italic)


def _match_link(span_rect: fitz.Rect, link_pool: list[dict]) -> str | None:
    for link in link_pool:
        if link["matched"]:
            continue
        inter = span_rect & link["rect"]
        if inter.is_empty:
            continue
        smaller_area = min(span_rect.get_area(), link["rect"].get_area())
        if smaller_area > 0 and inter.get_area() >= 0.5 * smaller_area:
            link["matched"] = True
            return link["uri"]
    return None


# ---------------------------------------------------------------------------
# Lists: merge adjacent ListBlocks/bullet paragraphs that ended up as
# separate items above (e.g. one PyMuPDF text block per list item)
# into a single list.
# ---------------------------------------------------------------------------


def _group_lists(items: list) -> list:
    result: list = []
    buffer_items: list[ListItem] = []
    buffer_ordered = False
    buffer_paras: list[Paragraph] = []

    def flush_paras() -> None:
        nonlocal buffer_paras
        if not buffer_paras:
            return
        if len(buffer_paras) >= 2:
            ordered = bool(_NUMBERED_RE.match(buffer_paras[0].text.strip()))
            list_items = [ListItem(runs=_strip_list_prefix(p.runs)) for p in buffer_paras]
            result.append(ListBlock(ordered=ordered, items=list_items))
        else:
            result.extend(buffer_paras)
        buffer_paras = []

    def flush_list() -> None:
        nonlocal buffer_items
        if buffer_items:
            result.append(ListBlock(ordered=buffer_ordered, items=buffer_items))
            buffer_items = []

    for item in items:
        if isinstance(item, ListBlock):
            flush_paras()
            if buffer_items:
                buffer_items.extend(item.items)
            else:
                buffer_items = list(item.items)
                buffer_ordered = item.ordered
        elif isinstance(item, Paragraph) and _is_list_item_text(item.text):
            flush_list()
            buffer_paras.append(item)
        else:
            flush_list()
            flush_paras()
            result.append(item)
    flush_list()
    flush_paras()
    return result


def _is_list_item_text(text: str) -> bool:
    stripped = text.strip()
    return bool(_BULLET_RE.match(stripped) or _NUMBERED_RE.match(stripped))


def _strip_list_prefix(runs: list[TextRun]) -> list[TextRun]:
    if not runs or runs[0].link is not None:
        return runs
    first = runs[0]
    stripped = _BULLET_RE.sub("", first.text, count=1)
    if stripped == first.text:
        stripped = _NUMBERED_RE.sub("", first.text, count=1)
    if stripped == first.text:
        return runs
    new_first = TextRun(text=stripped, bold=first.bold, italic=first.italic, link=first.link)
    return [new_first] + runs[1:]


# ---------------------------------------------------------------------------
# Tables (via PyMuPDF's find_tables -- simple grids only, R18).
# ---------------------------------------------------------------------------


def _build_table(table: "fitz.table.Table", inside_blocks: list[dict], page_num: int) -> Table:
    data = table.extract()
    rows: list[TableRow] = []
    col_count = len(data[0]) if data else 0
    ragged = False
    for row_idx, row_vals in enumerate(data):
        if len(row_vals) != col_count:
            ragged = True
        cells = [
            TableCell(runs=[TextRun(text=(v or "").strip())], header=(row_idx == 0))
            for v in row_vals
        ]
        rows.append(TableRow(cells=cells))

    ir_table = Table(rows=rows, header_row=bool(rows))
    ir_table.flags.append(
        Flag(
            code="NO_HEADER_ROW_DETECTED",
            wcag_sc="1.3.1",
            message=(
                f"Table on page {page_num + 1} has no explicit header "
                "markup (PDFs don't carry one) -- the first row was "
                "assumed to be a header row. Verify this is correct for "
                "this table."
            ),
            location=f"page {page_num + 1}",
        )
    )
    if ragged:
        ir_table.flags.append(
            Flag(
                code="COMPLEX_TABLE_STRUCTURE",
                wcag_sc="1.3.1",
                message=(
                    f"Table on page {page_num + 1} has rows of differing "
                    "cell counts (likely merged cells or a mis-detected "
                    "grid); automatic header/scope association is "
                    "unreliable here. Needs manual review."
                ),
                location=f"page {page_num + 1}",
            )
        )
    if not _cells_reconcile_with_inside_blocks(data, inside_blocks):
        ir_table.flags.append(
            Flag(
                code="TABLE_EXTRACTION_UNCERTAIN",
                wcag_sc="1.3.1",
                message=(
                    f"Table on page {page_num + 1}'s extracted cell "
                    "content includes text that doesn't reconcile with "
                    "what's actually inside the detected table borders "
                    "(likely nearby text -- e.g. a tight caption -- that "
                    "bled into a cell during extraction). Verify the "
                    "table's cell contents against the source page before "
                    "publishing."
                ),
                location=f"page {page_num + 1}",
            )
        )
    return ir_table


def _cells_reconcile_with_inside_blocks(data: list[list[str | None]], inside_blocks: list[dict]) -> bool:
    """True if every non-whitespace character `table.extract()` put into
    a cell is accounted for by text genuinely inside the table's bbox.
    Extra characters mean nearby text outside the table (e.g. a caption
    a couple points below the border) leaked into a cell during
    PyMuPDF's own extraction -- a sign the cell content can't be
    trusted blindly."""
    inside_chars: Counter[str] = Counter()
    for block in inside_blocks:
        for line in block["lines"]:
            for span in line["spans"]:
                inside_chars.update("".join(span["text"].split()))

    extract_chars: Counter[str] = Counter()
    for row in data:
        for cell in row:
            if cell:
                extract_chars.update("".join(cell.split()))

    return not (extract_chars - inside_chars)


# ---------------------------------------------------------------------------
# Images.
# ---------------------------------------------------------------------------


def _placed_images_on_page(page: fitz.Page, image_page_counts: Counter) -> list[dict]:
    """Only images that actually have a placement rect on this page --
    `get_images` also returns soft-mask/alpha-channel xrefs that aren't
    independently placed content."""
    placed = []
    seen_xrefs = set()
    for info in page.get_images(full=True):
        xref = info[0]
        if xref in seen_xrefs:
            continue
        rects = page.get_image_rects(xref)
        if not rects:
            continue
        seen_xrefs.add(xref)
        placed.append({"xref": xref, "rect": tuple(rects[0])})
    return placed


def _build_image(
    pdf: fitz.Document,
    img: dict,
    image_page_counts: Counter,
    page_count: int,
    image_bytes_cache: dict[int, tuple[bytes, str | None]],
    link_pool: list[dict],
) -> Image:
    xref = img["xref"]
    if xref not in image_bytes_cache:
        try:
            info = pdf.extract_image(xref)
            mime = _EXT_TO_MIME.get(info.get("ext", ""), f"image/{info.get('ext', 'png')}")
            image_bytes_cache[xref] = (info["image"], mime)
        except Exception:
            image_bytes_cache[xref] = (b"", None)
    data, mime = image_bytes_cache[xref]

    # Tiny is judged by displayed size (the placed rect, in points) --
    # not native pixel resolution -- since a reader perceives a small
    # icon/bullet glyph by how big it looks on the page, not by how many
    # source pixels it was encoded with.
    rect = img["rect"]
    displayed_width = rect[2] - rect[0]
    displayed_height = rect[3] - rect[1]
    tiny = displayed_width < _TINY_IMAGE_PX or displayed_height < _TINY_IMAGE_PX
    # "Appears on >50% of pages" is only a meaningful decorative signal
    # for a document with enough pages that repetition is actually
    # distinguishing -- on a 1-2 page document every image trivially
    # appears on "most" pages.
    repeated = page_count >= _REPEATED_IMAGE_MIN_PAGES and (
        image_page_counts.get(xref, 0) / page_count > _REPEATED_IMAGE_PAGE_FRACTION
    )

    image_rect = fitz.Rect(img["rect"])
    href = _match_link(image_rect, link_pool)
    link = Link(text="", href=href) if href else None

    if tiny or repeated:
        reason = "very small (likely a bullet/icon glyph)" if tiny else "repeated across most pages (likely a logo/watermark)"
        image = Image(
            decorative=True,
            needs_review=True,
            data=data,
            mime_type=mime,
            link=link,
        )
        image.flags.append(
            Flag(
                code="DECORATIVE_ASSUMED",
                wcag_sc="1.1.1",
                message=(
                    f"Image assumed decorative ({reason}) and given empty "
                    "alt text. Confirm this image doesn't convey meaning "
                    "that needs a real description."
                ),
            )
        )
        return image

    image = Image(
        decorative=None,
        needs_review=True,
        data=data,
        mime_type=mime,
        link=link,
    )
    image.flags.append(
        Flag(
            code="MISSING_ALT",
            wcag_sc="1.1.1",
            message=(
                "PDFs carry no reliable alt text for embedded images; "
                "this image needs a human-authored description or an "
                "explicit decorative marking before publishing."
            ),
        )
    )
    return image


# ---------------------------------------------------------------------------
# Title / language.
# ---------------------------------------------------------------------------


def _read_catalog_lang(pdf: fitz.Document) -> str | None:
    kind, value = pdf.xref_get_key(pdf.pdf_catalog(), "Lang")
    if kind == "string" and value:
        return value
    return None


def _determine_title(metadata_title: str, blocks: list, path: Path) -> tuple[str, Flag | None]:
    raw = (metadata_title or "").strip()
    if raw:
        m = _WORD_TITLE_RE.match(raw)
        if m:
            cleaned = m.group(1).strip()
            if cleaned:
                return cleaned, Flag(
                    code="TITLE_CLEANED",
                    wcag_sc="2.4.2",
                    message=(
                        f"Document title metadata looked like an "
                        f"editor-generated string ('{raw}'); cleaned to "
                        f"'{cleaned}'. Verify this is an accurate title."
                    ),
                )
        return raw, None

    heading_blocks = [b for b in blocks if isinstance(b, Heading) and b.level == 1]
    if heading_blocks:
        text = heading_blocks[0].text.strip()
        if text:
            return text, None

    return path.stem, Flag(
        code="TITLE_FROM_FILENAME",
        wcag_sc="2.4.2",
        message=(
            f"No document title metadata or heading found; using the "
            f"filename '{path.stem}' as the document title. Confirm or "
            "replace with a descriptive title."
        ),
    )


# ---------------------------------------------------------------------------
# Plain-text flattening (for language detection -- mirrors docx.py).
# ---------------------------------------------------------------------------


def _block_plain_text(block) -> str:
    if isinstance(block, (Heading, Paragraph)):
        return block.text
    if isinstance(block, ListBlock):
        return " ".join("".join(r.text for r in item.runs) for item in block.items)
    if isinstance(block, Table):
        return " ".join(cell.text for row in block.rows for cell in row.cells)
    return ""


__all__ = ["extract_pdf", "PdfExtractionError", "ProgressCallback"]
