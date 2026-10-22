# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Gateway ownership and pre-migration route contract regressions."""

import ast
import json
from pathlib import Path

from contracts.constants.voice import TEST_PCM_PATH, TEST_VOICE_PATH
from management.utils import oauth_providers


BACKEND = Path(__file__).resolve().parents[3] / "backend"


def test_gateway_routes_keep_all_original_paths_methods_and_handlers():
    expected = json.loads(Path(__file__).with_name("gateway_route_baseline.json").read_text(encoding="utf-8"))
    actual = []
    for file in ("gateway/api/northbound.py", "gateway/application.py"):
        tree = ast.parse((BACKEND / file).read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                receiver = dec.func.value
                if not isinstance(receiver, ast.Name) or receiver.id not in {"router", "a2a_router", "northbound_app"}:
                    continue
                prefix = {"router": "/nb/v1", "a2a_router": "/nb/a2a", "northbound_app": ""}[receiver.id]
                actual.append([dec.func.attr.upper(), prefix + dec.args[0].value, node.name])
    assert sorted(actual) == expected


def test_gateway_owns_two_authentication_implementations_and_one_route_file():
    assert {p.name for p in (BACKEND / "gateway/authentication").glob("*.py")} == {
        "__init__.py", "normal.py", "northbound.py"
    }
    assert {p.name for p in (BACKEND / "gateway/api").glob("*.py")} == {"__init__.py", "northbound.py"}
    assert not (BACKEND / "gateway/api/northbound").exists()
    assert not (BACKEND / "gateway/api/knowledge_base").exists()
    assembly = (BACKEND / "gateway/application.py").read_text(encoding="utf-8")
    assert assembly.count("northbound_app.include_router(") == 2


def test_audio_constants_still_point_to_backend_assets():
    assert Path(TEST_VOICE_PATH).resolve() == BACKEND / "assets/test.wav"
    assert Path(TEST_PCM_PATH).resolve() == BACKEND / "assets/test_voice.pcm"


def test_oauth_provider_enablement_still_reads_current_environment(monkeypatch):
    github = oauth_providers.get_provider_definition("github")
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_SECRET", raising=False)
    assert not oauth_providers.is_provider_enabled(github)
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "client")
    assert not oauth_providers.is_provider_enabled(github)
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "secret")
    assert oauth_providers.is_provider_enabled(github)
    monkeypatch.setenv("ENABLE_WECHAT_OAUTH", "true")
    assert oauth_providers.is_provider_enabled(oauth_providers.WECHAT_PROVIDER)
    monkeypatch.setenv("ENABLE_WECHAT_OAUTH", "false")
    assert not oauth_providers.is_provider_enabled(oauth_providers.WECHAT_PROVIDER)
    copied = oauth_providers.get_all_provider_definitions()
    copied.clear()
    assert oauth_providers.get_provider_definition("github") is github
