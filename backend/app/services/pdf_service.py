"""Minimal dependency-free PDF writer for text documents (offer letters, invoices).

Produces a valid multi-page PDF 1.4 using the built-in Helvetica font.
Only Latin-1 characters are representable; others are replaced sensibly.
"""

from __future__ import annotations

import re
import textwrap

_REPLACEMENTS = {"₹": "Rs.", "—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "•": "-", "…": "...", "✓": "v"}


def _latin1(text: str) -> str:
    for k, v in _REPLACEMENTS.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "replace").decode("latin-1")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_pdf(title: str, body: str, footer: str = "") -> bytes:
    width, height, margin, leading = 595, 842, 56, 15
    max_chars = 92
    lines: list[tuple[str, int, bool]] = [(title, 16, True), ("", 11, False)]
    for para in _latin1(body).replace("\r\n", "\n").split("\n"):
        wrapped = textwrap.wrap(para, max_chars) or [""]
        lines.extend((w, 11, False) for w in wrapped)
    per_page = int((height - 2 * margin - 20) / leading)
    pages = [lines[i:i + per_page] for i in range(0, len(lines), per_page)] or [[]]

    objects: list[bytes] = []
    def add(obj: str | bytes) -> int:
        objects.append(obj.encode("latin-1") if isinstance(obj, str) else obj)
        return len(objects)

    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_b = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    pages_id_placeholder = len(objects) + 1
    add("")  # reserved for /Pages
    page_ids = []
    for n, page in enumerate(pages, start=1):
        y = height - margin
        ops = ["BT"]
        for text, size, bold in page:
            ops.append(f"/{'F2' if bold else 'F1'} {size} Tf 1 0 0 1 {margin} {y} Tm ({_escape(_latin1(text))}) Tj")
            y -= leading if size <= 12 else 22
        ft = _escape(_latin1(footer or "")) + (f"   Page {n} of {len(pages)}" if len(pages) > 1 else "")
        ops.append(f"/F1 8 Tf 1 0 0 1 {margin} {margin - 24} Tm ({ft}) Tj")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        page_ids.append(add(f"<< /Type /Page /Parent {pages_id_placeholder} 0 R /MediaBox [0 0 {width} {height}] "
                            f"/Resources << /Font << /F1 {font} 0 R /F2 {font_b} 0 R >> >> /Contents {content} 0 R >>"))
    objects[pages_id_placeholder - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] "
                                          f"/Count {len(page_ids)} >>").encode()
    catalog = add(f"<< /Type /Catalog /Pages {pages_id_placeholder} 0 R >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


# ---------------------------------------------------------------------------
# Formatted letters (offer letters)
# ---------------------------------------------------------------------------
# A small, dependency-free layout engine for letters written in "markdown-lite":
#   # Heading          -> bold section heading
#   **Whole line**     -> bold line
#   - item             -> bullet
#   ---                -> horizontal rule
# Inline **bold** inside a sentence is shown as plain text.

_BOLD_INLINE = re.compile(r"\*\*(.+?)\*\*")


def _wrap(text: str, size: float, max_width: float) -> list[str]:
    max_chars = max(20, int(max_width / (size * 0.5)))   # Helvetica averages ~0.5 em per character
    return textwrap.wrap(text, max_chars) or [""]


def letter_pdf(company: str, letterhead: str, body: str, footer: str = "", accent: tuple = (1.0, 0.773, 0.239)) -> bytes:
    width, height, margin = 595, 842, 60
    usable = width - 2 * margin
    items: list[tuple] = []     # (kind, text, size, bold, indent)
    for raw in _latin1(body).replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        if stripped in ("---", "***", "___"):
            items.append(("rule", "", 0, False, 0))
        elif stripped.startswith("# ") or stripped.startswith("## "):
            items.append(("gap", "", 6, False, 0))
            for w in _wrap(stripped.lstrip("#").strip(), 12.5, usable):
                items.append(("text", w, 12.5, True, 0))
        elif stripped.startswith(("- ", "* ", "• ")):
            text = _BOLD_INLINE.sub(r"\1", stripped[2:].strip())
            for i, w in enumerate(_wrap(text, 10.5, usable - 16)):
                items.append(("bullet" if i == 0 else "text", w, 10.5, False, 16))
        elif stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
            for w in _wrap(stripped[2:-2], 10.5, usable):
                items.append(("text", w, 10.5, True, 0))
        elif not stripped:
            items.append(("gap", "", 7, False, 0))
        else:
            for w in _wrap(_BOLD_INLINE.sub(r"\1", line), 10.5, usable):
                items.append(("text", w, 10.5, False, 0))

    def height_of(item):
        kind, _, size, _, _ = item
        return {"rule": 12, "gap": size}.get(kind, size * 1.45)

    head_h = 92
    pages: list[list[tuple]] = [[]]
    y_space = height - margin - head_h - 40
    used = 0.0
    for it in items:
        h = height_of(it)
        if used + h > y_space and pages[-1]:
            pages.append([]); used = 0.0
            y_space = height - 2 * margin - 30
        pages[-1].append(it); used += h

    objects: list[bytes] = []
    def add(obj) -> int:
        objects.append(obj.encode("latin-1") if isinstance(obj, str) else obj)
        return len(objects)
    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font_b = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pages_id = len(objects) + 1
    add("")
    r, g, b = accent
    page_ids = []
    for n, page in enumerate(pages, start=1):
        ops = []
        y = height - margin
        if n == 1:
            ops.append(f"{r} {g} {b} rg 0 {height - 10} {width} 10 re f")
            ops.append(f"BT /F2 18 Tf 0.07 0.07 0.12 rg 1 0 0 1 {margin} {y - 6} Tm ({_escape(_latin1(company))}) Tj ET")
            if letterhead:
                ops.append(f"BT /F1 8.5 Tf 0.4 0.4 0.45 rg 1 0 0 1 {margin} {y - 22} Tm ({_escape(_latin1(letterhead))}) Tj ET")
            ops.append(f"{r} {g} {b} RG 1.4 w {margin} {y - 34} m {margin + 60} {y - 34} l S")
            ops.append(f"0.85 0.85 0.88 RG 0.6 w {margin + 62} {y - 34} m {width - margin} {y - 34} l S")
            y -= head_h - 30
        for kind, text, size, bold, indent in page:
            h = height_of((kind, text, size, bold, indent))
            if kind == "rule":
                ops.append(f"0.82 0.82 0.86 RG 0.6 w {margin} {y - 5} m {width - margin} {y - 5} l S")
            elif kind in ("text", "bullet"):
                color = "0.07 0.07 0.12 rg" if (bold and size > 11) else "0.15 0.15 0.18 rg"
                if kind == "bullet":
                    ops.append(f"BT /F1 {size} Tf 0.12 0.12 0.15 rg 1 0 0 1 {margin + 4} {y - size} Tm ({_escape(chr(149))}) Tj ET")
                ops.append(f"BT /{'F2' if bold else 'F1'} {size} Tf {color} 1 0 0 1 {margin + indent} {y - size} Tm "
                           f"({_escape(text)}) Tj ET")
            y -= h
        ft = _escape(_latin1(footer or ""))
        ops.append(f"0.88 0.88 0.9 RG 0.5 w {margin} {margin - 8} m {width - margin} {margin - 8} l S")
        ops.append(f"BT /F1 8 Tf 0.45 0.45 0.5 rg 1 0 0 1 {margin} {margin - 22} Tm ({ft}) Tj ET")
        ops.append(f"BT /F1 8 Tf 0.45 0.45 0.5 rg 1 0 0 1 {width - margin - 50} {margin - 22} Tm (Page {n} of {len(pages)}) Tj ET")
        stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        page_ids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {width} {height}] "
                            f"/Resources << /Font << /F1 {font} 0 R /F2 {font_b} 0 R >> >> /Contents {content} 0 R >>"))
    objects[pages_id - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] "
                             f"/Count {len(page_ids)} >>").encode()
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
