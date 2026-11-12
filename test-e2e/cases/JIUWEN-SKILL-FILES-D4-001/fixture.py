# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Clone authorized saved Skill bindings; keep all private state outside Git."""

import hashlib
import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path

import httpx
from management.db.client import get_db_session, minio_client
from management.db.models import AgentInfo, ConversationMessage, ConversationRecord
from gateway.authentication.auth import generate_session_jwt


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def source_rows(source):
    with get_db_session() as session:
        return [{c.name: getattr(row, c.name) for c in AgentInfo.__table__.columns}
                for row in session.query(AgentInfo).filter_by(agent_id=source).order_by(AgentInfo.version_no)]


def checked(response):
    assert response.status_code == 200, f"API {response.status_code} at {response.request.url.path}"
    return response.json()


def export_agent(config, agent_id):
    response = config.post("/agent/export", json={"agent_id": agent_id})
    assert response.status_code == 200
    if response.headers.get("content-type", "").startswith("application/zip"):
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            return json.loads(archive.read("agent.json"))
    return response.json()["data"]


def history(conversation):
    with get_db_session() as session:
        return [{"id": row.message_id, "index": row.message_index, "role": row.message_role,
                 "status": row.status, "hash": digest(row.message_content)}
                for row in session.query(ConversationMessage).filter_by(conversation_id=conversation).order_by(
                    ConversationMessage.message_index, ConversationMessage.message_id)]


