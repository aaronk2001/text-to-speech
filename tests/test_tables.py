from __future__ import annotations

import zipfile
from pathlib import Path

from PySide6.QtCore import QMimeData

from tts_app.text.docx import read_docx
from tts_app.text.tables import rows_to_speech, tsv_to_speech
from tts_app.ui.widgets import ReadingTextEdit


def test_rows_read_as_header_value_pairs() -> None:
    rows = [["Name", "Age", "City"], ["Alice", "30", "Tempe"], ["Bob", "", "Mesa."]]
    assert rows_to_speech(rows) == (
        "Row 1. Name: Alice. Age: 30. City: Tempe.\nRow 2. Name: Bob. City: Mesa."
    )


def test_single_row_and_single_column_read_plainly() -> None:
    assert rows_to_speech([["A", "B"]]) == "A, B."
    assert rows_to_speech([["A"], ["B"]]) == "A.\nB."
    assert rows_to_speech([["", ""]]) == ""


def test_tsv_block_inside_prose() -> None:
    text = "Scores below.\nName\tScore\nAlice\t9\r\nBob\t7\nThat's all."
    assert tsv_to_speech(text) == (
        "Scores below.\nRow 1. Name: Alice. Score: 9.\nRow 2. Name: Bob. Score: 7.\nThat's all."
    )


def test_text_without_tabs_untouched() -> None:
    assert tsv_to_speech("Hello.\r\n") == "Hello.\r\n"


def _docx(path: Path, body: str) -> Path:
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
    return path


def _p(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _row(*cells: str) -> str:
    return "<w:tr>" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in cells) + "</w:tr>"


def test_docx_keeps_tables_in_document_order(tmp_path: Path) -> None:
    body = (
        _p("Intro.")
        + "<w:tbl>" + _row("Item", "Qty") + _row("Bolts", "12") + "</w:tbl>"
        + "<w:p/>"
        + _p("Outro.")
    )
    path = _docx(tmp_path / "t.docx", body)
    assert read_docx(path) == "Intro.\nRow 1. Item: Bolts. Qty: 12.\nOutro."


def test_paste_converts_tsv(qtbot) -> None:  # type: ignore[no-untyped-def]
    edit = ReadingTextEdit()
    qtbot.addWidget(edit)
    mime = QMimeData()
    mime.setText("A\tB\n1\t2")
    edit.insertFromMimeData(mime)
    assert edit.toPlainText() == "Row 1. A: 1. B: 2."
