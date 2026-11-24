# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Guardrail action contracts exposed to the creator and accepted by saving."""

import ast
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from contracts.nl2agent_configuration import GuardrailPatch
from contracts.tag import AuthenticatedCaller
from services import nl2agent_configuration as service
from management.services.agent.nl2agent_tools import SAVE_CONFIGURATION_DESCRIPTION


@pytest.mark.parametrize("severity", ["block", "mask", "pass"])
async def test_guardrail_actions_save_and_preserve_unrequested_settings(mocker, severity):
    draft = {"verification_config": {
        "enabled": True, "max_final_rounds": 4,
        "guardrail_config": {"enabled": False, "rules": [
            {"name": "existing", "pattern": "old", "severity": "mask"},
        ]},
    }}
    mocker.patch.object(service, "_draft", return_value=draft)
    write = mocker.patch.object(service, "update_agent_draft_fields", return_value=1)
    fields = await service.save_configuration(AuthenticatedCaller("user", "tenant"), 1, "guardrails", {
        "enabled": True, "upsert_rules": [{"name": "pii", "pattern": "password", "severity": severity}],
    })
    assert fields == ["verification_config"]
    verification = write.call_args.args[2]["verification_config"]
    assert verification["enabled"] and verification["max_final_rounds"] == 4
    assert verification["guardrail_config"]["enabled"]
    assert verification["guardrail_config"]["rules"] == [
        {"name": "existing", "pattern": "old", "severity": "mask"},
        {"name": "pii", "pattern": "password", "severity": severity},
    ]


@pytest.mark.parametrize("extra", [
    {"severity": "error"}, {"severity": "high"}, {"action": "block"}, {"enabled": True},
])
async def test_invalid_guardrail_rule_never_reads_or_writes(mocker, extra):
    read = mocker.patch.object(service, "_draft")
    write = mocker.patch.object(service, "update_agent_draft_fields")
    with pytest.raises(ValidationError):
        await service.save_configuration(AuthenticatedCaller("user", "tenant"), 1, "guardrails", {
            "upsert_rules": [{"name": "pii", "pattern": "password", **extra}],
        })
    read.assert_not_called()
    write.assert_not_called()


def test_creator_contract_documents_actions_and_valid_examples():
    root = Path(__file__).resolve().parents[3]
    descriptions = [SAVE_CONFIGURATION_DESCRIPTION]
    for locale in ("zh", "en"):
        prompt = root / "sdk/nexent/core/prompts" / locale / "meta/nl2agent.yaml"
        descriptions.append(str(yaml.safe_load(prompt.read_text(encoding="utf-8"))))
    for description in descriptions:
        for token in ("block", "mask", "pass", "severity", "upsert_rules", "enabled", "error/high"):
            assert token in description
    example = SAVE_CONFIGURATION_DESCRIPTION.split("Example: ", 1)[1].split(". Only", 1)[0]
    call = ast.parse(f"save({example})", mode="eval").body
    arguments = {item.arg: ast.literal_eval(item.value) for item in call.keywords}
    assert arguments["section"] == "guardrails"
    validated = GuardrailPatch.model_validate(arguments["changes"])
    assert validated.enabled and validated.upsert_rules[0].severity == "block"
