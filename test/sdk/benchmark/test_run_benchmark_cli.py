import argparse
import sys
from types import SimpleNamespace

import pytest
import yaml

from sdk.benchmark.generic import run_benchmark
from sdk.benchmark.generic.run_benchmark import (
    load_agent_config,
    non_negative_int,
    positive_int,
    resolve_context_budget_defaults,
    select_dataset_items,
)


@pytest.mark.parametrize("value", ["0", "-1"])
def test_positive_int_rejects_non_positive_values(value):
    with pytest.raises(argparse.ArgumentTypeError):
        positive_int(value)


@pytest.mark.parametrize("value", ["-1", "-20"])
def test_non_negative_int_rejects_negative_values(value):
    with pytest.raises(argparse.ArgumentTypeError):
        non_negative_int(value)


def test_cli_integer_validators_accept_boundaries():
    assert positive_int("1") == 1
    assert non_negative_int("0") == 0


def test_context_budget_defaults_match_nexent_legacy_fallback():
    assert resolve_context_budget_defaults(
        token_threshold=None,
        soft_input_budget=None,
        hard_input_budget=None,
        context_window_tokens=None,
    ) == {
        "token_threshold": 32_768,
        "soft_input_budget_tokens": 32_768,
        "hard_input_budget_tokens": 36_044,
        "context_window_tokens": 32_768,
    }


def test_context_budget_defaults_follow_threshold_and_explicit_overrides():
    assert resolve_context_budget_defaults(
        token_threshold=20_000,
        soft_input_budget=None,
        hard_input_budget=25_000,
        context_window_tokens=30_000,
    ) == {
        "token_threshold": 20_000,
        "soft_input_budget_tokens": 20_000,
        "hard_input_budget_tokens": 25_000,
        "context_window_tokens": 30_000,
    }


def test_load_agent_config_resolves_strict_environment_references(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("EXA_API_KEY", "resolved-secret")
    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        yaml.safe_dump({
            "tools": [{
                "tool_params": {
                    "exa_api_key": {"$env": "EXA_API_KEY"},
                },
            }],
        }),
        encoding="utf-8",
    )

    config = load_agent_config(str(config_path))

    assert config["tools"][0]["tool_params"]["exa_api_key"] == "resolved-secret"


def test_load_agent_config_rejects_missing_environment_variable(tmp_path):
    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        "tool_params:\n  api_key:\n    $env: MISSING_API_KEY\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="MISSING_API_KEY"):
        load_agent_config(str(config_path))


def test_load_agent_config_rejects_non_strict_environment_reference(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("EXA_API_KEY", "resolved-secret")
    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        "tool_params:\n"
        "  api_key:\n"
        "    $env: EXA_API_KEY\n"
        "    default: plaintext-fallback\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be the only key"):
        load_agent_config(str(config_path))


def test_select_dataset_items_uses_exact_ids_in_dataset_order():
    items = [
        type("Item", (), {"id": "a"})(),
        type("Item", (), {"id": "b"})(),
        type("Item", (), {"id": "c"})(),
    ]

    selected = select_dataset_items(items, item_ids=["c", "a"])

    assert [item.id for item in selected] == ["a", "c"]


def test_select_dataset_items_rejects_missing_ids():
    items = [type("Item", (), {"id": "a"})()]

    with pytest.raises(ValueError, match="not found"):
        select_dataset_items(items, item_ids=["missing"])


def test_select_dataset_items_rejects_conflicts_and_duplicates():
    items = [type("Item", (), {"id": "a"})(), type("Item", (), {"id": "b"})()]

    assert [item.id for item in select_dataset_items(items, item_limit=1)] == ["a"]
    with pytest.raises(ValueError, match="cannot be combined"):
        select_dataset_items(items, item_limit=1, item_ids=["a"])
    with pytest.raises(ValueError, match="duplicate"):
        select_dataset_items(items, item_ids=["a", "a"])


