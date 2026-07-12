"""IR -> accessible HTML generator (plan task 5).

Turns a `remediate.ir.Document` into a complete, standalone HTML document:
semantic tags matching the IR block types, heading-skip repair, a single
h1, `<th scope>` for table headers (falling back to first-row-as-header
when the extractor couldn't determine one), alt-text placeholders,
generic-link-text detection, and a default AA-contrast-safe stylesheet.

Every repair this module makes is recorded as an `AutoFix` (parallel to
`ir.Flag` but for already-resolved, deterministic fixes rather than
items that need human review) so the compliance report (task 6) can list
both what was auto-fixed and what still needs a human.
"""

from __future__ import annotations

import base64
import html as html_escape
import re
from dataclasses import dataclass, field

from .ir import (
    Block,
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

MISSING_ALT_PLACEHOLDER = "[ALT TEXT NEEDED: description of image]"

_GENERIC_LINK_PHRASES = {
    "click here",
    "here",
    "read more",
    "more",
    "link",
    "learn more",
    "this link",
    "more info",
    "more information",
}
_BARE_URL_RE = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)


@dataclass
class AutoFix:
    """A deterministic repair the generator applied automatically.

    Distinct from `ir.Flag`: a Flag means "a human needs to look at
    this"; an AutoFix means "the pipeline already fixed this" but is
    still reported (per the WCAG checklist's AUTO+FLAG verdict type) so
    a human can review/override the fix.
    """

    code: str
    wcag_sc: str
    message: str
    location: str | None = None


@dataclass
class HtmlResult:
    html: str
    autofixes: list[AutoFix] = field(default_factory=list)


DEFAULT_CSS = """
:root {
  color-scheme: light;
}
body {
  font-family: "Segoe UI", "Helvetica Neue", Arial, "Liberation Sans", sans-serif;
  color: #1a1a1a;
  background: #ffffff;
  line-height: 1.5;
  font-size: 1rem;
  max-width: 46rem;
  margin: 2rem auto;
  padding: 0 1.5rem;
}
h1, h2, h3, h4, h5, h6 {
  font-weight: 700;
  line-height: 1.25;
  margin-top: 1.75em;
  margin-bottom: 0.6em;
  color: #111111;
}
h1 { font-size: 2rem; border-bottom: 0.125rem solid #111111; padding-bottom: 0.25em; }
h2 { font-size: 1.5rem; }
h3 { font-size: 1.25rem; }
h4 { font-size: 1.1rem; }
h5, h6 { font-size: 1rem; text-transform: uppercase; letter-spacing: 0.03em; }
p { margin: 0 0 1em 0; }
a {
  color: #0b4d8f;
  text-decoration: underline;
  text-underline-offset: 0.15em;
}
a:visited { color: #5a2a82; }
ul, ol { margin: 0 0 1em 0; padding-left: 1.75em; }
li { margin-bottom: 0.35em; }
table {
  border-collapse: collapse;
  width: 100%;
  margin: 0 0 1.5em 0;
}
caption {
  text-align: left;
  font-weight: 700;
  margin-bottom: 0.5em;
}
th, td {
  border: 0.0625rem solid #555555;
  padding: 0.5em 0.75em;
  text-align: left;
  vertical-align: top;
}
th {
  background: #ececec;
  font-weight: 700;
}
img {
  max-width: 100%;
  height: auto;
}
figure { margin: 1.5em 0; }
figcaption { font-size: 0.9rem; color: #333333; margin-top: 0.4em; }
"""


