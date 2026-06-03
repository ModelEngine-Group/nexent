import base64
import importlib.util
import os
import subprocess
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace
import zipfile
from xml.etree import ElementTree as ET

import pytest

# Stub heavy optional deps before importing module under test.
fake_pptx = types.ModuleType("pptx")
fake_pptx.Presentation = object
sys.modules.setdefault("pptx", fake_pptx)

fake_unstructured = types.ModuleType("unstructured")
fake_unstructured_partition = types.ModuleType("unstructured.partition")
fake_unstructured_partition_auto = types.ModuleType("unstructured.partition.auto")
fake_unstructured_partition_auto.partition = lambda *a, **k: []
fake_unstructured.partition = fake_unstructured_partition
fake_unstructured_partition.auto = fake_unstructured_partition_auto
sys.modules.setdefault("unstructured", fake_unstructured)
sys.modules.setdefault("unstructured.partition", fake_unstructured_partition)
sys.modules.setdefault("unstructured.partition.auto", fake_unstructured_partition_auto)

fake_unstructured = types.ModuleType("unstructured_inference")
fake_models = types.ModuleType("unstructured_inference.models")
fake_tables = types.ModuleType("unstructured_inference.models.tables")
fake_tables.tables_agent = types.SimpleNamespace(model=None)
fake_logger = types.ModuleType("unstructured_inference.logger")
fake_logger.logger = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None)
fake_models.tables = fake_tables
fake_unstructured.models = fake_models
sys.modules.setdefault("unstructured_inference", fake_unstructured)
sys.modules.setdefault("unstructured_inference.models", fake_models)
sys.modules.setdefault("unstructured_inference.models.tables", fake_tables)
sys.modules.setdefault("unstructured_inference.logger", fake_logger)

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "sdk" / "nexent" / "data_process" / "extract_image.py"
MODULE_NAME = "sdk.nexent.data_process.extract_image"

sdk_pkg = types.ModuleType("sdk")
sdk_pkg.__path__ = [str(REPO_ROOT / "sdk")]
sdk_pkg = sys.modules.setdefault("sdk", sdk_pkg)

nexent_pkg = types.ModuleType("sdk.nexent")
nexent_pkg.__path__ = [str(REPO_ROOT / "sdk" / "nexent")]
nexent_pkg = sys.modules.setdefault("sdk.nexent", nexent_pkg)
sdk_pkg.nexent = nexent_pkg

data_process_pkg = types.ModuleType("sdk.nexent.data_process")
data_process_pkg.__path__ = [str(REPO_ROOT / "sdk" / "nexent" / "data_process")]
data_process_pkg = sys.modules.setdefault("sdk.nexent.data_process", data_process_pkg)
nexent_pkg.data_process = data_process_pkg
spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
extract_image_module = importlib.util.module_from_spec(spec)
sys.modules[MODULE_NAME] = extract_image_module
assert spec and spec.loader
spec.loader.exec_module(extract_image_module)
data_process_pkg.extract_image = extract_image_module

UniversalImageExtractor = extract_image_module.UniversalImageExtractor


def test_detect_image_format_png():
    assert UniversalImageExtractor.detect_image_format(b"\x89PNG\r\n\x1a\n") == "png"


def test_detect_image_format_jpg():
    assert UniversalImageExtractor.detect_image_format(b"\xFF\xD8\xFF\xE0") == "jpg"


def test_detect_image_format_default_png():
    assert UniversalImageExtractor.detect_image_format(b"not-an-image") == "png"


def test_convert_file_success(mocker):
    extractor = UniversalImageExtractor()
    mocker.patch.object(extract_image_module.subprocess, "run")
    mocker.patch.object(extract_image_module.os.path, "exists", return_value=True)
    mocker.patch.object(extract_image_module.os.path, "splitext", return_value=("C:/tmp/file", ".doc"))

    result = extractor._convert_file("C:/tmp/file.doc", "pdf")

    assert result.endswith(".pdf")


def test_convert_file_missing_output(mocker):
    extractor = UniversalImageExtractor()
    mocker.patch.object(extract_image_module.subprocess, "run")
    mocker.patch.object(extract_image_module.os.path, "exists", return_value=False)
    mocker.patch.object(extract_image_module.os.path, "splitext", return_value=("C:/tmp/file", ".doc"))

    with pytest.raises(FileNotFoundError):
        extractor._convert_file("C:/tmp/file.doc", "pdf")


def test_process_file_routes_pdf(mocker, tmp_path):
    extractor = UniversalImageExtractor()
    mocker.patch.object(extractor, "_write_temp_file", return_value=str(tmp_path / "file.pdf"))
    mock_extract = mocker.patch.object(extractor, "_extract_pdf", return_value=[{"image_bytes": b"x"}])

    result = extractor.process_file(b"data", "none", "file.pdf")

    assert result == [{"image_bytes": b"x"}]
    mock_extract.assert_called_once()


