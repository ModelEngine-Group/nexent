"""User-message additions are rendered from matching SDK locale resources."""

import importlib
import importlib.util
from pathlib import Path
import sys
import types

import pytest


PROMPTS_ROOT = Path(__file__).resolve().parents[4] / "sdk/nexent/core/prompts"
ASSEMBLY_ROOT = PROMPTS_ROOT.parent / "agents/prompt"
PREFIX = "_user_context_test_package"
for name in (PREFIX, f"{PREFIX}.core", f"{PREFIX}.core.agents"):
    module = types.ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module
spec = importlib.util.spec_from_file_location(
    f"{PREFIX}.core.prompts", PROMPTS_ROOT / "__init__.py",
    submodule_search_locations=[str(PROMPTS_ROOT)],
)
assert spec is not None and spec.loader is not None
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
assembly = types.ModuleType(f"{PREFIX}.core.agents.prompt")
assembly.__path__ = [str(ASSEMBLY_ROOT)]
sys.modules[assembly.__name__] = assembly
user_context = importlib.import_module(f"{assembly.__name__}.user_context")


@pytest.mark.parametrize("language,marker,workspace_label", [
    ("zh", "[当前时间:", "本次运行的工作目录"),
    ("en", "[Current time:", "Run workspace"),
])
def test_user_context_matches_page_language(language, marker, workspace_label):
    value = user_context.render_user_context(language, "current_time", {
        "time": "2026-09-28 12:30:00", "query": "question",
    })
    assert value.startswith(marker)
    assert user_context.has_current_time_prefix(value)
    workspace = user_context.render_user_context(language, "workspace_note", {
        "workspace": "/run/1", "outputs": "/run/1/outputs",
    })
    assert workspace_label in workspace
    assert "/run/1/outputs" in workspace


def test_file_context_keeps_dynamic_values_and_separate_locales():
    values = {"name": "brief.pdf", "s3_url": "s3://bucket/brief.pdf", "presigned_url": "https://example.test/file"}
    zh = user_context.render_user_context("zh", "file_with_presigned_url", values)
    en = user_context.render_user_context("en", "file_with_presigned_url", values)
    assert "文件名" in zh and "File name" in en
    assert all(value in zh and value in en for value in values.values())


def test_missing_runtime_value_is_an_error():
    with pytest.raises(Exception):
        user_context.render_user_context("zh", "workspace_note", {})
