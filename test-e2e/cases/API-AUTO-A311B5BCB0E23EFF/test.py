"""D2 contract test: create agent converges name+display_name into a single display name.

Static local source contract verification only. No network calls, no external model service.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.config import repo_root

CASE_ID = "API-AUTO-A311B5BCB0E23EFF"

CREATE_AGENT_MODAL = "components/agent/CreateAgentModal.tsx"
AGENT_CONFIG_SERVICE = "services/agentConfigService.ts"
MY_AGENT_VIEW = "app/[locale]/agent-space/my-agent.tsx"

CREATE_PAYLOAD_KEYS = {
    "display_name",
    "description",
    "author",
    "max_steps",
    "is_main_agent",
    "provide_run_summary",
    "enabled",
}

FRONTEND = repo_root() / "frontend"


def _read(rel: str) -> str:
    path = FRONTEND / rel
    assert path.is_file(), f"contract source file missing: {path}"
    return path.read_text(encoding="utf-8")


def _brace_block(text: str, brace: int) -> str:
    depth = 0
    for i in range(brace, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[brace : i + 1]
    raise AssertionError("unbalanced braces")


def _extract_block(text: str, marker: str) -> str:
    start = text.index(marker)
    return _brace_block(text, text.index("{", start))


def _top_level_keys(block: str) -> set[str]:
    keys: set[str] = set()
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped in {"{", "}"}:
            continue
        if ":" not in stripped:
            continue
        key = stripped.split(":", 1)[0].strip()
        if key and key.replace("_", "").isalnum():
            keys.add(key)
    return keys


def _name_attrs(form_block: str) -> list[str]:
    attrs: list[str] = []
    idx = 0
    token = 'name="'
    while True:
        idx = form_block.find(token, idx)
        if idx == -1:
            break
        end = form_block.find('"', idx + len(token))
        attrs.append(form_block[idx + len(token) : end])
        idx = end + 1
    return attrs


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D2")
def test_create_agent_single_display_name_contract() -> None:
    modal = _read(CREATE_AGENT_MODAL)
    service = _read(AGENT_CONFIG_SERVICE)
    view = _read(MY_AGENT_VIEW)

    result_type = _extract_block(modal, "interface CreatedAgentResult")
    result_fields = _top_level_keys(result_type)
    assert result_fields == {"agentId", "displayName"}, (
        f"CreatedAgentResult fields mismatch: {sorted(result_fields)}"
    )

    payload = _extract_block(modal, "updateAgentInfo({")
    payload_keys = _top_level_keys(payload)
    assert payload_keys == CREATE_PAYLOAD_KEYS, (
        f"create payload fields mismatch: {sorted(payload_keys)}"
    )
    assert "name" not in payload_keys, "create payload must not include name"

    form_start = modal.index("<Form")
    form_end = modal.index("</Form>") + len("</Form>")
    form_block = modal[form_start:form_end]
    name_attrs = _name_attrs(form_block)
    assert name_attrs == ["displayName"], (
        f"form must expose only displayName, got: {name_attrs}"
    )
    assert "isValidAgentDisplayName" in form_block
    assert 'createAgentNameConflictValidator(t, "display_name")' in form_block

    update_fn = _extract_block(service, "updateAgentInfo = async")
    assert "API_ENDPOINTS.agent.update" in update_fn
    assert 'method: "POST"' in update_fn
    payload_type = _extract_block(service, "interface UpdateAgentInfoPayload")
    assert "display_name?: string;" in payload_type
    assert "agent_id?: number;" in payload_type

    assert "result.data?.agent_id" in modal
    assert "Number(result.data.agent_id)" in modal

    sig_start = view.index("handleAgentCreated = async")
    sig_end = view.index("=>", sig_start) + 2
    signature = view[sig_start:sig_end]
    params_open = signature.index("(") + 1
    params = signature[params_open : signature.index(")")]
    destructure = params[params.index("{") + 1 : params.index("}")].strip()
    assert destructure == "agentId", (
        f"onCreated callback must destructure only agentId, got {destructure!r}"
    )
    assert ": CreatedAgentResult" in signature

    body_start = view.index("{", sig_end)
    handle_block = _brace_block(view, body_start)
    assert "agents?agent_id=${agentId}" in handle_block
    assert "displayName" not in handle_block
    assert "result.data" not in handle_block