def test_process_file_routes_xls_and_ppt(mocker, tmp_path):
    extractor = UniversalImageExtractor()
    mocker.patch.object(extractor, "_write_temp_file", return_value=str(tmp_path / "file.xls"))
    mocker.patch.object(extractor, "_convert_file", return_value=str(tmp_path / "file.xlsx"))
    mock_extract_excel = mocker.patch.object(extractor, "_extract_excel", return_value=[{"image_bytes": b"x"}])

    result = extractor.process_file(b"data", "none", "file.xls")

    assert result == [{"image_bytes": b"x"}]
    mock_extract_excel.assert_called_once_with(str(tmp_path / "file.xlsx"))

    mocker.patch.object(extractor, "_write_temp_file", return_value=str(tmp_path / "file.ppt"))
    mocker.patch.object(extractor, "_convert_file", return_value=str(tmp_path / "file.pptx"))
    mock_extract_ppt = mocker.patch.object(extractor, "_extract_pptx", return_value=[{"image_bytes": b"y"}])

    result = extractor.process_file(b"data", "none", "file.ppt")

    assert result == [{"image_bytes": b"y"}]
    mock_extract_ppt.assert_called_once_with(str(tmp_path / "file.pptx"))


def test_process_file_routes_docx_to_pdf(mocker, tmp_path):
    extractor = UniversalImageExtractor()
    mocker.patch.object(extractor, "_write_temp_file", return_value=str(tmp_path / "file.docx"))
    mocker.patch.object(extractor, "_convert_file", return_value=str(tmp_path / "file.pdf"))
    mock_extract = mocker.patch.object(extractor, "_extract_pdf", return_value=[{"image_bytes": b"x"}])

    result = extractor.process_file(b"data", "none", "file.docx")

    assert result == [{"image_bytes": b"x"}]
    mock_extract.assert_called_once_with(str(tmp_path / "file.pdf"))


def test_process_file_unsupported_extension_returns_empty(mocker, tmp_path):
    extractor = UniversalImageExtractor()
    mocker.patch.object(extractor, "_write_temp_file", return_value=str(tmp_path / "file.txt"))

    result = extractor.process_file(b"data", "none", "file.txt")

    assert result == []


def _build_excel_zip(tmp_path, sheet_xml, sheet_rels=None, drawing_xml=None, drawing_rels=None, image_bytes=b"\x89PNGdata"):
    zip_path = tmp_path / "sample.xlsx"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        if sheet_rels is not None:
            zf.writestr("xl/worksheets/_rels/sheet1.xml.rels", sheet_rels)
        if drawing_xml is not None:
            zf.writestr("xl/drawings/drawing1.xml", drawing_xml)
        if drawing_rels is not None:
            zf.writestr("xl/drawings/_rels/drawing1.xml.rels", drawing_rels)
        if image_bytes is not None:
            zf.writestr("xl/media/image1.png", image_bytes)
    return zip_path


def test_custom_load_table_model_initializes_when_missing(monkeypatch):
    called = []
    fake_agent = SimpleNamespace(model=None, _lock=threading.Lock())

    def initialize(path):
        called.append(path)
        fake_agent.model = object()

    fake_agent.initialize = initialize
    monkeypatch.setattr(extract_image_module, "tables_agent", fake_agent)
    monkeypatch.setattr(extract_image_module, "TABLE_TRANSFORMER_MODEL_PATH", "model-path")

    extract_image_module.custom_load_table_model()

    assert called == ["model-path"]


def test_hash_namespace_write_temp_file(mocker, tmp_path):
    extractor = UniversalImageExtractor()

    assert extractor._hash(b"abc") == __import__("hashlib").sha256(b"abc").hexdigest()
    assert extractor._openxml_namespace_maps()["xdr"].endswith("spreadsheetDrawing")

    temp_path = extractor._write_temp_file(b"hello", ".bin")
    assert Path(temp_path).read_bytes() == b"hello"
    os.remove(temp_path)


def test_convert_file_error_paths(mocker):
    extractor = UniversalImageExtractor()
    mocker.patch.object(
        extract_image_module.subprocess,
        "run",
        side_effect=subprocess.CalledProcessError(1, ["soffice"]),
    )
    with pytest.raises(RuntimeError, match="LibreOffice conversion failed"):
        extractor._convert_file("C:/tmp/file.doc", "pdf")

    mocker.patch.object(
        extract_image_module.subprocess,
        "run",
        side_effect=subprocess.TimeoutExpired(cmd="soffice", timeout=60),
    )
    with pytest.raises(RuntimeError, match="timed out"):
        extractor._convert_file("C:/tmp/file.doc", "pdf")


