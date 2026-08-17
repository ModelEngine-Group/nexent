from io import BytesIO
import sys
import types

import pytest

pytest.importorskip("ijson")
pytest.importorskip("openpyxl")
pytest.importorskip("pypdf")

fake_unstructured = types.ModuleType("unstructured_inference")
fake_models = types.ModuleType("unstructured_inference.models")
fake_tables = types.ModuleType("unstructured_inference.models.tables")
fake_tables.tables_agent = types.SimpleNamespace(model=None)
fake_logger = types.ModuleType("unstructured_inference.logger")
fake_logger.logger = types.SimpleNamespace(
    info=lambda *args, **kwargs: None,
    warning=lambda *args, **kwargs: None,
    error=lambda *args, **kwargs: None,
)
fake_models.tables = fake_tables
fake_unstructured.models = fake_models
fake_partition = types.ModuleType("unstructured.partition")
fake_partition_auto = types.ModuleType("unstructured.partition.auto")
fake_partition_auto.partition = lambda *args, **kwargs: []
fake_partition.auto = fake_partition_auto
sys.modules.setdefault("unstructured_inference", fake_unstructured)
sys.modules.setdefault("unstructured_inference.models", fake_models)
sys.modules.setdefault("unstructured_inference.models.tables", fake_tables)
sys.modules.setdefault("unstructured_inference.logger", fake_logger)
sys.modules.setdefault("unstructured", types.ModuleType("unstructured"))
sys.modules.setdefault("unstructured.partition", fake_partition)
sys.modules.setdefault("unstructured.partition.auto", fake_partition_auto)

from sdk.nexent.data_process.file_splitter import FileSplitter


def test_split_csv_recursively_preserves_header_and_rows():
    splitter = FileSplitter()
    source = b"name,value\nalpha,111111\nbeta,222222\ngamma,333333\n"

    parts = splitter.split_csv_by_size(source, max_size=25)

    assert len(parts) == 3
    assert all(part.getvalue().startswith(b"name,value") for part in parts)
    assert b"alpha,111111" in parts[0].getvalue()
    assert b"gamma,333333" in parts[-1].getvalue()


def test_copy_images_safe_ignores_image_construction_failure(monkeypatch):
    splitter = FileSplitter()

    class ImageSource:
        anchor = "A1"

        def _data(self):
            return b"invalid-image"

    destination = types.SimpleNamespace(add_image=lambda *args: pytest.fail("image should not be added"))
    monkeypatch.setattr(
        "openpyxl.drawing.image.Image",
        lambda _buffer: (_ for _ in ()).throw(ValueError("invalid image")),
    )

    splitter.copy_images_safe(types.SimpleNamespace(_images=[ImageSource()]), destination)


def test_split_excel_skips_blank_header_sheet(monkeypatch):
    splitter = FileSplitter()

    class Worksheet:
        def iter_rows(self, values_only=True):
            return iter([(None, None)])

    class Workbook:
        sheetnames = ["blank"]

        def __getitem__(self, _name):
            return Worksheet()

    monkeypatch.setattr("openpyxl.load_workbook", lambda *args, **kwargs: Workbook())

    assert splitter.split_excel(b"x" * 20, max_size=5) == []


def test_split_markdown_without_headers_recurses_to_terminal_level(monkeypatch):
    splitter = FileSplitter()

    class Document:
        page_content = "plain content"
        metadata = {}

    class MarkdownSplitter:
        def __init__(self, headers_to_split_on):
            self.headers_to_split_on = headers_to_split_on

        def split_text(self, _content):
            return [Document()]

    monkeypatch.setattr("langchain_text_splitters.MarkdownHeaderTextSplitter", MarkdownSplitter)

    parts = splitter.split_markdown(b"plain content", max_size=3)

    assert [part.getvalue() for part in parts] == [b"plain content"]


def test_split_markdown_rebuilds_parent_header(monkeypatch):
    splitter = FileSplitter()

    class Document:
        def __init__(self, content, metadata):
            self.page_content = content
            self.metadata = metadata

    class MarkdownSplitter:
        def __init__(self, headers_to_split_on):
            self.level = len(headers_to_split_on[0][0])

        def split_text(self, content):
            if self.level == 2:
                return [
                    Document("first", {"h2": "One"}),
                    Document("second", {"h2": "Two"}),
                ]
            return [Document(content, {})]

    monkeypatch.setattr("langchain_text_splitters.MarkdownHeaderTextSplitter", MarkdownSplitter)

    parts = splitter.split_markdown(b"## One\nfirst\n## Two\nsecond", max_size=8)

    assert parts[0].getvalue().startswith(b"## One\n")
    assert parts[1].getvalue().startswith(b"## Two\n")


def test_split_pdf_by_parts_returns_empty_for_document_without_pages(monkeypatch):
    splitter = FileSplitter()
    monkeypatch.setattr("pypdf.PdfReader", lambda _buffer: types.SimpleNamespace(pages=[]))

    assert splitter.split_pdf_by_parts(b"%PDF", target_parts=2) == []


def test_convert_bytes_with_libreoffice_uses_discovered_output(monkeypatch, tmp_path):
    splitter = FileSplitter()
    output_file = tmp_path / "converted.PDF"

    class TemporaryDirectory:
        def __enter__(self):
            return str(tmp_path)

        def __exit__(self, *args):
            return False

    def run_conversion(*args, **kwargs):
        output_file.write_bytes(b"converted")

    monkeypatch.setattr(
        "sdk.nexent.data_process.file_splitter.tempfile.TemporaryDirectory",
        lambda: TemporaryDirectory(),
    )
    monkeypatch.setattr("sdk.nexent.data_process.file_splitter.subprocess.run", run_conversion)

    result = splitter._convert_bytes_with_libreoffice(b"source", ".docx", ".pdf")

    assert result == b"converted"


def test_file_process_pdf_with_target_parts_uses_part_splitter(monkeypatch):
    splitter = FileSplitter()
    expected = [BytesIO(b"one"), BytesIO(b"two")]
    captured = {}

    def split_by_parts(file_data, target_parts):
        captured.update(file_data=file_data, target_parts=target_parts)
        return expected

    monkeypatch.setattr(splitter, "split_pdf_by_parts", split_by_parts)

    result = splitter.file_process(b"%PDF", "report.pdf", target_parts=2)

    assert result == expected
    assert captured == {"file_data": b"%PDF", "target_parts": 2}
