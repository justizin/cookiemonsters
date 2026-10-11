"""A deliberately tiny Markdown subset -> HTML converter (headings, paragraphs,
bullet lists, tables, **bold**, `code`, [links](url)). Used for the privacy page
so the server and extension render the same text without a dependency."""

from __future__ import annotations

import html
import re

_INLINE = [
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+|/[^)\s]*|[a-z0-9_./-]+)\)"), r"<a href='\2'>\1</a>"),
]


def _inline(text: str) -> str:
    out = html.escape(text, quote=False)
    for pat, rep in _INLINE:
        out = pat.sub(rep, out)
    return out


def to_html(md: str) -> str:
    blocks: list[str] = []
    para: list[str] = []
    items: list[str] = []
    rows: list[list[str]] = []

    def flush() -> None:
        if para:
            blocks.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()
        if items:
            blocks.append("<ul>" + "".join("<li>" + _inline(i) + "</li>" for i in items) + "</ul>")
            items.clear()
        if rows:
            head, *body = rows
            t = "<table><tr>" + "".join("<th>" + _inline(c) + "</th>" for c in head) + "</tr>"
            for r in body:
                t += "<tr>" + "".join("<td>" + _inline(c) + "</td>" for c in r) + "</tr>"
            blocks.append(t + "</table>")
            rows.clear()

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            flush()
            n = len(m.group(1))
            blocks.append(f"<h{n}>{_inline(m.group(2))}</h{n}>")
        elif line.lstrip().startswith(("- ", "* ")):
            if para:
                flush()
            items.append(line.lstrip()[2:])
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                continue
            rows.append(cells)
        elif items and raw.startswith("  "):
            items[-1] += " " + line.strip()
        else:
            if items:
                flush()
            para.append(line.strip())
    flush()
    return "\n".join(blocks)