@pytest.mark.parametrize(
    ("extra_args", "message"),
    [
        (["--item-limit", "1", "--item-id", "item-1"], "cannot be combined"),
        (["--exa-cache-mode", "record"], "--exa-cache-path is required"),
        (["--exa-cache-path", "cache.json"], "requires --exa-cache-mode"),
        (["--keep-recent-pairs", "1"], "removed by the unified ContextItems runtime"),
        (
            ["--soft-input-budget", "20", "--hard-input-budget", "10"],
            "cannot exceed",
        ),
        (["--soft-input-budget", "40000"], "cannot exceed"),
    ],
)
def test_main_rejects_invalid_argument_combinations(monkeypatch, capsys, extra_args, message):
    monkeypatch.setattr(sys, "argv", ["run_benchmark.py", "--dataset", "dataset", *extra_args])

    with pytest.raises(SystemExit) as exc_info:
        run_benchmark.main()

    assert exc_info.value.code == 2
    assert message in capsys.readouterr().err


def test_main_lists_evaluators_without_connecting_to_langfuse(monkeypatch, capsys):
    import evaluators

    monkeypatch.setattr(evaluators, "list_evaluators", lambda: ["exact_match", "f1"])
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_benchmark.py", "--dataset", "dataset", "--list-evaluators"],
    )

    run_benchmark.main()

    output = capsys.readouterr().out
    assert "Available evaluators:" in output
    assert "exact_match" in output
    assert "f1" in output


def test_main_redacts_langfuse_auth_failure(monkeypatch, capsys):
    import evaluators

    monkeypatch.setattr(evaluators, "resolve_evaluators", lambda names: [])

    def fail_auth():
        raise RuntimeError("secret auth detail")

    monkeypatch.setattr(
        "langfuse.Langfuse",
        lambda: SimpleNamespace(auth_check=fail_auth),
    )
    monkeypatch.setattr(sys, "argv", ["run_benchmark.py", "--dataset", "dataset"])

    with pytest.raises(SystemExit) as exc_info:
        run_benchmark.main()

    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert "Langfuse connection failed" in output
    assert "secret auth detail" not in output


def test_main_rejects_missing_upload_file(monkeypatch, tmp_path, capsys):
    import evaluators

    monkeypatch.setattr(evaluators, "resolve_evaluators", lambda names: [])
    monkeypatch.setattr(
        "langfuse.Langfuse",
        lambda: SimpleNamespace(auth_check=lambda: True),
    )
    missing_path = tmp_path / "missing.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_benchmark.py", "--dataset", "dataset", "--upload", str(missing_path)],
    )

    with pytest.raises(SystemExit) as exc_info:
        run_benchmark.main()

    assert exc_info.value.code == 1
    assert "File not found" in capsys.readouterr().out


def test_main_uploads_and_stops_for_dry_run(monkeypatch, tmp_path, capsys):
    import evaluators

    monkeypatch.setattr(evaluators, "resolve_evaluators", lambda names: [])
    monkeypatch.setattr(
        "langfuse.Langfuse",
        lambda: SimpleNamespace(auth_check=lambda: True),
    )
    upload_path = tmp_path / "dataset.jsonl"
    upload_path.write_text("{}\n", encoding="utf-8")
    uploaded = {}
    monkeypatch.setattr(
        run_benchmark,
        "upload_jsonl",
        lambda **kwargs: uploaded.update(kwargs) or 1,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_benchmark.py",
            "--dataset",
            "dataset",
            "--upload",
            str(upload_path),
            "--input-key",
            "prompt",
            "--output-key",
            "gold",
            "--dry-run",
        ],
    )

    run_benchmark.main()

    assert uploaded == {
        "dataset_name": "dataset",
        "jsonl_path": str(upload_path),
        "input_key": "prompt",
        "output_key": "gold",
    }
    assert "Dry run complete" in capsys.readouterr().out


def test_main_requires_existing_run_for_rescore(monkeypatch, capsys):
    import evaluators

    monkeypatch.setattr(evaluators, "resolve_evaluators", lambda names: [])
    monkeypatch.setattr(
        "langfuse.Langfuse",
        lambda: SimpleNamespace(auth_check=lambda: True),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_benchmark.py", "--dataset", "dataset", "--rescore"],
    )

    with pytest.raises(SystemExit) as exc_info:
        run_benchmark.main()

    assert exc_info.value.code == 2
    assert "--existing-run is required" in capsys.readouterr().err