def test_extract_pdf_paths_and_deduplication(mocker):
    extractor = UniversalImageExtractor()

    assert extractor._extract_pdf("sample.pdf") == []

    png = base64.b64encode(b"\x89PNGdata").decode("ascii")
    jpg = base64.b64encode(b"\xFF\xD8\xFFdata").decode("ascii")

    elements = [
        SimpleNamespace(metadata=SimpleNamespace(image_base64=png, coordinates=SimpleNamespace(points=[(1, 2), (3, 4)]), page_number=1)),
        SimpleNamespace(metadata=SimpleNamespace(image_base64="", coordinates=None, page_number=2)),
        SimpleNamespace(metadata=SimpleNamespace(image_base64=png, coordinates=None, page_number=3)),
        SimpleNamespace(metadata=SimpleNamespace(image_base64=jpg, coordinates=SimpleNamespace(points=[(5, 6), (7, 8)]), page_number=4)),
    ]
    mocker.patch.object(extract_image_module, "partition", return_value=elements)

    result = extractor._extract_pdf(
        "sample.pdf",
        table_transformer_model_path="model-path",
        unstructured_default_model_initialize_params_json_path="init.json",
    )

    assert extract_image_module.TABLE_TRANSFORMER_MODEL_PATH == "model-path"
    assert len(result) == 2
    assert result[0]["position"]["coordinates"] == {"x1": 1, "y1": 2, "x2": 3, "y2": 4}
    assert result[1]["image_format"] == "jpg"


def test_excel_helpers_positive_and_negative_paths(tmp_path):
    extractor = UniversalImageExtractor()
    ns = extractor._openxml_namespace_maps()

    sheet_xml = """
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
               xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
      <drawing r:id="rId1" />
    </worksheet>
    """
    sheet_rels = """
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Target="../drawings/drawing1.xml" />
    </Relationships>
    """
    drawing_xml = """
    <xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
              xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
              xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
      <xdr:twoCellAnchor>
        <xdr:from><xdr:row>0</xdr:row><xdr:col>1</xdr:col></xdr:from>
        <xdr:to><xdr:row>2</xdr:row><xdr:col>3</xdr:col></xdr:to>
        <xdr:pic><xdr:blipFill><a:blip r:embed="rIdImg1" /></xdr:blipFill></xdr:pic>
      </xdr:twoCellAnchor>
      <xdr:oneCellAnchor>
        <xdr:from><xdr:row>4</xdr:row><xdr:col>5</xdr:col></xdr:from>
        <xdr:pic><xdr:blipFill><a:blip r:embed="rIdImg1" /></xdr:blipFill></xdr:pic>
      </xdr:oneCellAnchor>
    </xdr:wsDr>
    """
    drawing_rels = """
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdImg1" Target="../media/image1.png" />
    </Relationships>
    """
    zip_path = _build_excel_zip(tmp_path, sheet_xml, sheet_rels, drawing_xml, drawing_rels)

    with zipfile.ZipFile(zip_path) as zf:
        sheet_files = extractor._excel_sheet_files(zf)
        assert sheet_files == ["xl/worksheets/sheet1.xml"]
        assert extractor._excel_drawing_file(zf, sheet_files[0]) == "xl/drawings/drawing1.xml"
        rel_map = extractor._excel_rel_map(zf, "xl/drawings/drawing1.xml")
        assert rel_map == {"rIdImg1": "xl/media/image1.png"}
        anchors = extractor._excel_anchors(zf, "xl/drawings/drawing1.xml", ns)
        assert len(anchors) == 2
        assert extractor._excel_anchor_coords(anchors[0], ns) == {"row1": 1, "col1": 2, "row2": 3, "col2": 4}
        assert extractor._excel_anchor_coords(anchors[1], ns) == {"row1": 5, "col1": 6, "row2": 5, "col2": 6}
        assert extractor._excel_anchor_embed_id(anchors[0], ns) == "rIdImg1"
        results = extractor._extract_excel_anchors(zf, anchors, rel_map, "sheet1.xml", ns, set())
        assert len(results) == 1
        assert extractor._extract_excel_anchors(zf, [anchors[0]], {}, "sheet1.xml", ns, set()) == []
        assert extractor._extract_excel_sheet(zf, "xl/worksheets/sheet1.xml", ns, set()) == results

    assert extractor._extract_excel(str(zip_path)) == results

    no_drawing_zip = _build_excel_zip(tmp_path, "<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' />")
    with zipfile.ZipFile(no_drawing_zip) as zf:
        assert extractor._excel_drawing_file(zf, "xl/worksheets/sheet1.xml") is None

    bad_sheet_xml = """
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <drawing r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" />
    </worksheet>
    """
    missing_rel_zip = _build_excel_zip(tmp_path, bad_sheet_xml, drawing_xml=drawing_xml, drawing_rels=None)
    with zipfile.ZipFile(missing_rel_zip) as zf:
        assert extractor._excel_drawing_file(zf, "xl/worksheets/sheet1.xml") is None
        assert extractor._excel_rel_map(zf, "xl/drawings/drawing1.xml") is None
        assert extractor._extract_excel_sheet(zf, "xl/worksheets/sheet1.xml", ns, set()) == []

    empty_rel_xml = """
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships" />
    """
    empty_rel_zip = _build_excel_zip(tmp_path, sheet_xml, sheet_rels, drawing_xml, empty_rel_xml)
    with zipfile.ZipFile(empty_rel_zip) as zf:
        assert extractor._extract_excel_sheet(zf, "xl/worksheets/sheet1.xml", ns, set()) == []

    mismatch_sheet_rels = """
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdWrong" Target="../drawings/drawing1.xml" />
    </Relationships>
    """
    mismatch_zip = _build_excel_zip(tmp_path, sheet_xml, mismatch_sheet_rels, drawing_xml, drawing_rels)
    with zipfile.ZipFile(mismatch_zip) as zf:
        assert extractor._excel_drawing_file(zf, "xl/worksheets/sheet1.xml") is None

    anchor_no_from = ET.fromstring(
        '<xdr:twoCellAnchor xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" />'
    )
    assert extractor._excel_anchor_coords(anchor_no_from, ns) is None

    anchor_no_blip = ET.fromstring(
        '<xdr:twoCellAnchor xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing">'
        '<xdr:from><xdr:row>0</xdr:row><xdr:col>0</xdr:col></xdr:from>'
        '</xdr:twoCellAnchor>'
    )
    assert extractor._excel_anchor_embed_id(anchor_no_blip, ns) is None

    empty_anchors = [
        anchor_no_from,
        anchor_no_blip,
    ]
    assert extractor._extract_excel_anchors(zf, empty_anchors, {}, "sheet1.xml", ns, set()) == []


