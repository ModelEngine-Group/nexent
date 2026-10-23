from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from sdk.benchmark.generic.provenance.experiment_manifest import (
    _jsonable,
    _resolve_cm_budget_defaults,
    build_manifest,
    check_untracked_risk,
    compute_source_tree_hash,
    resolve_code_commit,
    sha256_value,
    write_manifest_exclusive,
)


@dataclass
class _ContextConfig:
    token_threshold: int = 10_000
    keep_recent_steps: int = 4
    policy_layers: dict = None

    def __post_init__(self):
        if self.policy_layers is None:
            self.policy_layers = {
                "platform": {"processing_mode": "adaptive_compact"}
            }


def test_build_manifest_records_resolved_values(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sdk.benchmark.generic.provenance.experiment_manifest.resolve_code_commit",
        lambda _: "abc123",
    )

    manifest = build_manifest(
        dataset_name="gaia",
        dataset_version="v1",
        dataset_item_ids=["item-1", "item-2"],
        run_name="gaia-managed",
        repo_root=tmp_path,
        lifecycle_mode="isolated-item",
        context_manager_config=_ContextConfig(),
        max_steps=10,
        temperature=0.1,
        language="en",
        max_concurrency=1,
        model_config={"model_name": "model-a", "url": "https://api.openai.com/v1"},
        tools=[{"name": "search"}],
        system_prompt="system",
        agent_config={"name": "agent"},
        evaluator_names=["exact_match"],
        observation_policy={"effective_limit_chars": 0},
        budget_profile="synthetic_trigger",
        started_at="2026-07-20T00:00:00+00:00",
    )

    assert manifest["code_commit"] == "abc123"
    assert manifest["manifest_schema_version"] == 3
    assert manifest["context_runtime"] == "context_items"
    assert manifest["context_processing_mode"] == "adaptive_compact"
    assert manifest["adaptive_compaction_enabled"] is True
    assert manifest["context_policy_fingerprint"]
    assert manifest["context_manager"]["token_threshold"] == 10_000
    assert manifest["dataset_item_ids"] == ["item-1", "item-2"]
    assert manifest["tool_schema_hash"] == sha256_value([{"name": "search"}])
    assert manifest["system_prompt_hash"] == sha256_value("system")
    assert manifest["budget_profile"] == "synthetic_trigger"
    assert manifest["manifest_hash"]


def test_write_manifest_exclusive_refuses_overwrite(tmp_path):
    manifest = {"run_name": "same/run", "manifest_hash": "hash"}

    path = write_manifest_exclusive(manifest, tmp_path)

    assert path == Path(tmp_path) / "same_run.manifest.json"
    with pytest.raises(FileExistsError):
        write_manifest_exclusive(manifest, tmp_path)


def test_manifest_redacts_secrets_and_endpoint_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sdk.benchmark.generic.provenance.experiment_manifest.resolve_code_commit",
        lambda _: "abc123",
    )

    manifest = build_manifest(
        dataset_name="dataset",
        dataset_version=None,
        dataset_item_ids=["item"],
        run_name="run",
        repo_root=tmp_path,
        lifecycle_mode="isolated-item",
        context_manager_config=_ContextConfig(),
        max_steps=1,
        temperature=0,
        language="en",
        max_concurrency=1,
        model_config={
            "model_name": "model",
            "url": "https://user:password@example.com/v1?api_key=secret",
        },
        tools=[{
            "name": "tool",
            "params": {
                "exa_api_key": "secret-exa",
                "tavily_api_key": "secret-tavily",
                "ssh_password": "secret-password",
                "access_token": "secret-token",
                "authorization_header": "secret-authorization",
                "headers": {"X-Secret": "secret-header"},
                "cookie": "secret-cookie",
                "max_tokens": 4096,
            },
        }],
        system_prompt="system",
        agent_config={"name": "agent"},
        evaluator_names=["exact_match"],
        observation_policy={},
    )

    assert manifest["model_endpoint"] == "https://example.com/v1"
    assert "secret" not in str(manifest)
    assert manifest["tool_schema_hash"] == sha256_value([{
        "name": "tool",
        "params": {
            "exa_api_key": "[REDACTED]",
            "tavily_api_key": "[REDACTED]",
            "ssh_password": "[REDACTED]",
            "access_token": "[REDACTED]",
            "authorization_header": "[REDACTED]",
            "headers": "[REDACTED]",
            "cookie": "[REDACTED]",
            "max_tokens": 4096,
        },
    }])


def test_jsonable_stops_cyclic_runtime_objects():
    cyclic = {}
    cyclic["self"] = cyclic

    assert _jsonable(cyclic) == {"self": "[CYCLE:dict]"}


