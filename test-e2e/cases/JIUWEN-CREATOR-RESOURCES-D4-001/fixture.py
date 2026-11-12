# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Own only a unique creator conversation and its new draft; never expose auth."""

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

from gateway.authentication.auth import generate_session_jwt
from management.db.skill.models import SkillInfo, SkillInstance
from services.nl2agent_service import _load_installed_resource_catalog
from management.db.client import get_db_session
from management.db.models import AgentInfo, ConversationMessage, ConversationMessageUnit, ConversationRecord


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def records(session, model, condition):
    return [{c.name: getattr(r, c.name) for c in model.__table__.columns}
            for r in session.query(model).filter(condition).order_by(*model.__table__.primary_key.columns)]


def original(session, state):
    return {"SkillInfo": digest(records(session, SkillInfo, SkillInfo.skill_id == state["skill"]["id"]))} | {model.__name__: digest(records(session, model, model.conversation_id.in_(state["original_conversations"])))
            for model in (ConversationRecord, ConversationMessage, ConversationMessageUnit)} | {"AgentInfo": digest(records(session, AgentInfo, AgentInfo.agent_id.in_(state["original_agents"])))}


def main():
    mode, filename = sys.argv[1:3]
    path = Path(filename)
    if mode == "setup":
        with get_db_session() as session:
            agent = session.query(AgentInfo).filter_by(agent_id=int(sys.argv[3]), version_no=0, delete_flag="N").one()
            suffix = path.stem[-12:]
            state = {"actor": agent.created_by, "tenant": agent.tenant_id, "name": "agent-card-" + suffix,
                     "marker": "CREATOR_HISTORY_" + suffix, "access_token": generate_session_jwt(agent.created_by, expires_in=1800),
                     "expires_at": int(time.time()) + 1800}
            state["original_conversations"] = [r.conversation_id for r in session.query(ConversationRecord)
                                                .filter_by(created_by=state["actor"])]
            state["original_agents"] = [r.agent_id for r in session.query(AgentInfo).filter_by(created_by=state["actor"])]
            catalog = asyncio.run(_load_installed_resource_catalog(tenant_id=state["tenant"], user_id=state["actor"]))
            skills = [r for r in catalog if r["resource_type"] == "skill" and r["config"] == []]
            assert skills, "No visible no-configuration Skill"
            skill = sorted(skills, key=lambda r: ("docx" not in r["name"].lower(), r["name"]))[0]
            state["skill"] = {"id": int(skill["candidate_ref"].split(":")[-1]), "name": skill["name"],
                              "ref": skill["candidate_ref"], "description": skill["description"]}
            state["original_hashes"] = original(session, state)
        path.write_text(json.dumps(state), encoding="utf-8")
        print(json.dumps({"setup": True}))
        return
    state = json.loads(path.read_text(encoding="utf-8"))
    if mode == "audit":
        cid = int(sys.argv[3])
        with get_db_session() as session:
            conv = session.query(ConversationRecord).filter_by(conversation_id=cid, created_by=state["actor"]).one()
            assert cid not in state["original_conversations"]
            messages = records(session, ConversationMessage, ConversationMessage.conversation_id == cid)
            assert any(state["marker"] in (r["message_content"] or "") for r in messages if r["message_role"] == "user")
            units = records(session, ConversationMessageUnit, ConversationMessageUnit.conversation_id == cid)
            target = conv.target or {}
            assert target.get("type") == "agent" and target["id"] not in state["original_agents"]
            draft = session.query(AgentInfo).filter_by(agent_id=target["id"], version_no=0, created_by=state["actor"], tenant_id=state["tenant"]).one()
            print(json.dumps({"target_id": target["id"], "description": draft.description, "prompt": draft.prompt,
                              "messages_hash": digest(messages), "units_hash": digest(units),
                              "bindings": [{"skill_id": r.skill_id, "enabled": r.enabled, "config_values": r.config_values}
                                           for r in session.query(SkillInstance).filter_by(agent_id=target["id"], version_no=0, delete_flag="N")],
                              "mode": (conv.workbench_config or {}).get("mode")}))
        return
    assert mode == "cleanup"
    with get_db_session() as session:
        assert original(session, state) == state["original_hashes"], "Pre-existing history changed"
        owned = [r.conversation_id for r in session.query(ConversationRecord).filter_by(created_by=state["actor"], delete_flag="N")
                 if r.conversation_id not in state["original_conversations"] and session.query(ConversationMessage).filter(
                     ConversationMessage.conversation_id == r.conversation_id,
                     ConversationMessage.message_content.contains(state["marker"])).first()]
        drafts = {r.target["id"] for r in session.query(ConversationRecord).filter(ConversationRecord.conversation_id.in_(owned))
                  if r.target and r.target.get("type") == "agent"}
        assert not drafts.intersection(state["original_agents"])
        for aid in drafts:
            session.query(AgentInfo).filter_by(agent_id=aid, version_no=0, created_by=state["actor"], tenant_id=state["tenant"]).one()
    headers = {"Authorization": "Bearer " + state["access_token"]}
    with httpx.Client(headers=headers, trust_env=False, timeout=30) as client:
        for cid in owned:
            assert client.delete(f"http://nexent-runtime:5014/conversation/{cid}").status_code == 200
        for aid in drafts:
            assert client.request("DELETE", "http://nexent-config:5010/agent", json={"agent_id": aid}).status_code == 200
    with get_db_session() as session:
        assert original(session, state) == state["original_hashes"], "Cleanup changed pre-existing data"
        assert not session.query(AgentInfo).filter(AgentInfo.agent_id.in_(drafts), AgentInfo.delete_flag == "N").count()
        assert not session.query(ConversationRecord).filter(ConversationRecord.conversation_id.in_(owned), ConversationRecord.delete_flag == "N").count()
    path.unlink()
    print(json.dumps({"cleanup": True, "original_history_unchanged": True,
                      "owned_conversations": len(owned), "owned_drafts": len(drafts)}))


if __name__ == "__main__":
    main()
