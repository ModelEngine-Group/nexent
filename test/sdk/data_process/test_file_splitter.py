from io import BytesIO

import pytest

pytest.importorskip("ijson")
pytest.importorskip("ebooklib")
pytest.importorskip("openpyxl")
pytest.importorskip("pypdf")

from sdk.nexent.data_process.file_splitter import FileSplitter


def test_file_process_docx_single_part_returns_original(monkeypatch):
    splitter = FileSplitter()
    monkeypatch.setattr(splitter, "_convert_bytes_with_libreoffice", lambda *args, **kwargs: b"pdf-bytes")
    monkeypatch.setattr(splitter, "split_pdf_by_size", lambda *args, **kwargs: [BytesIO(b"one-part")])

    original = b"word-bytes"
    parts = splitter.file_process(original, "sample.docx", max_size=1024)

    assert len(parts) == 1
    assert parts[0].getvalue() == original


def test_file_process_docx_multi_parts_returns_pdf_parts(monkeypatch):
    splitter = FileSplitter()
    expected_parts = [BytesIO(b"p1"), BytesIO(b"p2")]
    monkeypatch.setattr(splitter, "_convert_bytes_with_libreoffice", lambda *args, **kwargs: b"pdf-bytes")
    monkeypatch.setattr(splitter, "split_pdf_by_size", lambda *args, **kwargs: expected_parts)

    parts = splitter.file_process(b"word-bytes", "sample.docx", max_size=128)

    assert parts == expected_parts


def test_file_process_csv_routes_to_split_csv(monkeypatch):
    splitter = FileSplitter()
    captured = {}

    def _fake_split_csv(csv_bytes, max_size, encoding="utf-8"):
        captured["csv_bytes"] = csv_bytes
        captured["max_size"] = max_size
        captured["encoding"] = encoding
        return [BytesIO(b"a")]

    monkeypatch.setattr(splitter, "split_csv_by_size", _fake_split_csv)

    out = splitter.file_process(b"a,b\n1,2\n", "demo.csv", max_size=10, encoding="gbk")

    assert len(out) == 1
    assert captured["csv_bytes"] == b"a,b\n1,2\n"
    assert captured["max_size"] == 10
    assert captured["encoding"] == "gbk"


def test_file_process_unsupported_extension_raises():
    splitter = FileSplitter()
    with pytest.raises(ValueError, match="Unsupported file extension"):
        splitter.file_process(b"abc", "demo.unsupported", max_size=10)
