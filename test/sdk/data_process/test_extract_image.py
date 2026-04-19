import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "sdk" / "nexent" / "data_process" / "extract_image.py"
MODULE_NAME = "sdk.nexent.data_process.extract_image"

sdk_pkg = types.ModuleType("sdk")
sdk_pkg.__path__ = [str(REPO_ROOT / "sdk")]
sys.modules.setdefault("sdk", sdk_pkg)

nexent_pkg = types.ModuleType("sdk.nexent")
nexent_pkg.__path__ = [str(REPO_ROOT / "sdk" / "nexent")]
sys.modules.setdefault("sdk.nexent", nexent_pkg)
sdk_pkg.nexent = nexent_pkg

data_process_pkg = types.ModuleType("sdk.nexent.data_process")
data_process_pkg.__path__ = [str(REPO_ROOT / "sdk" / "nexent" / "data_process")]
sys.modules.setdefault("sdk.nexent.data_process", data_process_pkg)
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
    mocker.patch(f"{MODULE_NAME}.subprocess.run")
    mocker.patch(f"{MODULE_NAME}.os.path.exists", return_value=True)
    mocker.patch(f"{MODULE_NAME}.os.path.splitext", return_value=("C:/tmp/file", ".doc"))

    result = extractor._convert_file("C:/tmp/file.doc", "pdf")

    assert result.endswith(".pdf")


def test_convert_file_missing_output(mocker):
    extractor = UniversalImageExtractor()
    mocker.patch(f"{MODULE_NAME}.subprocess.run")
    mocker.patch(f"{MODULE_NAME}.os.path.exists", return_value=False)
    mocker.patch(f"{MODULE_NAME}.os.path.splitext", return_value=("C:/tmp/file", ".doc"))

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
