"""DOCX -> IR extractor (plan task 4).

Uses mammoth to turn Word's semantic paragraph/list/table/image structure
into HTML (mammoth already resolves Word style names, numbering levels,
and repeat-header-row table markup -- reimplementing that walk over raw
python-docx paragraphs would be duplicating a solved problem), then parses
that HTML with lxml into the IR. python-docx is used only for what mammoth
doesn't expose: core properties (title, language) and encrypted/corrupt
file detection.
"""

from __future__ import annotations

import re
from pathlib import Path

import docx
import lxml.html
import mammoth
import mammoth.images
from docx.opc.exceptions import PackageNotFoundError

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


class DocxExtractionError(Exception):
    """Raised when a .docx file cannot be read: corrupt, not a real
    .docx/zip package, or (the common real-world cause) password
    protected -- a password-protected .docx is stored as an encrypted OLE
    compound file, not a valid OOXML zip, so it fails to open the same
    way a corrupt file would."""


_BOLD_TAGS = {"strong", "b"}
_ITALIC_TAGS = {"em", "i"}

# Alt text that is just the image's own filename/placeholder name conveys
# nothing to a screen reader user -- treat it the same as missing alt.
_FILENAME_ALT_RE = re.compile(
    r"^(img|image|pic|picture|photo|graphic|figure)[\s_-]*\d*\.\w+$", re.IGNORECASE
)
_FILENAME_NO_EXT_RE = re.compile(r"^(img|image|pic|dsc)[_\s-]?\d+$", re.IGNORECASE)


