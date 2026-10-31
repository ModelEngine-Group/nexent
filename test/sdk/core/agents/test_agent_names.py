# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Identifier compatibility and deterministic external callable allocation."""

import ast

import pytest

from nexent.core.agent_names import allocate_external_agent_names, validate_agent_name, validate_callable_names


@pytest.mark.parametrize("name", ["agent_one", "_", "中文助手", "a" * 100])
def test_internal_identifier_compatibility(name):
    assert validate_agent_name(name) == name


@pytest.mark.parametrize("name", ["", "agent-one", "9agent", "agent name", "class", "None", "a" * 101])
def test_internal_identifier_rejection(name):
    with pytest.raises(ValueError, match="Python identifier"):
        validate_agent_name(name)


def test_legal_external_calls_preserved_and_original_inputs_untouched():
    agents = [("2", "parallel_probe_a"), ("1", "中文助手")]
    assert allocate_external_agent_names(agents) == {"1": "中文助手", "2": "parallel_probe_a"}
    assert agents == [("2", "parallel_probe_a"), ("1", "中文助手")]


def test_legal_dunder_prefix_is_not_renamed_unnecessarily():
    assert allocate_external_agent_names([("7", "__legacy_worker")]) == {"7": "__legacy_worker"}


def test_aliases_are_order_independent_and_do_not_overwrite_existing_names():
    agents = [("2", "duplicate"), ("1", "duplicate"), ("3", "agent-one"), ("4", "a2a_agent_3")]
    names = allocate_external_agent_names(agents, {"duplicate", "a2a_agent_2"})
    assert names == allocate_external_agent_names(list(reversed(agents)), {"a2a_agent_2", "duplicate"})
    assert names["4"] == "a2a_agent_3"
    assert len(set(names.values())) == 4
    assert not set(names.values()) & {"duplicate", "a2a_agent_2"}
    for name in names.values():
        ast.parse(f"{name} = None")


def test_unique_generated_alias_depends_on_id_instead_of_display_name():
    assert allocate_external_agent_names([("7", "agent-one")]) == {"7": "a2a_agent_7"}
    assert allocate_external_agent_names([("7", "class")]) == {"7": "a2a_agent_7"}


@pytest.mark.parametrize("name", ["print", "final_answer", "parallel_executor", "_nexent_json", "__builtins__"])
def test_framework_bindings_are_reserved(name):
    assert allocate_external_agent_names([("7", name)])["7"] == "a2a_agent_7"


def test_arbitrary_ids_are_encoded_without_syntax_or_identity_collisions():
    aliases = allocate_external_agent_names([(key, "bad-name") for key in ["a-b", "a_b", "../x", "中"]])
    assert len(set(aliases.values())) == 4
    validate_callable_names(aliases.values())


def test_unicode_normalized_names_cannot_overwrite_each_other():
    aliases = allocate_external_agent_names([("1", "Ｋ"), ("2", "K")])
    assert aliases["2"] == "K"
    assert aliases["1"] != "Ｋ"
    assert len(set(aliases.values())) == 2


def test_duplicate_external_id_is_rejected():
    with pytest.raises(ValueError, match="Duplicate external Agent ID"):
        allocate_external_agent_names([("1", "one"), ("1", "two")])


@pytest.mark.parametrize("names", [["bad-name"], ["class"], ["one", "one"], ["K", "Ｋ"], ["_nexent_json"]])
def test_invalid_registry_fails_before_source_generation(names):
    with pytest.raises(ValueError, match="callable"):
        validate_callable_names(names)
