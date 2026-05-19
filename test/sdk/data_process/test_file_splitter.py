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


def test_split_txt_by_size_basic():
    splitter = FileSplitter()
    data = b"line1\nline2\nline3\n"
    parts = splitter.split_txt_by_size(data, max_size=8)
    assert len(parts) >= 2
    assert b"line1\n" in parts[0].getvalue()


def test_split_json_stream_and_batch_bytes():
    splitter = FileSplitter()
    json_bytes = b'[{"a":1},{"a":2},{"a":3}]'
    parts = splitter.split_json_stream(json_bytes, max_size=10)
    assert len(parts) >= 2
    assert splitter._json_bytes_from_batch([{"x": 1}]).startswith(b"[")


def test_split_xml_by_size():
    splitter = FileSplitter()
    xml_bytes = b"<root><a>1</a><b>2</b><c>3</c></root>"
    parts = splitter.split_xml_by_size(xml_bytes, max_size=20)
    assert len(parts) >= 2


def test_split_csv_by_size_empty_and_small():
    splitter = FileSplitter()
    assert splitter.split_csv_by_size(b"", max_size=10) == []
    out = splitter.split_csv_by_size(b"h1,h2\n1,2\n", max_size=1024)
    assert len(out) == 1


def test_split_excel_small_returns_original():
    splitter = FileSplitter()
    out = splitter.split_excel(b"abc", max_size=9999)
    assert len(out) == 1
    assert out[0].getvalue() == b"abc"


def test_split_pdf_by_size(monkeypatch):
    splitter = FileSplitter()

    class FakeReader:
        def __init__(self, *_a, **_k):
            self.pages = [object(), object(), object()]

    class FakeWriter:
        def __init__(self):
            self.pages = []

        def add_page(self, p):
            self.pages.append(p)

        def write(self, buffer):
            buffer.write(b"x" * (50 * max(1, len(self.pages))))

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)
    monkeypatch.setattr("pypdf.PdfWriter", FakeWriter)
    out = splitter.split_pdf_by_size(b"%PDF", max_size=60)
    assert len(out) >= 2


def test_split_epub_by_size(monkeypatch):
    splitter = FileSplitter()

    class Doc:
        def __init__(self, n):
            self.n = n

        def get_name(self):
            return f"n{self.n}"

        def get_content(self):
            return f"c{self.n}".encode()

    class Book:
        def get_items_of_type(self, _):
            return [Doc(1), Doc(2), Doc(3)]

        def get_metadata(self, *_a):
            return [("title", {})]

    monkeypatch.setattr("ebooklib.epub.read_epub", lambda *_a, **_k: Book())

    def _write_epub(buffer, new_book):
        sz = max(10, len(getattr(new_book, "spine", [])) * 80)
        buffer.write(b"x" * sz)

    monkeypatch.setattr("ebooklib.epub.write_epub", _write_epub)
    out = splitter.split_epub_by_size(b"epub", max_size=100)
    assert len(out) >= 2


def test_copy_images_safe_branches(monkeypatch):
    splitter = FileSplitter()
    added = []

    class WS:
        def __init__(self, images):
            self._images = images

        def add_image(self, img, anchor):
            added.append((img, anchor))

    class Img:
        anchor = "A1"

        def _data(self):
            return b"img"

    monkeypatch.setattr("openpyxl.drawing.image.Image", lambda bio: object())
    splitter.copy_images_safe(WS([Img()]), WS([]))
    assert len(added) == 1


def test_split_excel_empty_sheet_returns_empty(monkeypatch):
    splitter = FileSplitter()

    class WS:
        def iter_rows(self, values_only=True):
            return iter([])

    class WB:
        sheetnames = ["s1"]

        def __getitem__(self, k):
            return WS()

    monkeypatch.setattr("openpyxl.load_workbook", lambda *_a, **_k: WB())
    assert splitter.split_excel(b"x" * 100, max_size=10) == []


def test_split_markdown_recursive(monkeypatch):
    splitter = FileSplitter()

    class Doc:
        def __init__(self, text, meta):
            self.page_content = text
            self.metadata = meta

    class Splitter:
        def __init__(self, headers_to_split_on):
            self.headers = headers_to_split_on

        def split_text(self, content):
            if "##" in content:
                return [Doc("p1", {"h2": "H2A"}), Doc("p2", {"h2": "H2B"})]
            return [Doc(content, {})]

    monkeypatch.setattr("langchain_text_splitters.MarkdownHeaderTextSplitter", Splitter)
    out = splitter.split_markdown(b"## T\ntext\n## K\nbody", max_size=8)
    assert len(out) >= 2


def test_convert_bytes_with_libreoffice(monkeypatch, tmp_path):
    splitter = FileSplitter()
    work = tmp_path / "w"
    work.mkdir()
    out_file = work / "input.pdf"
    out_file.write_bytes(b"pdf")

    class TDir:
        def __enter__(self):
            return str(work)

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("sdk.nexent.data_process.file_splitter.tempfile.TemporaryDirectory", lambda: TDir())
    monkeypatch.setattr("sdk.nexent.data_process.file_splitter.subprocess.run", lambda *a, **k: None)
    data = splitter._convert_bytes_with_libreoffice(b"doc", ".docx", ".pdf")
    assert data == b"pdf"


def test_split_excel_grouping_and_rows(monkeypatch):
    splitter = FileSplitter()

    class WS:
        def __init__(self, rows):
            self._rows = rows

        def iter_rows(self, values_only=True):
            return iter(self._rows)

    class WBIn:
        sheetnames = ["s1"]

        def __getitem__(self, key):
            return WS([("h1", "h2"), ("a", "1"), ("b", "2"), ("c", "3")])

    class WSOut:
        def __init__(self):
            self.rows = []

        def append(self, row):
            self.rows.append(row)

    class WBOut:
        def __init__(self):
            self.active = object()
            self.saved = []

        def remove(self, _):
            return None

        def create_sheet(self, title):
            return WSOut()

        def save(self, buffer):
            buffer.write(b"xlsx")

    monkeypatch.setattr("openpyxl.load_workbook", lambda *_a, **_k: WBIn())
    monkeypatch.setattr("openpyxl.Workbook", WBOut)
    monkeypatch.setattr(splitter, "copy_images_safe", lambda *_a, **_k: None)
    out = splitter.split_excel(b"x" * 100, max_size=30)
    assert len(out) >= 2


def test_copy_images_safe_handles_data_fail(monkeypatch):
    splitter = FileSplitter()

    class WS:
        def __init__(self):
            self._images = [Img()]
            self.added = 0

        def add_image(self, *_a, **_k):
            self.added += 1

    class Img:
        anchor = "A1"

        def _data(self):
            raise RuntimeError("no data")

    src = WS()
    dst = WS()
    splitter.copy_images_safe(src, dst)
    assert dst.added == 0


def test_convert_bytes_with_libreoffice_no_output_raises(monkeypatch, tmp_path):
    splitter = FileSplitter()
    work = tmp_path / "w2"
    work.mkdir()

    class TDir:
        def __enter__(self):
            return str(work)

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("sdk.nexent.data_process.file_splitter.tempfile.TemporaryDirectory", lambda: TDir())
    monkeypatch.setattr("sdk.nexent.data_process.file_splitter.subprocess.run", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="produced no output"):
        splitter._convert_bytes_with_libreoffice(b"doc", ".docx", ".pdf")
