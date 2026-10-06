from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from tts_app.text.tables import rows_to_speech

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _paragraph_text(p: ET.Element) -> str:
    parts: list[str] = []
    for el in p.iter():
        if el.tag == f"{_W}t":
            parts.append(el.text or "")
        elif el.tag in (f"{_W}tab", f"{_W}br", f"{_W}cr"):
            parts.append(" ")
    return "".join(parts).strip()


def _cell_text(tc: ET.Element) -> str:
    return " ".join(t for p in tc.iter(f"{_W}p") if (t := _paragraph_text(p)))


def _blocks(parent: ET.Element) -> list[ET.Element]:
    out: list[ET.Element] = []
    for el in parent:
        if el.tag == f"{_W}sdt":
            content = el.find(f"{_W}sdtContent")
            if content is not None:
                out.extend(_blocks(content))
        else:
            out.append(el)
    return out


def read_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{_W}body")
    if body is None:
        return ""
    blocks: list[str] = []
    for el in _blocks(body):
        if el.tag == f"{_W}p":
            text = _paragraph_text(el)
        elif el.tag == f"{_W}tbl":
            rows = [
                [_cell_text(tc) for tc in tr.findall(f"{_W}tc")] for tr in el.findall(f"{_W}tr")
            ]
            text = rows_to_speech(rows)
        else:
            continue
        if text:
            blocks.append(text)
    return "\n".join(blocks)
