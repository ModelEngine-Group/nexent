# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Own a saved-assistant clone and private auth state for real clarification acceptance."""

import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

from gateway.authentication.auth import generate_session_jwt
from management.db.client import get_db_session
from management.db.models import AgentInfo, ConversationMessage, ConversationMessageUnit, ConversationRecord


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def rows(session, model, **filters):
    return [{c.name: getattr(row, c.name) for c in model.__table__.columns}
            for row in session.query(model).filter_by(**filters).order_by(*model.__table__.primary_key.columns)]


def checked(response):
    assert response.status_code == 200, f"Fixture API status {response.status_code} at {response.request.url.path}"
    return response.json()


def source_history(session, source):
    ids = [c.conversation_id for c in session.query(ConversationRecord).filter_by(agent_id=source)]
    result = {}
    for model in [ConversationRecord, ConversationMessage, ConversationMessageUnit]:
        records = session.query(model).filter(model.conversation_id.in_(ids)).order_by(*model.__table__.primary_key.columns)
        result[model.__name__] = digest([{c.name: getattr(row, c.name) for c in model.__table__.columns} for row in records])
    return result


def save(path, state):
    path.write_text(json.dumps(state, default=str), encoding="utf-8")


def main():
    mode, filename = sys.argv[1:3]
    path = Path(filename)
    if mode in {"auth", "setup"}:
        source = int(sys.argv[3])
        with get_db_session() as session:
            draft = session.query(AgentInfo).filter_by(agent_id=source, version_no=0, delete_flag="N").one()
            state = {"source": source, "user": draft.created_by, "tenant": draft.tenant_id,
                     "source_version": draft.current_version_no,
                     "access_token": generate_session_jwt(draft.created_by, expires_in=3600),
                     "expires_at": int(time.time()) + 3600, "owned_agents": [], "prefix": path.stem[-12:]}
            if mode == "setup":
                state["source_hash"] = digest(rows(session, AgentInfo, agent_id=source))
                state["source_history"] = source_history(session, source)
        save(path, state)
        if mode == "auth":
            print(json.dumps({"authenticated": True, "source": source}))
            return
    else:
        state = json.loads(path.read_text(encoding="utf-8"))
    headers = {"Authorization": "Bearer " + state["access_token"]}
    with httpx.Client(base_url="http://nexent-config:5010", headers=headers, trust_env=False, timeout=90) as config, \
            httpx.Client(base_url="http://nexent-runtime:5014", headers=headers, trust_env=False, timeout=90) as runtime:
        if mode == "setup":
            exported = checked(config.post("/agent/export", json={"agent_id": state["source"]}))["data"]
            state["source_export_hash"] = digest(exported)
            original = exported["agent_info"][str(state["source"])]
            assert "agent_core" not in original, "Portable Agent still persists Core"
            keys = ["model_ids", "business_logic_model_id", "prompt", "max_steps", "enable_context_manager",
                    "context_policy", "model_params_override", "verification_config", "requested_output_tokens"]
            expected = {key: original.get(key) for key in keys}
            def tools(entry):
                return sorted([{k: v for k, v in tool.items() if k != "agent_id"}
                               for tool in entry.get("tools", [])], key=lambda item: item["name"])
            expected_tools = tools(original)
            expected_skills = sorted(original.get("skill_names") or [])
            state["source_models"] = original.get("model_ids")
            for key, entry in exported["agent_info"].items():
                entry["name"] = "hitl_" + state["prefix"] + "_" + key
                entry["display_name"] = "算卦助手-澄清验收-" + state["prefix"] + "-" + key
            save(path, state)
            imported = checked(config.post("/agent/import", json={"agent_info": exported}))
            state["agent_id"] = imported["agent_id"]
            state["owned_agents"] = list(imported["agent_id_mapping"].values())
            save(path, state)
            assert state["source"] not in state["owned_agents"]
            checked(config.post(f"/agent/{state['agent_id']}/publish", json={"version_name": "Real HITL validation"}))
            copied = checked(config.post("/agent/export", json={"agent_id": state["agent_id"]}))["data"]
            actual = copied["agent_info"][str(state["agent_id"])]
            assert all(actual.get(key) == value for key, value in expected.items()), "Clone changed source semantics"
            assert "agent_core" not in actual
            assert tools(actual) == expected_tools, "Clone changed authorized tools"
            assert sorted(actual.get("skill_names") or []) == expected_skills, "Clone changed Skills"
            print(json.dumps({"setup": True, "same_model_and_config": True, "same_resources": True,
                              "source_version": state["source_version"]}))
        elif mode == "audit":
            cid = int(sys.argv[3])
            with get_db_session() as session:
                owner = session.query(ConversationRecord).filter_by(conversation_id=cid).one()
                assert owner.agent_id == state["agent_id"] and owner.created_by == state["user"]
                messages = rows(session, ConversationMessage, conversation_id=cid)
                units = rows(session, ConversationMessageUnit, conversation_id=cid)
                forms, responses, terminals = [], [], []
                for unit in units:
                    value = unit["unit_content"]
                    try:
                        parsed = json.loads(value) if isinstance(value, str) else value
                    except (TypeError, ValueError):
                        continue
                    if unit["unit_type"] == "human_interaction":
                        assert parsed.get("type") == "human_interaction" and parsed.get("agent_core") == "jiuwen"
                        form = json.loads(parsed["content"])
                        forms.append({"source_message_id": unit["message_id"], "unit_index": unit["unit_index"],
                                      "form": form})
                    elif unit["unit_type"] == "clarification_response":
                        responses.append(parsed)
                    elif unit["unit_type"] == "run_terminal":
                        terminals.append({k: parsed.get(k) for k in ["status", "end_reason", "agent_core"]})
                print(json.dumps({"message_count": len(messages), "message_statuses": [m["status"] for m in messages],
                                  "messages_hash": digest(messages), "units_hash": digest(units),
                                  "forms": forms, "responses": responses, "terminals": terminals}, ensure_ascii=False))
        elif mode == "cleanup":
            with get_db_session() as session:
                source_unchanged = digest(rows(session, AgentInfo, agent_id=state["source"])) == state["source_hash"]
                history_unchanged = source_history(session, state["source"]) == state["source_history"]
                assert source_unchanged and history_unchanged, "Source assistant or history changed"
                # Recover only this unique owned prefix if import failed before returning a mapping.
                owned = session.query(AgentInfo).filter(AgentInfo.name.startswith("hitl_" + state["prefix"] + "_", autoescape=True),
                    AgentInfo.created_by == state["user"], AgentInfo.tenant_id == state["tenant"],
                    AgentInfo.version_no == 0, AgentInfo.delete_flag == "N").all()
                ids = {a.agent_id for a in owned} | set(state.get("owned_agents", []))
                assert state["source"] not in ids
                conversations = [c.conversation_id for c in session.query(ConversationRecord).filter(
                    ConversationRecord.agent_id.in_(ids), ConversationRecord.created_by == state["user"],
                    ConversationRecord.delete_flag == "N")]
            for cid in conversations:
                checked(runtime.delete(f"/conversation/{cid}"))
            if state.get("source_export_hash"):
                assert digest(checked(config.post("/agent/export", json={"agent_id": state["source"]}))["data"]) == state["source_export_hash"]
            for agent_id in ids:
                checked(config.request("DELETE", "/agent", json={"agent_id": agent_id}))
            path.unlink(missing_ok=True)
            print(json.dumps({"cleanup": True, "source_unchanged": True, "source_history_unchanged": True,
                              "owned_conversations": len(conversations), "owned_agents": len(ids)}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"fixture_failure": type(error).__name__}))
        raise