def extract_docx(path: str | Path) -> Document:
    """Extract a .docx file into the internal Document representation.

    Raises DocxExtractionError for encrypted/corrupt/non-.docx input --
    the caller (pipeline/CLI) is expected to turn that into a clean exit,
    not a traceback.
    """
    path = Path(path)
    try:
        docx_doc = docx.Document(str(path))
    except PackageNotFoundError as exc:
        raise DocxExtractionError(
            f"Cannot open '{path.name}': not a valid, unencrypted .docx file "
            "(it may be corrupt or password-protected)."
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive: any other read failure
        raise DocxExtractionError(f"Cannot open '{path.name}': {exc}") from exc

    core = docx_doc.core_properties
    doc_flags: list[Flag] = []

    lang = (core.language or "").strip()
    if not lang:
        lang = "en"
        doc_flags.append(
            Flag(
                code="LANG_ASSUMED",
                wcag_sc="3.1.1",
                message=(
                    "No document language metadata found in the source .docx "
                    "(docProps core.xml dc:language is empty); defaulted the "
                    "page language to 'en'. Confirm this is correct or set the "
                    "actual language."
                ),
            )
        )
    else:
        lang = lang.split(",")[0].strip()

    registry: list[tuple[bytes, str]] = []
    convert_image = mammoth.images.img_element(lambda image: _capture_image(image, registry))

    with open(path, "rb") as f:
        result = mammoth.convert_to_html(f, convert_image=convert_image)

    root = lxml.html.fragment_fromstring(result.value, create_parent="div")
    blocks = _walk_blocks(root, registry)

    title = (core.title or "").strip()
    if not title:
        heading_blocks = [b for b in blocks if isinstance(b, Heading)]
        if heading_blocks:
            title = heading_blocks[0].text.strip()
        if not title:
            title = path.stem
            doc_flags.append(
                Flag(
                    code="TITLE_FROM_FILENAME",
                    wcag_sc="2.4.2",
                    message=(
                        f"No document title metadata or heading found; using "
                        f"the filename '{path.stem}' as the document title. "
                        "Confirm or replace with a descriptive title."
                    ),
                )
            )

    return Document(
        title=title,
        lang=lang,
        blocks=blocks,
        source_format="docx",
        flags=doc_flags,
    )


def _capture_image(image, registry: list[tuple[bytes, str]]) -> dict:
    with image.open() as f:
        data = f.read()
    idx = len(registry)
    registry.append((data, image.content_type))
    return {"src": f"remediate-image:{idx}"}


def _looks_filename_like(alt: str) -> bool:
    a = alt.strip()
    if not a:
        return True
    if _FILENAME_ALT_RE.match(a):
        return True
    if _FILENAME_NO_EXT_RE.match(a):
        return True
    return False


def _mk_run(text: str, bold: bool = False, italic: bool = False, link: Link | None = None) -> TextRun:
    return TextRun(text=text, bold=bold, italic=italic, link=link)


def _clean_runs(runs: list[TextRun]) -> list[TextRun]:
    return [r for r in runs if r.text]


def _inline_runs_of_element(el, bold: bool = False, italic: bool = False) -> list[TextRun]:
    """Runs for `el`'s own text plus all descendant inline content
    (not including `el`'s tail -- callers handle tails themselves)."""
    if el.tag in _BOLD_TAGS:
        bold = True
    elif el.tag in _ITALIC_TAGS:
        italic = True

    if el.tag == "a":
        href = el.get("href") or ""
        text = el.text_content()
        if not text:
            return []
        return [_mk_run(text, bold, italic, link=Link(text=text, href=href))]

    runs: list[TextRun] = []
    if el.text:
        runs.append(_mk_run(el.text, bold, italic))
    for child in el:
        if child.tag == "br":
            runs.append(_mk_run("\n", bold, italic))
        else:
            runs.extend(_inline_runs_of_element(child, bold, italic))
        if child.tail:
            runs.append(_mk_run(child.tail, bold, italic))
    return runs


def _build_image(img_el, registry: list[tuple[bytes, str]]) -> Image:
    src = img_el.get("src", "")
    data = b""
    mime = None
    if src.startswith("remediate-image:"):
        idx = int(src.split(":", 1)[1])
        data, mime = registry[idx]

    alt = img_el.get("alt")
    meaningful = bool(alt) and not _looks_filename_like(alt)
    image = Image(
        alt=alt if alt else None,
        data=data,
        mime_type=mime,
        decorative=None,
        needs_review=not meaningful,
    )
    if not meaningful:
        image.flags.append(
            Flag(
                code="MISSING_ALT",
                wcag_sc="1.1.1",
                message=(
                    "Image has no meaningful alt text (missing, empty, or just "
                    "the source filename); needs a human-authored description "
                    "or an explicit decorative marking."
                ),
            )
        )
    return image


def _paragraph_or_images(p_el, registry: list[tuple[bytes, str]]) -> list:
    """A mammoth <p> is either body text, or (for an embedded image) a
    lone <img>. Split on direct-child <img> so mixed content still comes
    out as separate Paragraph/Image blocks in the right order."""
    blocks: list = []
    buffer: list[TextRun] = []

    if p_el.text:
        buffer.append(_mk_run(p_el.text))
    for child in p_el:
        if child.tag == "img":
            cleaned = _clean_runs(buffer)
            if cleaned:
                blocks.append(Paragraph(runs=cleaned))
            buffer = []
            blocks.append(_build_image(child, registry))
        else:
            buffer.extend(_inline_runs_of_element(child))
        if child.tail:
            buffer.append(_mk_run(child.tail))

    cleaned = _clean_runs(buffer)
    if cleaned:
        blocks.append(Paragraph(runs=cleaned))
    return blocks


def _build_list(list_el, registry: list[tuple[bytes, str]]) -> ListBlock:
    ordered = list_el.tag == "ol"
    items: list[ListItem] = []
    for li in list_el:
        if li.tag != "li":
            continue
        sub_lists: list[ListBlock] = []
        runs: list[TextRun] = []
        if li.text:
            runs.append(_mk_run(li.text))
        for child in li:
            if child.tag in ("ul", "ol"):
                sub_lists.append(_build_list(child, registry))
            else:
                runs.extend(_inline_runs_of_element(child))
            if child.tail:
                runs.append(_mk_run(child.tail))
        items.append(ListItem(runs=_clean_runs(runs), sub_lists=sub_lists))
    return ListBlock(ordered=ordered, items=items)


def _build_table(table_el) -> Table:
    thead = table_el.find("thead")
    tbody = table_el.find("tbody")
    header_row = thead is not None

    if thead is not None or tbody is not None:
        row_els = list(thead) if thead is not None else []
        row_els += list(tbody) if tbody is not None else []
    else:
        row_els = list(table_el.findall("tr"))

    rows: list[TableRow] = []
    for tr in row_els:
        cells: list[TableCell] = []
        for cell_el in tr:
            if cell_el.tag not in ("td", "th"):
                continue
            runs = _clean_runs(_inline_runs_of_element(cell_el))
            cells.append(TableCell(runs=runs, header=(cell_el.tag == "th")))
        rows.append(TableRow(cells=cells))

    table = Table(rows=rows, header_row=header_row)
    if not header_row:
        table.flags.append(
            Flag(
                code="NO_HEADER_ROW_DETECTED",
                wcag_sc="1.3.1",
                message=(
                    "This table has no explicit 'repeat as header row' marking "
                    "in the source .docx, so its header row could not be "
                    "determined with confidence. The HTML generator will "
                    "default to treating the first row as a header -- verify "
                    "this is correct for this table."
                ),
            )
        )
    return table


def _walk_blocks(root, registry: list[tuple[bytes, str]]) -> list:
    blocks: list = []
    for el in root.iterchildren():
        tag = el.tag
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            runs = _clean_runs(_inline_runs_of_element(el))
            if runs:
                blocks.append(Heading(level=int(tag[1]), runs=runs))
        elif tag == "p":
            blocks.extend(_paragraph_or_images(el, registry))
        elif tag in ("ul", "ol"):
            blocks.append(_build_list(el, registry))
        elif tag == "table":
            blocks.append(_build_table(el))
        elif tag == "img":
            blocks.append(_build_image(el, registry))
        elif tag in ("blockquote", "div"):
            runs = _clean_runs(_inline_runs_of_element(el))
            if runs:
                para = Paragraph(runs=runs)
                para.flags.append(
                    Flag(
                        code="UNMAPPED_BLOCK",
                        wcag_sc="1.3.1",
                        message=(
                            f"Unrecognized block-level content (<{tag}>) was "
                            "rendered as a plain paragraph; verify its "
                            "structure is correct."
                        ),
                    )
                )
                blocks.append(para)
        # else: ignore (mammoth appends trailing empty <ol>/<dl> for
        # footnotes/comments the source document doesn't use).
    return blocks
