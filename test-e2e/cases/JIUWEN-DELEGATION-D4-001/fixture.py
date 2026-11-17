# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Inspect owned nested execution while reusing the source-preserving file fixture."""

import importlib.util
import json
import sys
from pathlib import Path

import httpx
from management.db.client import get_db_session
from management.db.models import ConversationMessage, ConversationMessageUnit, ConversationRecord


mode, filename, helper_path = sys.argv[1:4]
if mode == "select-core":
    state = json.loads(Path(filename).read_text())
    core = sys.argv[4]
    assert core in {"smolagents", "jiuwen"}
    assert state["agent_id"] != state["source"] and state["agent_id"] in state["owned_agents"]
    with httpx.Client(
        base_url="http://nexent-config:5010",
        trust_env=False,
        timeout=90,
        headers={"Authorization": "Bearer " + state["access_token"]},
    ) as client:
        response = client.post(
            "/agent/update", json={"agent_id": state["agent_id"], **state["copied_fields"], "agent_core": core}
        )
        assert response.status_code == 200
        response = client.post(f"/agent/{state['agent_id']}/publish", json={"version_name": "Delegation validation"})
        assert response.status_code == 200
    print(json.dumps({"configured_core": core}))
elif mode == "nested":
    state = json.loads(Path(filename).read_text())
    conversation = int(sys.argv[4])
    with get_db_session() as session:
        owner = session.query(ConversationRecord).filter_by(conversation_id=conversation).one()
        assert owner.agent_id == state["agent_id"] and owner.created_by == state["user"]
        messages = (
            session.query(ConversationMessage)
            .filter_by(conversation_id=conversation)
            .order_by(ConversationMessage.message_id)
            .all()
        )
        units = (
            session.query(ConversationMessageUnit)
            .filter_by(conversation_id=conversation)
            .order_by(ConversationMessageUnit.unit_index)
            .all()
        )
        print(
            json.dumps(
                {
                    "messages": [
                        {"id": m.message_id, "index": m.message_index, "status": m.status, "role": m.message_role}
                        for m in messages
                    ],
                    "starts": sum(unit.unit_type == "subagent_start" for unit in units),
                    "ends": sum(unit.unit_type == "subagent_end" for unit in units),
                    "nested_units": sum(bool(unit.invocation_id) for unit in units),
                }
            )
        )
else:
    spec = importlib.util.spec_from_file_location("owned_file_fixture", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    sys.argv = [sys.argv[0], mode, filename, *sys.argv[4:]]
    helper.main()