def generate_html(document: Document) -> HtmlResult:
    autofixes: list[AutoFix] = []

    headings = [b for b in document.blocks if isinstance(b, Heading)]
    synthetic_title_heading: Heading | None = None
    if not headings:
        synthetic_title_heading = Heading(level=1, runs=[TextRun(text=document.title)])
        autofixes.append(
            AutoFix(
                code="TITLE_PROMOTED_TO_H1",
                wcag_sc="1.3.1",
                message=(
                    "Document had no headings at all; the document title was "
                    "promoted to a single H1 so the page has a proper heading "
                    "structure."
                ),
            )
        )
    else:
        h1_indices = [i for i, h in enumerate(headings) if h.level == 1]
        if not h1_indices:
            synthetic_title_heading = Heading(level=1, runs=[TextRun(text=document.title)])
            autofixes.append(
                AutoFix(
                    code="TITLE_PROMOTED_TO_H1",
                    wcag_sc="1.3.1",
                    message=(
                        "Document had headings but no H1; the document title "
                        "was promoted to a single H1 above the existing "
                        "heading structure."
                    ),
                )
            )
        else:
            first_h1 = h1_indices[0]
            for i in h1_indices[1:]:
                headings[i].level = 2
                autofixes.append(
                    AutoFix(
                        code="MULTIPLE_H1_DEMOTED",
                        wcag_sc="1.3.1",
                        message=(
                            f'Duplicate top-level heading "{headings[i].text}" '
                            "was demoted from H1 to H2 -- a page must have "
                            "exactly one H1."
                        ),
                        location=f"heading: {headings[i].text[:60]!r}",
                    )
                )

    # Heading-skip repair: no heading may jump more than one level below
    # the previous rendered level (decreases/level-ups are always fine).
    ordered_headings = ([synthetic_title_heading] if synthetic_title_heading else []) + headings
    prev_level = 0
    for heading in ordered_headings:
        original = heading.level
        capped = original if original <= prev_level + 1 else prev_level + 1
        capped = max(capped, 1)
        if capped != original:
            autofixes.append(
                AutoFix(
                    code="HEADING_SKIP_REPAIRED",
                    wcag_sc="2.4.6",
                    message=(
                        f'Heading "{heading.text}" jumped from level '
                        f"{prev_level} to {original}; repaired to level "
                        f"{capped} to avoid skipping levels."
                    ),
                    location=f"heading: {heading.text[:60]!r}",
                )
            )
            heading.level = capped
        prev_level = heading.level

    body_parts: list[str] = []
    if synthetic_title_heading is not None:
        body_parts.append(_render_heading(synthetic_title_heading))

    for block in document.blocks:
        body_parts.append(_render_block(block, autofixes))

    html_doc = (
        "<!DOCTYPE html>\n"
        f'<html lang="{_esc(document.lang)}">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_esc(document.title)}</title>\n"
        f"<style>{DEFAULT_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        + "\n".join(p for p in body_parts if p)
        + "\n</body>\n</html>\n"
    )
    return HtmlResult(html=html_doc, autofixes=autofixes)


def _esc(text: str) -> str:
    return html_escape.escape(text, quote=True)


def _render_block(block: Block, autofixes: list[AutoFix]) -> str:
    if isinstance(block, Heading):
        return _render_heading(block)
    if isinstance(block, Paragraph):
        return f"<p>{_render_runs(block.runs)}</p>"
    if isinstance(block, ListBlock):
        return _render_list(block)
    if isinstance(block, Table):
        return _render_table(block, autofixes)
    if isinstance(block, Image):
        return _render_image(block, autofixes)
    raise TypeError(f"Unknown block type: {type(block)!r}")  # pragma: no cover


def _render_heading(heading: Heading) -> str:
    return f"<h{heading.level}>{_render_runs(heading.runs)}</h{heading.level}>"


def _render_list(list_block: ListBlock) -> str:
    tag = "ol" if list_block.ordered else "ul"
    items = "".join(_render_list_item(item) for item in list_block.items)
    return f"<{tag}>{items}</{tag}>"


def _render_list_item(item: ListItem) -> str:
    sub = "".join(_render_list(sub_list) for sub_list in item.sub_lists)
    return f"<li>{_render_runs(item.runs)}{sub}</li>"


