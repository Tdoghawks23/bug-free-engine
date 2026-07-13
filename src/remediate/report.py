"""Compliance report generator (plan task 6).

Takes the IR `Document`'s flags (things a human needs to look at) and the
HTML generator's `AutoFix` list (things the pipeline already fixed), maps
every one to an R-number from docs/WCAG-CHECKLIST.md, and writes both a
machine-readable report.json and a human-readable report.html (styled
with the same accessible stylesheet as the generated document).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from .html_gen import DEFAULT_CSS, AutoFix
from .ir import Document, Flag

# code -> (R-number, human label, severity). wcag_sc comes from the Flag/
# AutoFix itself since both already carry the accurate SC number; the
# R-number here is the docs/WCAG-CHECKLIST.md cross-reference id.
_CODE_INFO: dict[str, tuple[str, str]] = {
    "LANG_ASSUMED": ("R15", "needs-human-review"),
    "LANG_DETECTED": ("R15", "needs-human-review"),
    "TITLE_FROM_FILENAME": ("R12", "needs-human-review"),
    "MISSING_ALT": ("R1b", "needs-human-review"),
    "IMAGE_UNKNOWN_MIME_TYPE": ("R1", "needs-human-review"),
    # Both of these instruct a human to verify something the pipeline
    # couldn't determine with confidence -- "info" undersold that they're
    # actionable, not just FYI.
    "NO_HEADER_ROW_DETECTED": ("R18", "needs-human-review"),
    "UNMAPPED_BLOCK": ("R2", "needs-human-review"),
    "COMPLEX_TABLE_STRUCTURE": ("R18", "needs-human-review"),
    "GENERIC_LINK_TEXT": ("R13", "needs-human-review"),
    "HEADING_SKIP_REPAIRED": ("R14", "auto-fixed"),
    "MULTIPLE_H1_DEMOTED": ("R2", "auto-fixed"),
    "TITLE_PROMOTED_TO_H1": ("R2", "auto-fixed"),
    "HEADER_ROW_AUTO_ADDED": ("R18", "auto-fixed"),
    # PDF extractor (task 8) -- font-size/layout heuristics with no
    # source semantic tags to fall back on, so most of these are
    # needs-human-review by nature.
    "HEADINGS_INFERRED": ("R19", "info"),
    "HEADING_LOW_CONFIDENCE": ("R19", "needs-human-review"),
    "READING_ORDER_UNCERTAIN": ("R20", "needs-human-review"),
    "DECORATIVE_ASSUMED": ("R1b", "needs-human-review"),
    "LINK_UNASSOCIATED": ("R21", "needs-human-review"),
    "TITLE_CLEANED": ("R12", "needs-human-review"),
    "TABLE_EXTRACTION_UNCERTAIN": ("R18", "needs-human-review"),
}
_DEFAULT_R_NUMBER = "R2"


@dataclass
class ReportItem:
    r_number: str
    wcag_sc: str
    severity: str  # "auto-fixed" | "needs-human-review" | "info"
    code: str
    message: str
    location: str | None = None


@dataclass
class LinkEntry:
    """One hyperlink from the document, listed for human spot-check of
    link purpose (R13b / SC 2.4.4) -- every link appears here, not just
    the ones the generic-text blocklist flagged."""

    text: str
    href: str
    flagged: bool  # True when the link also carries a flag (e.g. GENERIC_LINK_TEXT)


@dataclass
class ComplianceReport:
    document_title: str
    items: list[ReportItem]
    links: list[LinkEntry] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts = {"auto-fixed": 0, "needs-human-review": 0, "info": 0}
        for item in self.items:
            counts[item.severity] = counts.get(item.severity, 0) + 1
        return counts

    def to_dict(self) -> dict:
        return {
            "document_title": self.document_title,
            "summary": {
                "total_items": len(self.items),
                **self.counts,
            },
            "items": [asdict(item) for item in self.items],
            # R13b: full link inventory for human spot-check of link
            # purpose, independent of whether any link was flagged.
            "links": [asdict(link) for link in self.links],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def _map_flag(flag: Flag) -> ReportItem:
    r_number, severity = _CODE_INFO.get(flag.code, (_DEFAULT_R_NUMBER, "needs-human-review"))
    return ReportItem(
        r_number=r_number,
        wcag_sc=flag.wcag_sc,
        severity=severity,
        code=flag.code,
        message=flag.message,
        location=flag.location,
    )


def _map_autofix(autofix: AutoFix) -> ReportItem:
    r_number, severity = _CODE_INFO.get(autofix.code, (_DEFAULT_R_NUMBER, "auto-fixed"))
    return ReportItem(
        r_number=r_number,
        wcag_sc=autofix.wcag_sc,
        severity=severity,
        code=autofix.code,
        message=autofix.message,
        location=autofix.location,
    )


def build_report(document: Document, autofixes: list[AutoFix]) -> ComplianceReport:
    items = [_map_flag(f) for f in document.all_flags()]
    items.extend(_map_autofix(a) for a in autofixes)
    # Stable, readable order: auto-fixed first (already resolved), then
    # needs-human-review (most actionable), then info.
    order = {"auto-fixed": 0, "needs-human-review": 1, "info": 2}
    items.sort(key=lambda i: (order.get(i.severity, 3), i.r_number, i.code))
    links = [
        LinkEntry(text=link.text, href=link.href, flagged=bool(link.flags))
        for link in document.all_links()
    ]
    return ComplianceReport(document_title=document.title, items=items, links=links)


_SEVERITY_LABELS = {
    "auto-fixed": "Auto-fixed",
    "needs-human-review": "Needs human review",
    "info": "Informational",
}


def render_report_html(report: ComplianceReport) -> str:
    counts = report.counts
    rows = "\n".join(_render_row(item) for item in report.items)
    if not rows:
        rows = '<tr><td colspan="5">No issues found.</td></tr>'

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>Compliance report: {_esc(report.document_title)}</title>\n"
        f"<style>{DEFAULT_CSS}\n{_REPORT_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"<h1>Compliance report</h1>\n"
        f"<p>Document: <strong>{_esc(report.document_title)}</strong></p>\n"
        "<h2>Summary</h2>\n"
        "<ul>\n"
        f'<li>Total items: {len(report.items)}</li>\n'
        f'<li>Auto-fixed: {counts.get("auto-fixed", 0)}</li>\n'
        f'<li>Needs human review: {counts.get("needs-human-review", 0)}</li>\n'
        f'<li>Informational: {counts.get("info", 0)}</li>\n'
        "</ul>\n"
        "<h2>Items</h2>\n"
        "<table>\n"
        "<thead><tr>"
        "<th scope=\"col\">R#</th>"
        "<th scope=\"col\">WCAG SC</th>"
        "<th scope=\"col\">Severity</th>"
        "<th scope=\"col\">Code</th>"
        "<th scope=\"col\">Message</th>"
        "<th scope=\"col\">Location</th>"
        "</tr></thead>\n"
        f"<tbody>\n{rows}\n</tbody>\n"
        "</table>\n"
        f"{_render_link_inventory(report)}"
        "</body>\n</html>\n"
    )


def _render_link_inventory(report: ComplianceReport) -> str:
    """R13b: every link in the document with its text and resolved URL,
    for a human to spot-check that each link's purpose is clear."""
    if not report.links:
        return ""
    rows = "\n".join(
        "<tr>"
        f"<td>{_esc(link.text) or '<em>(no text)</em>'}</td>"
        f"<td><code>{_esc(link.href)}</code></td>"
        f"<td>{'Flagged' if link.flagged else ''}</td>"
        "</tr>"
        for link in report.links
    )
    return (
        "<h2>Link inventory (R13b)</h2>\n"
        "<p>Spot-check that each link's text makes its purpose clear. "
        "Links already flagged above are marked.</p>\n"
        "<table>\n"
        "<thead><tr>"
        '<th scope="col">Link text</th>'
        '<th scope="col">URL</th>'
        '<th scope="col">Status</th>'
        "</tr></thead>\n"
        f"<tbody>\n{rows}\n</tbody>\n"
        "</table>\n"
    )


_REPORT_CSS = """
tr.severity-auto-fixed td.severity { color: #146c2e; font-weight: 700; }
tr.severity-needs-human-review td.severity { color: #9a3b00; font-weight: 700; }
tr.severity-info td.severity { color: #333333; }
"""


def _render_row(item: ReportItem) -> str:
    return (
        f'<tr class="severity-{item.severity}">'
        f"<td>{_esc(item.r_number)}</td>"
        f"<td>{_esc(item.wcag_sc)}</td>"
        f'<td class="severity">{_esc(_SEVERITY_LABELS.get(item.severity, item.severity))}</td>'
        f"<td><code>{_esc(item.code)}</code></td>"
        f"<td>{_esc(item.message)}</td>"
        f"<td>{_esc(item.location or '')}</td>"
        "</tr>"
    )


def _esc(text: str) -> str:
    import html as _h

    return _h.escape(text, quote=True)
