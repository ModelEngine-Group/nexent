# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Service configuration, pure protocol and minimal-source startup boundaries."""

import ast
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gateway.configuration import GatewaySettings, load_settings
from gateway.security.identity import IdentityError, derive_signing_key, sign_identity, verify_identity


BACKEND = Path(__file__).resolve().parents[3] / "backend"


def test_defaults_are_authenticated_and_ignore_unrelated_business_configuration():
    settings = load_settings({"MAX_KNOWLEDGE_FILE_SIZE_MB": "not-a-number", "MODEL_MAX_TOKENS": "invalid"})
    assert settings.auth_enabled is True
    assert settings.port == 5013
    assert settings.northbound_url == settings.management_url
    assert not settings.is_speed_mode
    with pytest.raises(IdentityError):
        settings.signing_key()


def test_explicit_configuration_preserves_issuer_key_and_listener_contract():
    values = {"GATEWAY_HOST": "127.0.0.1", "GATEWAY_PORT": "5099", "GATEWAY_AUTH_ENABLED": "FALSE",
              "GATEWAY_MANAGEMENT_URL": "https://management.test/", "JWT_ISSUER": "custom-issuer",
              "JWT_SECRET": "secret-fixture", "GATEWAY_SIGNING_SECRET": "signing-fixture", "DEPLOYMENT_VERSION": "speed"}
    settings = load_settings(values)
    assert (settings.host, settings.port, settings.auth_enabled) == ("127.0.0.1", 5099, False)
    assert settings.northbound_url == "https://management.test"
    assert settings.jwt_issuer == "custom-issuer"
    assert settings.signing_key() == "signing-fixture"
    assert settings.is_speed_mode
    assert "secret-fixture" not in repr(settings) and "signing-fixture" not in repr(settings)


@pytest.mark.parametrize("name,value", [
    ("GATEWAY_PORT", "0"), ("GATEWAY_PORT", "65536"), ("GATEWAY_PORT", "1.2"),
    ("GATEWAY_AUTH_ENABLED", "yes"), ("GATEWAY_HOST", " "), ("JWT_ISSUER", ""),
    ("DEPLOYMENT_VERSION", "unknown"),
])
def test_invalid_configuration_fails_before_startup(name, value):
    with pytest.raises(ValueError):
        load_settings({name: value})


def test_pure_protocol_has_no_implicit_key_and_derived_key_matches_backend(monkeypatch):
    from contracts.constants import environment
    from gateway.downstream.identity import sign_identity as backend_sign, signing_key

    identity = {"user_id": "u1", "tenant_id": "t1", "kind": "session"}
    key = derive_signing_key("master-fixture")
    monkeypatch.setattr(environment, "JWT_SECRET", "master-fixture")
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", "")
    assert signing_key() == GatewaySettings(jwt_secret="master-fixture").signing_key() == key
    with pytest.raises(IdentityError):
        sign_identity(identity, "management", "GET", "/api/models", b"")
    token = backend_sign(identity, "management", "GET", "/api/models", b"q=1", key=key)
    assert verify_identity(token, "management", "GET", "/api/models", b"q=1", key=key) == identity
    with pytest.raises(IdentityError):
        verify_identity(token, "management", "GET", "/api/models", b"q=1")


def test_gateway_imports_only_its_package_and_declared_runtime_libraries():
    allowed = set(sys.stdlib_module_names) | {"gateway", "fastapi", "starlette", "httpx", "jwt", "websockets", "infrastructure"}
    for path in (BACKEND / "gateway").rglob("*.py"):
        if path.relative_to(BACKEND / "gateway").parts[0] == "downstream":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = [node.module] if isinstance(node, ast.ImportFrom) else [item.name for item in node.names] if isinstance(node, ast.Import) else []
            for module in modules:
                assert module and module.split(".")[0] in allowed, (path, module)
                if module.startswith("infrastructure"):
                    assert module == "infrastructure.rdb.identity", (path, module)
                assert not module.startswith("gateway.downstream"), (path, module)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr in {"environ", "getenv"}:
                assert path.name == "configuration.py", path


def test_only_gateway_sources_can_import_launcher_in_an_isolated_directory(tmp_path):
    repository = BACKEND.parent
    dockerfile = repository / "deploy/images/dockerfiles/gateway/Dockerfile"
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        if not line.startswith("COPY "):
            continue
        *sources, destination = shlex.split(line)[1:]
        if not destination.startswith("/opt/"):
            continue
        target = tmp_path / destination.removeprefix("/opt/")
        for source in sources:
            for entry in repository.glob(source):
                if entry.is_dir():
                    shutil.copytree(entry, target, dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns("__pycache__"))
                else:
                    output = target / entry.name if destination.endswith("/") else target
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(entry, output)
    backend = tmp_path / "backend"
    assert not (backend / "gateway/downstream").exists()
    code = """import json,sys
sys.path[:0] = sys.argv[1:3]
sys.modules["bcrypt"] = None
import http.client
import logging.handlers
from backend.http import gateway_service
from gateway.configuration import load_settings
from gateway.application import create_gateway_app
app=create_gateway_app(settings=load_settings({'GATEWAY_AUTH_ENABLED':'false'}))
assert not {'management','runtime','contracts','infrastructure.rdb.client','gateway.downstream','nexent','dotenv','sqlalchemy'} & sys.modules.keys()
print(json.dumps({'imported':True,'routes':len(app.routes)}))
"""
    env = os.environ.copy()
    env["MAX_KNOWLEDGE_FILE_SIZE_MB"] = "invalid-business-setting"
    result = subprocess.run([sys.executable, "-I", "-c", code, str(tmp_path), str(backend)], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["imported"] is True


def test_launcher_uses_injected_settings_and_does_not_trust_forwarded_headers(monkeypatch):
    from backend.http import gateway_service

    settings = GatewaySettings(host="127.0.0.1", port=5099, jwt_secret="launcher-fixture")
    calls = []
    monkeypatch.setattr(gateway_service, "load_settings", lambda: settings)
    monkeypatch.setattr(gateway_service.uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    gateway_service.main()
    assert calls == [{"host": "127.0.0.1", "port": 5099, "log_level": "info", "proxy_headers": False}]


def test_healthcheck_uses_the_service_listener_port(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from gateway import healthcheck

    calls = []
    monkeypatch.setattr(healthcheck, "load_settings", lambda: GatewaySettings(port=5099))

    def open_url(url, timeout):
        calls.append((url, timeout))
        return nullcontext(SimpleNamespace(status=200))

    monkeypatch.setattr(healthcheck, "urlopen", open_url)
    healthcheck.main()
    assert calls == [("http://127.0.0.1:5099/health/ready", 3)]