def _render_table(table: Table, autofixes: list[AutoFix]) -> str:
    rows = list(table.rows)
    header_row = table.header_row
    if not header_row and rows:
        # No explicit header row detected upstream -- default to
        # first-row-as-header (safer than no header at all for a simple
        # grid table) and record it as an auto-fix, per checklist R18.
        for cell in rows[0].cells:
            cell.header = True
        header_row = True
        autofixes.append(
            AutoFix(
                code="HEADER_ROW_AUTO_ADDED",
                wcag_sc="1.3.1",
                message=(
                    "No header row was explicitly marked in the source table; "
                    "the first row was treated as a header row (<th scope="
                    '"col">) by default. Verify this is correct -- if the '
                    "table isn't a simple column-headed grid, fix manually."
                ),
                location=table.caption or "table",
            )
        )

    parts = ["<table>"]
    if table.caption:
        parts.append(f"<caption>{_esc(table.caption)}</caption>")

    body_rows = rows[1:] if header_row and rows else rows
    if header_row and rows:
        parts.append("<thead>")
        parts.append(_render_row(rows[0], is_header_row=True, header_col=table.header_col))
        parts.append("</thead>")
    if body_rows or not header_row:
        parts.append("<tbody>")
        for row in body_rows if header_row else rows:
            parts.append(_render_row(row, is_header_row=False, header_col=table.header_col))
        parts.append("</tbody>")
    parts.append("</table>")
    return "".join(parts)


def _render_row(row: TableRow, is_header_row: bool, header_col: bool) -> str:
    cells_html = []
    for i, cell in enumerate(row.cells):
        is_header = cell.header or is_header_row or (header_col and i == 0)
        tag = "th" if is_header else "td"
        scope = ""
        if is_header:
            if is_header_row:
                scope = ' scope="col"'
            elif header_col and i == 0:
                scope = ' scope="row"'
        cells_html.append(f"<{tag}{scope}>{_render_runs(cell.runs)}</{tag}>")
    return f"<tr>{''.join(cells_html)}</tr>"


def _render_image(image: Image, autofixes: list[AutoFix]) -> str:
    alt = image.alt
    if image.decorative:
        alt = ""
    elif not alt:
        alt = MISSING_ALT_PLACEHOLDER
        if not any(f.code == "MISSING_ALT" for f in image.flags):
            image.flags.append(
                Flag(
                    code="MISSING_ALT",
                    wcag_sc="1.1.1",
                    message=(
                        "Image rendered with a placeholder alt attribute; "
                        "needs a human-authored description or an explicit "
                        "decorative marking before publishing."
                    ),
                )
            )

    src = ""
    if image.data and image.mime_type:
        b64 = base64.b64encode(image.data).decode("ascii")
        src = f"data:{image.mime_type};base64,{b64}"
    return f'<img src="{src}" alt="{_esc(alt)}">'


def _render_runs(runs: list[TextRun]) -> str:
    return "".join(_render_run(r) for r in runs)


def _render_run(run: TextRun) -> str:
    if run.link is not None:
        inner = _esc(run.link.text)
        _flag_generic_link_text(run.link)
        return f'<a href="{_esc(run.link.href)}">{inner}</a>'

    text = _esc(run.text).replace("\n", "<br>")
    if run.bold:
        text = f"<strong>{text}</strong>"
    if run.italic:
        text = f"<em>{text}</em>"
    return text


def _flag_generic_link_text(link: Link) -> None:
    if any(f.code == "GENERIC_LINK_TEXT" for f in link.flags):
        return
    normalized = link.text.strip().lower()
    is_generic = normalized in _GENERIC_LINK_PHRASES
    is_bare_url = bool(_BARE_URL_RE.match(link.text.strip()))
    if is_generic or is_bare_url:
        reason = "generic link text" if is_generic else "a bare URL as link text"
        link.flags.append(
            Flag(
                code="GENERIC_LINK_TEXT",
                wcag_sc="2.4.4",
                message=(
                    f'Link text "{link.text}" is {reason}, which does not '
                    "describe the link's purpose out of context. Rewrite with "
                    "descriptive text."
                ),
                location=f"link href: {link.href}",
            )
        )