def main():
    mode, filename = sys.argv[1:3]
    path = Path(filename)
    if mode == "setup":
        source, user = int(sys.argv[3]), sys.argv[4]
        with get_db_session() as session:
            draft = session.query(AgentInfo).filter_by(agent_id=source, version_no=0, delete_flag="N").one()
            published = session.query(AgentInfo).filter_by(agent_id=source, version_no=draft.current_version_no).one()
            assert published.agent_core in {"smolagents", "jiuwen"}, "Unsupported source Core"
            originals = session.query(ConversationRecord).filter_by(agent_id=source, created_by=user).all()
            conversations = {row.conversation_id: history(row.conversation_id) for row in originals}
            keys = ["model_ids", "business_logic_model_id", "prompt",
                    "enable_context_manager", "max_steps", "provide_run_summary", "verification_config",
                    "enable_protocol_repair_retry", "requested_output_tokens", "context_policy", "model_params_override"]
            fields = {key: getattr(published, key) for key in keys}
            state = {"source": source, "user": user, "tenant": published.tenant_id,
                     "source_hash": digest(source_rows(source)), "source_history": conversations,
                     "source_version": published.version_no, "fields": fields,
                     "access_token": generate_session_jwt(user, expires_in=3600),
                     "expires_at": int(time.time()) + 3600, "objects": []}
        path.write_text(json.dumps(state, default=str))
    else:
        state = json.loads(path.read_text())
    headers = {"Authorization": "Bearer " + state["access_token"]}
    with httpx.Client(base_url="http://nexent-config:5010", headers=headers, trust_env=False, timeout=90) as config, \
            httpx.Client(base_url="http://nexent-runtime:5014", headers=headers, trust_env=False, timeout=90) as runtime:
        if mode == "setup":
            exported = export_agent(config, state["source"])
            assert len(exported["agent_info"]) == 1, "Fixture expects standalone file generator"
            state["source_export_hash"] = digest(exported)
            skills = checked(config.get("/skills/instance/list", params={
                "agent_id": state["source"], "version_no": state["source_version"]}))["instances"]
            enabled = [s for s in skills if s.get("enabled")]
            assert any(s.get("skill_name") == "docx" for s in enabled), "Source must bind docx Skill"
            state["source_skills_hash"] = digest(skills)
            entry = exported["agent_info"][str(state["source"])]
            entry["name"] = "skill_files_" + path.stem[-12:]
            entry["display_name"] = "鏂囦欢鐢熸垚鍔╂墜-Skill楠屾敹-" + path.stem[-12:]
            result = checked(config.post("/agent/import", json={"agent_info": exported}))
            state["agent_id"] = result["agent_id"]
            path.write_text(json.dumps(state, default=str))
            checked(config.post("/agent/update", json={"agent_id": state["agent_id"], **state["fields"],
                                                       "agent_core": "jiuwen"}))
            for skill in enabled:
                checked(config.post("/skills/instance/update", json={"agent_id": state["agent_id"],
                    "skill_id": skill["skill_id"], "enabled": True, "version_no": 0,
                    "config_values": skill.get("config_values") or {}}))
            checked(config.post(f"/agent/{state['agent_id']}/publish", json={"version_name": "Skill-files-real"}))
            cloned = export_agent(config, state["agent_id"])
            clone = cloned["agent_info"][str(state["agent_id"])]
            assert clone["agent_core"] == "jiuwen", "Owned target must use Jiuwen"
            for key in ["model_ids", "prompt"]:
                assert clone[key] == entry[key], "Clone mismatch: " + key
            # Skill bindings have no priority order; retain exact membership and duplicate checks.
            assert sorted(clone["skill_names"]) == sorted(entry["skill_names"]), "Clone mismatch: skill_names"
            left = [{k: v for k, v in t.items() if k != "agent_id"} for t in entry["tools"]]
            right = [{k: v for k, v in t.items() if k != "agent_id"} for t in clone["tools"]]
            assert sorted(left, key=str) == sorted(right, key=str), "Clone tool mismatch"
            print(json.dumps({"setup": True, "docx_skill": True, "equivalent_configuration": True}))
        elif mode == "select-model":
            model = int(sys.argv[3])
            assert model in state["fields"]["model_ids"]
            checked(config.post("/agent/update", json={"agent_id": state["agent_id"],
                "model_ids": [model] + [m for m in state["fields"]["model_ids"] if m != model]}))
            checked(config.post(f"/agent/{state['agent_id']}/publish", json={"version_name": "Skill-files-" + str(model)}))
            print(json.dumps({"selected": model}))
        elif mode in {"check", "verify-docx"}:
            conversation = int(sys.argv[3])
            with get_db_session() as session:
                owner = session.query(ConversationRecord).filter_by(conversation_id=conversation).one()
                assert owner.agent_id == state["agent_id"] and owner.created_by == state["user"]
                latest = session.query(ConversationMessage).filter_by(
                    conversation_id=conversation, message_role="assistant").order_by(
                        ConversationMessage.message_id.desc()).first()
                content = latest.message_content
            if mode == "check":
                print(json.dumps({"messages": history(conversation)}))
            else:
                refs = re.findall(r"s3://[^\s)\]<>\"']+\.docx", content)
                assert refs, "Missing actual docx link"
                bucket, key = refs[-1][5:].split("/", 1)
                state["objects"] = list(set([*state["objects"], key]))
                path.write_text(json.dumps(state, default=str))
                artifact = path.with_suffix(".docx")
                try:
                    success, _ = minio_client.download_file(key, str(artifact), bucket=bucket)
                    assert success
                    with zipfile.ZipFile(artifact) as document:
                        assert sys.argv[4] in document.read("word/document.xml").decode()
                finally:
                    artifact.unlink(missing_ok=True)
                print(json.dumps({"downloaded_docx_verified": True}))
        elif mode == "cleanup":
            assert digest(source_rows(state["source"])) == state["source_hash"], "Source agent changed"
            for conversation, rows in state["source_history"].items():
                assert history(int(conversation)) == rows, "Source history changed"
            current = checked(config.get("/skills/instance/list", params={
                "agent_id": state["source"], "version_no": state["source_version"]}))["instances"]
            assert digest(current) == state["source_skills_hash"], "Source Skill bindings changed"
            assert digest(export_agent(config, state["source"])) == state["source_export_hash"]
            with get_db_session() as session:
                ids = [r.conversation_id for r in session.query(ConversationRecord).filter_by(
                    agent_id=state.get("agent_id"), created_by=state["user"]).all()] if state.get("agent_id") else []
            for key in state["objects"]:
                checked(config.delete("/file/storage/" + key))
            for conversation in ids:
                checked(runtime.delete(f"/conversation/{conversation}"))
            if state.get("agent_id"):
                checked(config.request("DELETE", "/agent", json={"agent_id": state["agent_id"]}))
            path.unlink(missing_ok=True)
            print(json.dumps({"cleanup": True, "source_unchanged": True, "conversations": len(ids)}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        import traceback

        Path(sys.argv[2] + ".trace").write_text(traceback.format_exc())
        print("FIXTURE_FAILURE=" + type(error).__name__ + ": " + str(error)[:180])
        raise SystemExit(1)
