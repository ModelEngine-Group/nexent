import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest


def _load_aidp_client_module():
    repo_root = Path(__file__).resolve().parents[4]
    sdk_root = repo_root / "sdk" / "nexent"
    package_dir = sdk_root / "core" / "knowledge_base"
    packages = {
        "nexent": sdk_root,
        "nexent.core": sdk_root / "core",
        "nexent.core.knowledge_base": package_dir,
        "nexent.utils": sdk_root / "utils",
    }
    for name, path in packages.items():
        module = sys.modules.get(name) or types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module

    for module_name, path in {
        "nexent.utils.http_client_manager": sdk_root / "utils" / "http_client_manager.py",
        "nexent.core.knowledge_base.config": package_dir / "config.py",
        "nexent.core.knowledge_base.aidp_client": package_dir / "aidp_client.py",
    }.items():
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return sys.modules["nexent.core.knowledge_base.aidp_client"]


aidp_client_module = _load_aidp_client_module()
AidpAdapterError = aidp_client_module.AidpAdapterError
AidpClient = aidp_client_module.AidpClient


def _response(status_code: int, body: dict) -> httpx.Response:
    request = httpx.Request("GET", "https://aidp.example.com/resource")
    return httpx.Response(status_code, content=json.dumps(body), request=request)


@pytest.fixture
def client() -> AidpClient:
    aidp_client = AidpClient.__new__(AidpClient)
    aidp_client.base_url = "https://aidp.example.com"
    aidp_client._client = MagicMock()
    return aidp_client


def test_request_retries_non_200_until_a_200_response(client: AidpClient):
    client._client.request.side_effect = [
        _response(503, {"message": "unavailable"}),
        _response(429, {"message": "busy"}),
        _response(200, {"value": "ok"}),
    ]

    with patch.object(aidp_client_module, "time", create=True) as time_module:
        sleep = time_module.sleep
        result = client._request("GET", "/resource")

    assert result == {"value": "ok"}
    assert client._client.request.call_count == 3
    assert sleep.call_args_list == [((1,),), ((2,),)]


def test_request_raises_final_non_200_after_four_attempts(client: AidpClient):
    client._client.request.return_value = _response(503, {"message": "unavailable"})

    with patch.object(aidp_client_module, "time", create=True) as time_module:
        sleep = time_module.sleep
        with pytest.raises(AidpAdapterError) as error:
            client._request("GET", "/resource")

    assert error.value.status_code == 503
    assert error.value.response_body == {"message": "unavailable"}
    assert client._client.request.call_count == 4
    assert sleep.call_args_list == [((1,),), ((2,),), ((4,),)]


def test_request_retries_request_errors_until_a_200_response(client: AidpClient):
    client._client.request.side_effect = [
        httpx.ConnectError("offline"),
        _response(200, {"value": "ok"}),
    ]

    with patch.object(aidp_client_module, "time", create=True) as time_module:
        sleep = time_module.sleep
        result = client._request("GET", "/resource")

    assert result == {"value": "ok"}
    assert client._client.request.call_count == 2
    sleep.assert_called_once_with(1)


def test_request_does_not_retry_a_200_response(client: AidpClient):
    client._client.request.return_value = _response(200, {"value": "ok"})

    with patch.object(aidp_client_module, "time", create=True) as time_module:
        sleep = time_module.sleep
        result = client._request("GET", "/resource")

    assert result == {"value": "ok"}
    client._client.request.assert_called_once()
    sleep.assert_not_called()
