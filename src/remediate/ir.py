"""Internal document representation (IR).

Both format extractors (DOCX via mammoth/python-docx, PDF via PyMuPDF)
populate this model; the accessible-HTML generator consumes it. Kept as
plain dataclasses -- no pydantic needed, nothing here does I/O or
validation-at-parse-time beyond what `__post_init__` sanity checks are
worth having.

Every place a human judgment call may be required (missing alt text,
ambiguous heading level, possible generic link text, etc.) carries a
`flags: list[Flag]` field so the compliance report (task 6) can surface it
without re-walking the tree to rediscover ambiguity.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Flags: human-attention markers, each mapped to a WCAG success criterion.
# ---------------------------------------------------------------------------


@dataclass
class Flag:
    """A single human-attention marker attached to a block or run.

    code: short machine-stable identifier, e.g. "MISSING_ALT",
          "HEADING_SKIP", "GENERIC_LINK_TEXT". Used by the report generator
          to group/count flags and by tests to assert specific detections.
    wcag_sc: WCAG 2.1 success criterion number this flag relates to, e.g.
             "1.1.1", "2.4.4". Matches the checklist numbering from task 1.
    message: human-readable explanation of what needs review and why.
    location: free-text pointer to where in the source this occurred (e.g.
              "page 4", "paragraph 12", "table 2, row 3"). Best-effort --
              extractors may not always have precise location info.
    """

    code: str
    wcag_sc: str
    message: str
    location: str | None = None


# ---------------------------------------------------------------------------
# Rich-text runs: the inline content of paragraphs, list items, table cells.
# ---------------------------------------------------------------------------


@dataclass
class Link:
    """An inline hyperlink within a run of rich text."""

    text: str
    href: str
    flags: list[Flag] = field(default_factory=list)


@dataclass
class TextRun:
    """A run of plain or lightly-styled inline text.

    `links` are hyperlinks embedded within this run's text (by character
    offset would be ideal for a real renderer, but for v1 a run is split
    at link boundaries by the extractor, so a TextRun is either plain text
    or wraps exactly one Link -- see `link`).
    """

    text: str
    bold: bool = False
    italic: bool = False
    link: Link | None = None


# ---------------------------------------------------------------------------
# Block-level content.
# ---------------------------------------------------------------------------


@dataclass
class Heading:
    """A section heading. `level` is 1-6, matching HTML h1..h6."""

    level: int
    runs: list[TextRun]
    flags: list[Flag] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 1 <= self.level <= 6:
            raise ValueError(f"Heading level must be 1-6, got {self.level}")

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class Paragraph:
    """A run-of-the-mill paragraph of body text."""

    runs: list[TextRun]
    flags: list[Flag] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class ListItem:
    """A single item in a ListBlock. May contain nested lists."""

    runs: list[TextRun]
    sub_lists: list["ListBlock"] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)


@dataclass
class ListBlock:
    """An ordered or unordered list. Items may nest sub-lists."""

    ordered: bool
    items: list[ListItem] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)


@dataclass
class TableCell:
    """A single table cell. `header` marks it as a th (vs td).

    `colspan`/`rowspan` mirror the source's merged-cell span (1 means no
    merge). The extractor preserves these honestly rather than silently
    collapsing them -- see `Table.flags` for the accompanying
    COMPLEX_TABLE_STRUCTURE human-review flag on any table that uses
    them (R18)."""

    runs: list[TextRun]
    header: bool = False
    colspan: int = 1
    rowspan: int = 1
    flags: list[Flag] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class TableRow:
    cells: list[TableCell] = field(default_factory=list)


@dataclass
class Table:
    """A data table.

    `header_row` / `header_col` are heuristics-derived flags saying
    whether the first row / first column look like headers -- the HTML
    generator uses these plus each cell's own `header` flag to decide
    scope="col"/"row" when emitting <th>. Complex tables (merged cells,
    both header row AND header col, nested tables) are out of scope for
    v1 auto-remediation -- extractors should set a flag rather than guess
    at row/col header duality.
    """

    rows: list[TableRow] = field(default_factory=list)
    header_row: bool = False
    header_col: bool = False
    caption: str | None = None
    flags: list[Flag] = field(default_factory=list)


@dataclass
class Image:
    """An embedded image.

    `alt`: extracted or human-provided alt text, if any.
    `decorative`: True if determined (or asserted) to be decorative and
        should get alt="" / aria-hidden treatment; None means undetermined
        (extractor could not tell -- gets a flag).
    `needs_review`: explicit flag that this image's alt/decorative status
        is a placeholder and needs human confirmation before publishing.
    `data`: raw image bytes, populated by the extractor so the HTML
        generator can inline or write it out without re-reading the source
        document.
    `mime_type`: e.g. "image/png", "image/jpeg".
    `link`: set when the image itself is wrapped in a hyperlink in the
        source (e.g. a linked logo/banner) -- the HTML generator wraps
        the rendered `<img>` in an `<a href>` using this instead of
        silently dropping the link (or the image).
    """

    alt: str | None = None
    decorative: bool | None = None
    needs_review: bool = True
    data: bytes | None = None
    mime_type: str | None = None
    link: Link | None = None
    flags: list[Flag] = field(default_factory=list)


# Union of every block type a Document's top-level `blocks` list may hold.
Block = Heading | Paragraph | ListBlock | Table | Image


# ---------------------------------------------------------------------------
# Document root.
# ---------------------------------------------------------------------------


@dataclass
class Document:
    """The root IR node produced by an extractor and consumed by the HTML
    generator.

    title: document title. Required for PDF/UA (DisplayDocTitle) -- if the
        source has none, the extractor should synthesize one (e.g. from
        filename or first heading) and add a flag.
    lang: BCP-47 language tag, e.g. "en". Document-level only (per-passage
        language tagging is out of scope for v1 -- see plan).
    blocks: ordered top-level content blocks in reading order.
    source_format: "docx" or "pdf" -- which extractor produced this.
    warnings: document-level notices that aren't tied to one block (e.g.
        "detected as scanned/image-only, rejected", "encrypted, rejected").
        Block-level issues belong in each block's own `flags` instead.
    """

    title: str
    lang: str
    blocks: list[Block] = field(default_factory=list)
    source_format: str = "unknown"
    warnings: list[str] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    """Document-level flags not tied to any single block (e.g. assumed
    language, filename-fallback title) -- see extractors/docx.py. Kept
    separate from `warnings` (free text) because the compliance report
    (task 6) needs the structured `code`/`wcag_sc` fields."""

    def all_flags(self) -> list[Flag]:
        """Collect every flag in the document -- document-level flags
        first, then block flags in document order -- for the compliance
        report generator (task 6)."""
        flags: list[Flag] = list(self.flags)
        for block in self.blocks:
            flags.extend(_block_flags(block))
        return flags


def _run_flags(runs: list[TextRun]) -> list[Flag]:
    """Flags attached to hyperlinks embedded in a run of text (e.g.
    generic link text) -- these live on `TextRun.link.flags`, not on the
    enclosing block, so `_block_flags` has to reach into them."""
    flags: list[Flag] = []
    for run in runs:
        if run.link is not None:
            flags.extend(run.link.flags)
    return flags


def _block_flags(block: Block) -> list[Flag]:
    flags = list(block.flags)
    if isinstance(block, (Heading, Paragraph)):
        flags.extend(_run_flags(block.runs))
    elif isinstance(block, ListBlock):
        for item in block.items:
            flags.extend(item.flags)
            flags.extend(_run_flags(item.runs))
            for sub in item.sub_lists:
                flags.extend(_block_flags(sub))
    elif isinstance(block, Table):
        for row in block.rows:
            for cell in row.cells:
                flags.extend(cell.flags)
                flags.extend(_run_flags(cell.runs))
    return flags
