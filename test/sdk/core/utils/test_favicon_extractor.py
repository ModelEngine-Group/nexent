import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock, patch

MODULE_NAME = "favicon_extractor_under_test"
MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "sdk"
    / "nexent"
    / "core"
    / "utils"
    / "favicon_extractor.py"
)
spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
favicon_module = importlib.util.module_from_spec(spec)
sys.modules[MODULE_NAME] = favicon_module
assert spec and spec.loader
spec.loader.exec_module(favicon_module)

get_favicon_url = favicon_module.get_favicon_url
check_favicon_exists = favicon_module.check_favicon_exists


def test_get_favicon_url_builds_default():
    assert get_favicon_url("https://example.com/path") == "https://example.com/favicon.ico"


def test_check_favicon_exists_true():
    mock_response = Mock()
    mock_response.status_code = 200
    with patch(f"{MODULE_NAME}.requests.head", return_value=mock_response):
        assert check_favicon_exists("https://example.com/favicon.ico") is True


def test_check_favicon_exists_false_on_error():
    with patch(f"{MODULE_NAME}.requests.head", side_effect=Exception("boom")):
        assert check_favicon_exists("https://example.com/favicon.ico") is False