def test_pptx_extraction_paths(monkeypatch):
    extractor = UniversalImageExtractor()

    monkeypatch.setattr(extract_image_module, "Presentation", None)
    with pytest.raises(RuntimeError, match="python-pptx is required"):
        extractor._extract_pptx("sample.pptx")

    class FakeShape:
        def __init__(self, blob=None):
            if blob is not None:
                self.image = SimpleNamespace(blob=blob)
            self.left = 914400
            self.top = 914400
            self.width = 914400
            self.height = 914400

    class FakeSlide:
        def __init__(self):
            self.shapes = [SimpleNamespace(), FakeShape(b"\x89PNGdata"), FakeShape(b"\x89PNGdata")]

    class FakePresentation:
        def __init__(self, path):
            self.slide_width = 914400 * 10
            self.slide_height = 914400 * 5
            self.slides = [FakeSlide()]

    monkeypatch.setattr(extract_image_module, "Presentation", FakePresentation)
    result = extractor._extract_pptx("sample.pptx")
    assert len(result) == 1
    assert result[0]["position"]["coordinates"]["x1"] == 96
    assert result[0]["position"]["coordinates"]["slide_width"] == 960


def test_process_file_direct_and_cleanup_paths(mocker, tmp_path):
    extractor = UniversalImageExtractor()

    mocker.patch.object(extractor, "_write_temp_file", side_effect=[str(tmp_path / "file.xlsx"), str(tmp_path / "file.pptx"), str(tmp_path / "file.doc")])
    mocker.patch.object(extractor, "_extract_excel", return_value=[{"image_bytes": b"x"}])
    mocker.patch.object(extractor, "_extract_pptx", return_value=[{"image_bytes": b"y"}])

    assert extractor.process_file(b"data", "none", "file.xlsx") == [{"image_bytes": b"x"}]
    assert extractor.process_file(b"data", "none", "file.pptx") == [{"image_bytes": b"y"}]

    mocker.patch.object(extractor, "_convert_file", return_value=str(tmp_path / "file.pdf"))
    mocker.patch.object(extractor, "_extract_pdf", return_value=[{"image_bytes": b"z"}])
    mocker.patch.object(extract_image_module.os.path, "exists", return_value=True)

    removed = []

    def remove_side_effect(path):
        removed.append(path)
        if len(removed) == 1:
            raise Exception("cleanup boom")

    mocker.patch.object(extract_image_module.os, "remove", side_effect=remove_side_effect)

    assert extractor.process_file(b"data", "none", "file.doc") == [{"image_bytes": b"z"}]
    assert str(tmp_path / "file.doc") in removed
    assert str(tmp_path / "file.pdf") in removed
