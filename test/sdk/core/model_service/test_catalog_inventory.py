# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AC-01/16: integrity of the reviewed source inventory, not model support."""

import hashlib
import tomllib
from collections import Counter
from pathlib import Path

import pytest

CATALOG_ROOT = (
    Path(__file__).resolve().parents[4] / "sdk/nexent/core/model_service/profiles"
)
MANIFEST = tomllib.loads((CATALOG_ROOT / "manifest.toml").read_text())


def test_reviewed_inventory_is_pinned_and_complete():
    assert MANIFEST["schema_version"] == 1
    assert MANIFEST["source_schema_ref"] == "models_dev_authored_v1"
    assert MANIFEST["upstream_revision"] == "e69e1844210e5cfe7c7e7f68d57328bc7451a51c"
    sources = MANIFEST["sources"]
    assert Counter(source["kind"] for source in sources) == {
        "model": 26,
        "provider_model": 35,
        "provider": 6,
    }
    paths = [source["path"] for source in sources]
    assert len(paths) == len(set(paths))
    actual = {
        str(path.relative_to(CATALOG_ROOT))
        for folder in ("models", "providers")
        for path in (CATALOG_ROOT / folder).rglob("*.toml")
    }
    assert actual == set(paths)


@pytest.mark.parametrize(
    "source", MANIFEST["sources"], ids=lambda source: source["path"]
)
def test_source_bytes_match_manifest_and_dependencies_are_present(source):
    path = CATALOG_ROOT / source["path"]
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == source["content_sha256"]
    parsed = tomllib.loads(data.decode("utf-8"))
    if "base_model" in parsed:
        assert f"models/{parsed['base_model']}.toml" in {
            item["path"] for item in MANIFEST["sources"] if item["kind"] == "model"
        }
    if source["kind"] == "provider":
        assert parsed["api"].startswith("https://")
        assert isinstance(parsed["env"], list)


def test_license_and_scope_notice_ship_with_inventory():
    license_text = (CATALOG_ROOT / "LICENSE").read_text()
    assert "Copyright (c) 2025 models.dev" in license_text
    assert "Permission is hereby granted, free of charge" in license_text
    assert "THE SOFTWARE IS PROVIDED" in license_text
    readme = (CATALOG_ROOT / "README.md").read_text()
    assert MANIFEST["upstream_revision"] in readme
    assert "not a verified support list" in readme


def test_requested_china_inventory_is_a_union_with_explicit_local_origin():
    paths = {source["path"] for source in MANIFEST["sources"]}
    assert {"models/" + key + ".toml" for key in [
        "deepseek/deepseek-v4-flash", "deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4-pro",
        "bytedance-seed/seed-2.1-pro", "zhipuai/glm-5", "zhipuai/glm-5.1", "zhipuai/glm-5.2",
        "zhipuai/glm-5.3", "zhipuai/glm-5.3-flash", "moonshotai/kimi-k3", "minimax/MiniMax-M3",
        "alibaba/qwen3.7-max", "alibaba/qwen3.7-plus", "alibaba/qwen3.8-max", "alibaba/qwen3.8-flash",
    ]} <= paths
    assert {"providers/" + key + "/provider.toml" for key in [
        "siliconflow-cn", "alibaba-cn", "volcengine", "volcengine-coding-plan", "deepseek", "tokenpony",
    ]} <= paths
    local = [source for source in MANIFEST["sources"] if source.get("origin") == "nexent"]
    assert len(local) == 1
    assert local[0]["path"] == "providers/tokenpony/provider.toml"
    assert local[0]["source_url"] == "https://docs.tokenpony.cn/"
    assert local[0]["source_revision"] == "nexent_tokenpony_provider_v1"
