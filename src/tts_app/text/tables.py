from __future__ import annotations


def _clean(cell: str) -> str:
    return " ".join(cell.split()).rstrip(".")


def rows_to_speech(rows: list[list[str]]) -> str:
    rows = [[_clean(c) for c in row] for row in rows]
    rows = [row for row in rows if any(row)]
    if not rows:
        return ""
    if len(rows) == 1 or max(len(r) for r in rows) == 1:
        return "\n".join(", ".join(c for c in row if c) + "." for row in rows)
    header, *body = rows
    lines = []
    for n, row in enumerate(body, 1):
        pairs = [
            f"{header[i]}: {cell}" if i < len(header) and header[i] else cell
            for i, cell in enumerate(row)
            if cell
        ]
        lines.append(f"Row {n}. " + ". ".join(pairs) + ".")
    return "\n".join(lines)


def tsv_to_speech(text: str) -> str:
    """Rewrite each run of tab-separated lines (a table pasted from Excel or a web page)."""
    if "\t" not in text:
        return text
    out: list[str] = []
    block: list[list[str]] = []
    for line in text.splitlines():
        if "\t" in line:
            block.append(line.split("\t"))
            continue
        if block:
            out.append(rows_to_speech(block))
            block = []
        out.append(line)
    if block:
        out.append(rows_to_speech(block))
    return "\n".join(out)