def test_tool_schema_hash_ignores_runtime_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sdk.benchmark.generic.provenance.experiment_manifest.resolve_code_commit",
        lambda _: "abc123",
    )

    class Tool:
        class_name = "SearchTool"
        name = "search"
        description = "Search"
        inputs = "{}"
        output_type = "string"
        params = {"limit": 5}
        source = "local"
        usage = None
        labels = ["web"]

        def __init__(self):
            self.metadata = {}
            self.metadata["tool"] = self

    common = {
        "dataset_name": "dataset",
        "dataset_version": None,
        "dataset_item_ids": ["item"],
        "repo_root": tmp_path,
        "lifecycle_mode": "isolated-item",
        "context_manager_config": _ContextConfig(),
        "max_steps": 1,
        "temperature": 0,
        "language": "en",
        "max_concurrency": 1,
        "model_config": {"model_name": "model"},
        "system_prompt": "system",
        "agent_config": {"name": "agent"},
        "evaluator_names": ["exact_match"],
        "observation_policy": {},
    }

    first = build_manifest(run_name="first", tools=[Tool()], **common)
    second = build_manifest(run_name="second", tools=[Tool()], **common)

    assert first["tool_schema_hash"] == second["tool_schema_hash"]


class TestResolveCmBudgetDefaults:
    def test_zero_defaults_resolved_from_threshold(self):
        config = {
            "token_threshold": 10_000,
            "soft_input_budget_tokens": 0,
            "hard_input_budget_tokens": 0,
            "max_summary_input_tokens": 0,
            "max_summary_reduce_tokens": 0,
        }
        _resolve_cm_budget_defaults(config)

        assert config["soft_input_budget_tokens"] == 10_000
        assert config["hard_input_budget_tokens"] == 11_000
        assert config["max_summary_input_tokens"] == 12_000
        assert config["max_summary_reduce_tokens"] == 2_000


def test_git_provenance_helpers_capture_commit_and_relevant_untracked_files(
    monkeypatch,
    tmp_path,
):
    responses = iter(
        [
            SimpleNamespace(stdout="commit-sha\n"),
            SimpleNamespace(stdout=" M sdk/benchmark/file.py\n?? notes.txt\n"),
            SimpleNamespace(
                stdout="\n".join(
                    [
                        "sdk/benchmark/new.py",
                        "backend/new.yaml",
                        "notes/config.yml",
                        "sdk/benchmark/__pycache__/ignored.py",
                        "sdk/benchmark/ignored.pyc",
                        "frontend/ignored.ts",
                    ]
                )
            ),
        ]
    )
    monkeypatch.setattr(
        "sdk.benchmark.generic.provenance.experiment_manifest.subprocess.run",
        lambda *args, **kwargs: next(responses),
    )

    assert resolve_code_commit(tmp_path) == "commit-sha"
    risk = check_untracked_risk(tmp_path)
    assert risk == {
        "tracked_worktree_dirty": True,
        "relevant_untracked_files": [
            "backend/new.yaml",
            "notes/config.yml",
            "sdk/benchmark/new.py",
        ],
        "source_snapshot_method": "temporary_index_write_tree_v1",
    }


@pytest.mark.parametrize(
    ("error", "expected_prefix"),
    [
        (
            __import__("subprocess").CalledProcessError(
                1,
                ["git", "read-tree"],
                stderr="bad index",
            ),
            "error:bad index",
        ),
        (FileNotFoundError(), "error:git not found"),
    ],
)
def test_source_tree_hash_returns_diagnostic_for_git_failure(
    monkeypatch,
    tmp_path,
    error,
    expected_prefix,
):
    monkeypatch.setattr(
        "sdk.benchmark.generic.provenance.experiment_manifest.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    assert compute_source_tree_hash(tmp_path) == expected_prefix


def test_jsonable_handles_paths_model_dump_public_objects_and_depth_limit():
    class Model:
        def model_dump(self, **kwargs):
            return {"value": 1, "api_key": "secret"}

    class BrokenModel:
        visible = "fallback"

        def __init__(self):
            self.visible = "fallback"
            self.metadata = {"ignored": True}

        def model_dump(self, **kwargs):
            raise ValueError("cannot dump")

    assert _jsonable(Path("/tmp/file")) == "/tmp/file"
    assert _jsonable(Model()) == {"value": 1, "api_key": "[REDACTED]"}
    assert _jsonable(BrokenModel()) == {"visible": "fallback"}
    assert _jsonable([], _depth=50) == "[MAX_DEPTH:list]"

    def test_explicit_values_preserved(self):
        config = {
            "token_threshold": 10_000,
            "soft_input_budget_tokens": 8_000,
            "hard_input_budget_tokens": 15_000,
            "max_summary_input_tokens": 5_000,
            "max_summary_reduce_tokens": 3_000,
        }
        _resolve_cm_budget_defaults(config)

        assert config["soft_input_budget_tokens"] == 8_000
        assert config["hard_input_budget_tokens"] == 15_000
        assert config["max_summary_input_tokens"] == 5_000
        assert config["max_summary_reduce_tokens"] == 3_000

    def test_no_op_when_threshold_zero(self):
        config = {
            "token_threshold": 0,
            "soft_input_budget_tokens": 0,
            "hard_input_budget_tokens": 0,
        }
        _resolve_cm_budget_defaults(config)

        assert config["soft_input_budget_tokens"] == 0
        assert config["hard_input_budget_tokens"] == 0

    def test_missing_fields_added_with_resolved_values(self):
        config = {"token_threshold": 10_000}
        _resolve_cm_budget_defaults(config)

        assert config["soft_input_budget_tokens"] == 10_000
        assert config["hard_input_budget_tokens"] == 11_000
        assert config["max_summary_input_tokens"] == 12_000
        assert config["max_summary_reduce_tokens"] == 2_000
