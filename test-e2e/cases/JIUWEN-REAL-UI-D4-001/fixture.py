# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned deployment fixtures; private state and credentials never enter test output."""

import hashlib
import json
import re
import sys
import time
import zipfile
from pathlib import Path

import httpx
from management.db.client import get_db_session, minio_client
from management.db.models import AgentInfo, ConversationMessage, ConversationRecord
from management.services.permission.identity.authentication_helpers import generate_session_jwt


def digest(value):
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True).encode()).hexdigest()


def rows(session, model, **filters):
    return [
        {c.name: getattr(row, c.name) for c in model.__table__.columns}
        for row in session.query(model).filter_by(**filters).order_by(*model.__table__.primary_key.columns)
    ]


def checked(response):
    assert response.status_code == 200, f"API status {response.status_code} at {response.request.url.path}"
    return response.json()


def main():
    mode, state_path = sys.argv[1:3]
    path = Path(state_path)
    if mode == "setup":
        source, user, message = int(sys.argv[3]), sys.argv[4], int(sys.argv[5])
        with get_db_session() as session:
            image = session.query(ConversationMessage).filter_by(message_id=message).one()
            owner = session.query(ConversationRecord).filter_by(conversation_id=image.conversation_id).one()
            assert owner.created_by == user, "Image must belong to the authorized user"
            files = json.loads(image.minio_files) if isinstance(image.minio_files, str) else image.minio_files
            reference = next(f for f in files if f.get("type", "").startswith("image/"))
            draft = session.query(AgentInfo).filter_by(agent_id=source, version_no=0, delete_flag="N").one()
            published = session.query(AgentInfo).filter_by(agent_id=source, version_no=draft.current_version_no).one()
            keys = ["business_logic_model_id", "model_ids", "duty_prompt", "constraint_prompt", "few_shots_prompt",
                    "enable_context_manager", "context_policy", "max_steps", "requested_output_tokens",
                    "provide_run_summary", "enable_protocol_repair_retry", "verification_config", "model_params_override"]
            values = {k: getattr(published, k) for k in keys}
            assert values == {k: getattr(draft, k) for k in keys}, "Draft and published source differ"
            from management.services.agent.reasoning import snapshot_agent_reasoning_config

            # Match the management API's effective reasoning snapshot without writing the source.
            values["model_params_override"] = snapshot_agent_reasoning_config(
                model_ids=values["model_ids"],
                requested_overrides=values["model_params_override"],
                existing_overrides=values["model_params_override"],
                tenant_id=published.tenant_id,
            )
            state = {"source": source, "user": user, "source_conversation": image.conversation_id,
                     "source_agent_hash": digest(rows(session, AgentInfo, agent_id=source)),
                     "source_history_hash": digest(rows(session, ConversationMessage, conversation_id=image.conversation_id)),
                     "reference_object": reference["object_name"], "model": published.business_logic_model_id,
                     "source_version": published.version_no, "copied_fields": values,
                     "access_token": generate_session_jwt(user, expires_in=3600), "expires_at": int(time.time()) + 3600}
        path.write_text(json.dumps(state, default=str))
    else:
        state = json.loads(path.read_text())
    headers = {"Authorization": "Bearer " + state["access_token"]}
    with httpx.Client(base_url="http://nexent-config:5010", headers=headers, trust_env=False, timeout=90) as config, \
            httpx.Client(base_url="http://nexent-runtime:5014", headers=headers, trust_env=False, timeout=90) as runtime:
        if mode == "setup":
            exported = checked(config.post("/agent/export", json={"agent_id": state["source"]}))["data"]
            state["source_export_hash"] = digest(exported)
            info = exported["agent_info"][str(state["source"])]
            assert not any(v.get("skill_names") for v in exported["agent_info"].values()), "Unexpected source skills need an explicit fixture policy"
            suffix = path.stem[-12:]
            for key, entry in exported["agent_info"].items():
                entry["name"] = "real_ui_" + suffix + "_" + key
                entry["display_name"] = "文件解析助手-真实验收-" + suffix + "-" + key
            info["agent_core"] = "smolagents"
            result = checked(config.post("/agent/import", json={"agent_info": exported}))
            state["agent_id"] = result["agent_id"]
            state["owned_agents"] = list(result["agent_id_mapping"].values())
            path.write_text(json.dumps(state, default=str))
            checked(config.post("/agent/update", json={"agent_id": state["agent_id"], **state["copied_fields"],
                                                       "agent_core": "smolagents"}))
            checked(config.post(f"/agent/{state['agent_id']}/publish", json={"version_name": "Real-UI-smol",
                                                                          "release_note": "Owned real UI validation"}))
            cloned = checked(config.post("/agent/export", json={"agent_id": state["agent_id"]}))["data"]
            clone_info = cloned["agent_info"][str(state["agent_id"])]
            for key in ["tools", "model_ids", "business_logic_model_id", "duty_prompt", "constraint_prompt", "few_shots_prompt"]:
                left, right = info.get(key), clone_info.get(key)
                if key == "tools":
                    left = sorted([{k: v for k, v in t.items() if k != "agent_id"} for t in left], key=lambda t: t["name"])
                    right = sorted([{k: v for k, v in t.items() if k != "agent_id"} for t in right], key=lambda t: t["name"])
                assert left == right, "Clone configuration mismatch: " + key
            state["image_path"] = str(path.with_suffix(".jpg"))
            success, _ = minio_client.download_file(state["reference_object"], state["image_path"])
            assert success, "Reference image download failed"
            path.write_text(json.dumps(state, default=str))
            print(json.dumps({"setup": True, "source_version": state["source_version"], "same_model_and_tools": True}))
        elif mode == "expect-cm":
            assert sys.argv[3] in {"true", "false"}
            state["copied_fields"]["enable_context_manager"] = sys.argv[3] == "true"
            path.write_text(json.dumps(state, default=str))
            print(json.dumps({"cm_expectation_updated": True}))
        elif mode == "check":
            conversation = int(sys.argv[3])
            with get_db_session() as session:
                owner = session.query(ConversationRecord).filter_by(conversation_id=conversation).one()
                assert owner.created_by == state["user"] and owner.agent_id == state["agent_id"]
                messages = session.query(ConversationMessage).filter_by(conversation_id=conversation).order_by(
                    ConversationMessage.message_index, ConversationMessage.message_id).all()
                draft = session.query(AgentInfo).filter_by(agent_id=state["agent_id"], version_no=0).one()
                published = session.query(AgentInfo).filter_by(agent_id=state["agent_id"], version_no=draft.current_version_no).one()
                assert all(getattr(published, k) == v for k, v in state["copied_fields"].items()), "Configuration changed beyond Core"
                print(json.dumps({"core": published.agent_core, "version": published.version_no,
                                  "messages": [{"id": m.message_id, "index": m.message_index, "role": m.message_role,
                                                "status": m.status, "hash": digest(m.message_content)} for m in messages]}))
        elif mode == "verify-docx":
            conversation, marker = int(sys.argv[3]), sys.argv[4]
            with get_db_session() as session:
                owner = session.query(ConversationRecord).filter_by(conversation_id=conversation).one()
                assert owner.agent_id == state["agent_id"] and owner.created_by == state["user"]
                latest = session.query(ConversationMessage).filter_by(
                    conversation_id=conversation, message_role="assistant").order_by(
                        ConversationMessage.message_id.desc()).first()
                refs = re.findall(r"s3://[^\s)\]<>\"']+\.docx", latest.message_content)
                assert refs, "Generated docx link is missing"
            bucket, key = refs[-1][5:].split("/", 1)
            artifact = path.with_suffix(".docx")
            try:
                success, _ = minio_client.download_file(key, str(artifact), bucket=bucket)
                assert success, "Generated docx download failed"
                with zipfile.ZipFile(artifact) as document:
                    assert marker in document.read("word/document.xml").decode(), "Document marker mismatch"
            finally:
                artifact.unlink(missing_ok=True)
            print(json.dumps({"downloaded_docx_verified": True}))
        elif mode == "cleanup":
            with get_db_session() as session:
                assert digest(rows(session, AgentInfo, agent_id=state["source"])) == state["source_agent_hash"], "Source assistant changed"
                assert digest(rows(session, ConversationMessage, conversation_id=state["source_conversation"])) == state["source_history_hash"], "Source history changed"
                owned = session.query(ConversationRecord).filter_by(agent_id=state.get("agent_id"), created_by=state["user"]).all() if state.get("agent_id") else []
                ids = [c.conversation_id for c in owned]
                objects = set()
                for c in ids:
                    for m in session.query(ConversationMessage).filter_by(conversation_id=c):
                        files = json.loads(m.minio_files) if isinstance(m.minio_files, str) else m.minio_files
                        for f in files or []:
                            if f.get("object_name") != state["reference_object"]:
                                objects.add(f["object_name"])
            for obj in objects:
                checked(config.delete("/file/storage/" + obj))
            for c in ids:
                checked(runtime.delete(f"/conversation/{c}"))
            if state.get("source_export_hash"):
                assert digest(checked(config.post("/agent/export", json={"agent_id": state["source"]}))["data"]) == state["source_export_hash"], "Source tree configuration changed"
            for agent in state.get("owned_agents", [state["agent_id"]] if state.get("agent_id") else []):
                checked(config.request("DELETE", "/agent", json={"agent_id": agent}))
            Path(state.get("image_path", str(path.with_suffix(".jpg")))).unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            print(json.dumps({"cleanup": True, "source_unchanged": True, "owned_conversations": len(ids), "uploads": len(objects)}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("FIXTURE_FAILURE=" + type(error).__name__ + ": " + str(error)[:180])
        raise SystemExit(1)
