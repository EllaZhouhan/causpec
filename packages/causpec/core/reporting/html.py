"""The report as a web page, for a reader who has no Markdown viewer.

**Why this exists.** The report is Markdown, which is right for a file that has to be
diffed, grepped and kept next to the run that produced it. It is wrong for the moment a
clinician double-clicks it: `open report.md` hands the file to whatever that machine
associates with `.md`, which may be a text editor, may be nothing, and on a colleague's
laptop is a coin toss. A browser is the one renderer everyone has.

**Why it is written here rather than taken from a library.** The input is not arbitrary
Markdown. It is the output of `report.py`, which emits a fixed set of constructs: headings,
paragraphs, bullet lists one level deep, pipe tables, blockquotes, fenced code, mermaid
blocks, horizontal rules, bold, and inline code. A converter for exactly that is short
enough to read in one sitting, and the alternative is a dependency, plus its transitive
dependencies, for one artefact. Anything this does not recognise is emitted as a paragraph
with its characters escaped, so an unexpected construct degrades to visible text rather
than disappearing.

**The mermaid diagram** is emitted as `<pre class="mermaid">`, which mermaid's own script
converts in place. The script comes from a CDN, so with no network the browser shows the
diagram's source instead of a picture: a reader sees the roles either way, which is the
point of having the diagram at all.
"""

from __future__ import annotations

import html
import re

BOLD = re.compile(r"\*\*(.+?)\*\*")
CODE = re.compile(r"`([^`]+)`")
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET = re.compile(r"^(\s*)[-*]\s+(.*)$")
TABLE_DIVIDER = re.compile(r"^\|[\s:|-]+\|$")

STYLE = """
:root { color-scheme: light dark; }
body {
  margin: 0 auto; padding: 2.5rem 1.25rem 6rem; max-width: 46rem;
  font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, sans-serif;
  color: #1a1a1a; background: #fdfdfc;
}
h1 { font-size: 1.75rem; line-height: 1.25; margin: 0 0 1.5rem; }
h2 {
  font-size: 1.25rem; margin: 2.5rem 0 0.75rem;
  padding-top: 0.75rem; border-top: 1px solid #e4e4e0;
}
h3 { font-size: 1.05rem; margin: 1.75rem 0 0.5rem; }
p, li { overflow-wrap: break-word; }
code { font-size: 0.9em; background: #f1f1ee; padding: 0.1em 0.3em; border-radius: 3px; }
pre { background: #f1f1ee; padding: 0.9rem; border-radius: 4px; overflow-x: auto; }
pre code { background: none; padding: 0; }
blockquote {
  margin: 1.25rem 0; padding: 0.1rem 1rem; border-left: 3px solid #c9c9c2; color: #444;
}
table {
  border-collapse: collapse; width: 100%; margin: 1.25rem 0; font-size: 0.93rem;
  display: block; overflow-x: auto;
}
th, td {
  border: 1px solid #e0e0db; padding: 0.45rem 0.6rem; text-align: left; vertical-align: top;
}
th { background: #f6f6f3; font-weight: 600; }
hr { border: 0; border-top: 1px solid #e4e4e0; margin: 2rem 0; }
a { color: #2d5ea8; }
.mermaid { background: #fdfdfc; border: 1px solid #e4e4e0; }
@media (prefers-color-scheme: dark) {
  body { color: #e8e8e5; background: #16161a; }
  h2, hr { border-color: #30303a; }
  code, pre, th { background: #22222a; }
  th, td { border-color: #30303a; }
  blockquote { border-color: #44444e; color: #b9b9b5; }
  .mermaid { background: #16161a; border-color: #30303a; }
  a { color: #8ab4f8; }
}
"""

MERMAID_SCRIPT = (
    '<script type="module">\n'
    "  import mermaid from "
    '"https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs";\n'
    '  mermaid.initialize({ startOnLoad: true, theme: "neutral" });\n'
    "</script>"
)


def _inline(text: str) -> str:
    """Escape, then put back the four inline constructs the report uses."""
    escaped = html.escape(text, quote=False)
    escaped = CODE.sub(lambda m: f"<code>{m.group(1)}</code>", escaped)
    escaped = BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", escaped)
    escaped = LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', escaped)
    return escaped


