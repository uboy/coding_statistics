from pathlib import Path

from stats_core.export import word as word_export, excel as excel_export


def test_word_export(tmp_path: Path) -> None:
    sections = [
        {
            "title": "Section A",
            "headers": ["Name", "Value"],
            "rows": [["foo", "bar"], ["baz", "qux"]],
        }
    ]
    output = tmp_path / "report.docx"
    word_export.export_report(output, sections)
    assert output.exists()
    assert output.stat().st_size > 0


def test_excel_export(tmp_path: Path) -> None:
    headers = ["A", "B"]
    rows = [["foo", "bar"], ["baz", "qux"]]
    output = tmp_path / "report.xlsx"
    excel_export.export_sheet(output, "Sheet1", headers, rows)
    assert output.exists()
    assert output.stat().st_size > 0

