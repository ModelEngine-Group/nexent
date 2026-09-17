import importlib.util
from pathlib import Path
from unittest.mock import Mock

import requests


MODULE_PATH = (
    Path(__file__).resolve().parents[4] / "sdk" / "nexent" / "core" / "nlp" / "stopwords.py"
)
SPEC = importlib.util.spec_from_file_location("nexent_stopwords", MODULE_PATH)
assert SPEC and SPEC.loader
stopwords = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stopwords)


def test_download_stopwords_rejects_http_error(monkeypatch, tmp_path):
    response = Mock(text="Not Found")
    response.raise_for_status.side_effect = requests.HTTPError("404 Client Error")
    get = Mock(return_value=response)
    monkeypatch.setattr(stopwords.requests, "get", get)
    target = tmp_path / "stopwords.txt"

    assert (
        stopwords.download_stopwords("https://example.com/missing", str(target))
        is False
    )
    assert not target.exists()
    response.raise_for_status.assert_called_once_with()