def _table_row(line: str, cell: str) -> str:
    # A table cell can hold an escaped pipe, which must survive the split that finds the
    # cells. The report escapes it for exactly this reason, "max |SMD|" being a real
    # example, so the split has to respect the backslash.
    parts = re.split(r"(?<!\\)\|", line.strip())
    cells = [part.replace("\\|", "|").strip() for part in parts[1:-1]]
    rendered = "".join(f"<{cell}>{_inline(value)}</{cell}>" for value in cells)
    return f"<tr>{rendered}</tr>"


def to_html(markdown: str, title: str = "CauSpec report") -> str:
    """One self-contained page. No external CSS, no fonts, nothing to install."""
    # The question is a folded YAML scalar, so it arrives with newlines in it and a browser
    # tab is one line.
    title = " ".join(title.split()) or "CauSpec report"
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    needs_mermaid = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Comments pass through, so the provenance header of a committed example survives.
        if stripped.startswith("<!--"):
            block = [line]
            while "-->" not in block[-1] and i + 1 < len(lines):
                i += 1
                block.append(lines[i])
            out.append("\n".join(block))
            i += 1
            continue

        if stripped.startswith("```"):
            language = stripped[3:].strip()
            fenced: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                fenced.append(lines[i])
                i += 1
            i += 1
            text = html.escape("\n".join(fenced), quote=False)
            if language == "mermaid":
                needs_mermaid = True
                out.append(f'<pre class="mermaid">{text}</pre>')
            else:
                out.append(f"<pre><code>{text}</code></pre>")
            continue

        if stripped in {"---", "***", "___"}:
            out.append("<hr>")
            i += 1
            continue

        heading = HEADING.match(stripped)
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        if stripped.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            head = [row for row in rows[:1] if not TABLE_DIVIDER.match(row.strip())]
            body_rows = [row for row in rows[1:] if not TABLE_DIVIDER.match(row.strip())]
            parts = ["<table>"]
            if head:
                parts.append(f"<thead>{_table_row(head[0], 'th')}</thead>")
            if body_rows:
                cells = "".join(_table_row(row, "td") for row in body_rows)
                parts.append(f"<tbody>{cells}</tbody>")
            parts.append("</table>")
            out.append("".join(parts))
            continue

        if stripped.startswith(">"):
            quoted: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quoted.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(f"<blockquote><p>{_inline(' '.join(quoted).strip())}</p></blockquote>")
            continue

        bullet = BULLET.match(line)
        if bullet:
            items: list[tuple[int, str]] = []
            while i < len(lines):
                match = BULLET.match(lines[i])
                if match:
                    items.append((len(match.group(1)), match.group(2)))
                    i += 1
                elif lines[i].strip() and lines[i].startswith(("  ", "\t")) and items:
                    # A wrapped continuation line belongs to the item above it.
                    depth, text = items[-1]
                    items[-1] = (depth, f"{text} {lines[i].strip()}")
                    i += 1
                else:
                    break
            out.append(_list_html(items))
            continue

        # A paragraph: consecutive non-blank lines that start no other construct.
        paragraph = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip() or nxt.strip().startswith(("|", ">", "#", "```", "-", "*")):
                break
            paragraph.append(nxt.strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(paragraph))}</p>")

    page_body = "\n".join(out)
    script = f"\n{MERMAID_SCRIPT}" if needs_mermaid else ""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title, quote=False)}</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n{page_body}\n</body>{script}\n</html>\n"
    )


def _list_html(items: list[tuple[int, str]]) -> str:
    """A bullet list, one level of nesting, which is all the report emits."""
    base = min(depth for depth, _ in items)
    parts: list[str] = ["<ul>"]
    nested = False
    for depth, text in items:
        if depth > base and not nested:
            parts.append("<ul>")
            nested = True
        elif depth == base and nested:
            parts.append("</ul>")
            nested = False
        parts.append(f"<li>{_inline(text)}</li>")
    if nested:
        parts.append("</ul>")
    parts.append("</ul>")
    return "".join(parts)
