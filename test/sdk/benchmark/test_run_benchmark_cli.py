import argparse

import pytest
import yaml

from sdk.benchmark.generic.run_benchmark import (
    load_agent_config,
    non_negative_int,
    positive_int,
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
