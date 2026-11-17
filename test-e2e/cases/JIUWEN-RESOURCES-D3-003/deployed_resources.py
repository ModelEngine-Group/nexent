# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real saved resources through deployed APIs; private events stay in owned files."""

import importlib.util
import json
import re
import sys
import time
import traceback
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from management.db.client import get_db_session, minio_client
from management.db.models import AgentInfo, AgentRelation, ConversationRecord
from gateway.authentication.auth import (
    generate_session_jwt,
)


def main():
    input_path, helper_path, directory = map(Path, sys.argv[1:4])
    inputs = json.loads(input_path.read_text())
    directory.mkdir(exist_ok=True)
    spec = importlib.util.spec_from_file_location("owned_skill_fixture", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    state_path = directory / "skill-state.json"
    report_path = directory / "report.json"
    report = {"profile": "real_smoke", "scenarios": {}}
    owned, objects, snapshots = [], set(), {}
    config = runtime = None

    def fixture(mode, *args):
        sys.argv = [str(helper_path), mode, str(state_path), *map(str, args)]
        helper.main()

    def save():
        report_path.write_text(json.dumps(report, indent=2))

    def publish(agent):
        helper.checked(config.post(f"/agent/{agent}/publish", json={"version_name": "Resource-acceptance"}))
        with get_db_session() as session:
            draft = session.query(AgentInfo).filter_by(agent_id=agent, version_no=0).one()
            row = session.query(AgentInfo).filter_by(agent_id=agent, version_no=draft.current_version_no).one()
            return row.version_no, row.agent_core, list(row.model_ids)

    def clone(source, label, core, model, **patch):
        exported = helper.export_agent(config, source)
        snapshots[source] = (helper.digest(helper.source_rows(source)), helper.digest(exported))
        assert len(exported["agent_info"]) == 1
        entry = exported["agent_info"][str(source)]
        entry["name"] = "resource_" + label + "_" + directory.name[-10:]
        entry["display_name"] = "Resource acceptance " + label + " " + directory.name[-10:]
        result = helper.checked(config.post("/agent/import", json={"agent_info": exported}))
        agent = result["agent_id"]
        owned.append(agent)
        helper.checked(config.post("/agent/update", json={
            "agent_id": agent, "agent_core": core, "model_ids": [model], "enable_context_manager": False,
            "provide_run_summary": False, "verification_config": {"enabled": False},
            "enable_protocol_repair_retry": False, **patch}))
        return agent, publish(agent)

    def run(agent, version, model, query, label, conversation=None):
        body = {"agent_id": agent, "version_no": version, "model_id": model, "query": query}
        if conversation:
            body.update(conversation_id=conversation, history=[])
        response = runtime.post("/agent/run", json=body)
        assert response.status_code == 200, f"Run HTTP {response.status_code}"
        conversation = conversation or int(response.headers["conversation_id"])
        events = [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")]
        (directory / (label + ".private.json")).write_text(json.dumps(events))
        assert not [e for e in events if e.get("type") == "error"], "Run error event"
        for _ in range(100):
            rows = helper.history(conversation)
            if rows and rows[-1]["role"] == "assistant" and rows[-1]["status"] == "completed":
                break
            time.sleep(.1)
        assert rows[-1]["status"] == "completed", "Persisted run did not complete"
        terminal = [e for e in events if e.get("type") == "run_terminal" and not e.get("invocation_id")]
        final = terminal[0].get("final_content", "") if terminal else ""
        if terminal:
            assert len(terminal) == 1 and terminal[0]["status"] == "completed"
        else:
            from management.db.models import ConversationMessage

            with get_db_session() as session:
                final = session.query(ConversationMessage).filter_by(message_id=rows[-1]["id"]).one().message_content
            assert any(e.get("type") == "final_answer" and e.get("answer_phase") == "complete"
                       and not e.get("invocation_id") for e in events), "Missing root completion"
        assert final and not re.search(r"completed_action_history|historical_attachments|</?final_answer\b", final)
        return conversation, events, final, rows

    def verify_docx(final, marker):
        refs = re.findall(r"s3://[^\s)\]<>\"']+\.docx", final)
        assert refs, "No actual docx link"
        bucket, key = refs[-1][5:].split("/", 1)
        objects.add(key)
        artifact = directory / "document.docx"
        try:
            success, _ = minio_client.download_file(key, str(artifact), bucket=bucket)
            assert success, "Actual document download failed"
            with zipfile.ZipFile(artifact) as document:
                assert marker in document.read("word/document.xml").decode(), "Document content mismatch"
        finally:
            artifact.unlink(missing_ok=True)

    def require_successful_workspace_script(events):
        calls = {e.get("local_call_id") for e in events if e.get("type") == "tool"
                 and e.get("tool_name") == "run_skill_script"
                 and (e.get("tool_arguments") or {}).get("source") == "workspace"}
        results = [e for e in events if e.get("type") == "tool_result" and e.get("local_call_id") in calls]
        assert any(not e.get("is_error") and not str(e.get("content", "")).startswith("[") for e in results), (
            "No successful workspace Skill script; a fallback document does not prove script capability")

    def follow(agent, version, model, conversation, marker, rows, label):
        cid, events, final, later = run(agent, version, model,
            "只根据本会话已完成的结果，回复上轮结果和上轮用户指定的验收编号（不要使用内部运行ID）。不要调用工具或子智能体，不要重复之前任务。",
            label + "_follow", conversation)
        assert cid == conversation and marker in final
        assert not [e for e in events if e.get("type") in {"tool", "subagent_start"}], "Follow-up replayed resources"
        assert later[:len(rows)] == rows, "Saved history changed"

    try:
        source = inputs["skill_source"]
        with get_db_session() as session:
            draft = session.query(AgentInfo).filter_by(agent_id=source, version_no=0, delete_flag="N").one()
            original = [row.conversation_id for row in session.query(ConversationRecord).filter_by(
                agent_id=source, created_by=inputs["user_id"]).all()]
            state = {"source": source, "user": inputs["user_id"], "source_version": draft.current_version_no,
                "source_hash": helper.digest(helper.source_rows(source)), "objects": [],
                "source_history": {str(cid): helper.history(cid) for cid in original},
                "access_token": generate_session_jwt(inputs["user_id"], expires_in=3600)}
        headers = {"Authorization": "Bearer " + state["access_token"]}
        config = httpx.Client(base_url="http://nexent-config:5010", headers=headers, trust_env=False, timeout=90)
        runtime = httpx.Client(base_url="http://nexent-runtime:5014", headers=headers, trust_env=False, timeout=600)
        source_skills = helper.checked(config.get("/skills/instance/list", params={
            "agent_id": source, "version_no": state["source_version"]}))["instances"]
        enabled = [skill for skill in source_skills if skill.get("enabled")]
        assert any(skill.get("skill_name") == "docx" for skill in enabled), "Authorized source must bind docx"
        state["source_skills_hash"] = helper.digest(source_skills)
        state["source_export_hash"] = helper.digest(helper.export_agent(config, source))
        child, _ = clone(source, "skill_child", "jiuwen", inputs["child_model"])
        # This clone has an explicit resource policy, without changing the saved source.
        for skill in enabled:
            helper.checked(config.post("/skills/instance/update", json={"agent_id": child,
                "skill_id": skill["skill_id"], "enabled": True, "version_no": 0,
                "config_values": skill.get("config_values") or {}}))
        state["agent_id"] = child
        state_path.write_text(json.dumps(state))
        owned.remove(child)
        child_version, child_core, child_models = publish(child)
        assert child_core == "jiuwen" and child_models[0] == inputs["child_model"]

        def skills():
            marker = "SKILLS_" + directory.name
            cid, events, final, rows = run(child, child_version, inputs["child_model"],
                f"本次用户指定的验收编号为{marker}。帮我生成一个简单docx文件，正文包含该编号。必须遵循docx Skill的JavaScript/docx库工作流，实际运行生成脚本，不要改用python-docx。实际生成并上传，回复上传工具原样返回的s3://文件链接和上述用户指定验收编号，不要使用内部运行ID或自造HTTP域名。", "skills")
            names = [e.get("tool_name") for e in events if e.get("type") == "tool"]
            assert "read_skill_md" in names and "nexent_execute_python" in names and "upload_to_s3" in names
            assert "download_from_s3" not in names
            require_successful_workspace_script(events)
            verify_docx(final, marker)
            follow(child, child_version, inputs["child_model"], cid, marker, rows, "skills")
            return {"completed": True, "docx_verified": True, "workspace_script_verified": True,
                    "tool_names": names, "no_replay": True}

        def mcp():
            agent, (version, core, models) = clone(inputs["knowledge_source"], "mcp", "jiuwen", inputs["child_model"],
                enabled_tool_ids=[inputs["mcp_tool_id"]], prompt="Use the configured external MCP tool to answer actual current date queries.")
            assert core == "jiuwen"
            marker = "MCP_" + directory.name
            cid, events, final, rows = run(agent, version, models[0],
                f"必须调用get_current_date工具读取今天的日期，回复工具得到的日期及验收编号{marker}。", "mcp")
            calls = [e for e in events if e.get("type") == "tool" and e.get("tool_name") == "get_current_date"]
            assert len(calls) == 1, "External MCP call missing or repeated"
            results = [e for e in events if e.get("type") == "tool_result" and
                       e.get("local_call_id") == calls[0].get("local_call_id")]
            assert results and not any(e.get("is_error") for e in results)
            today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
            assert today in json.dumps(results) and today in final and marker in final
            follow(agent, version, models[0], cid, marker, rows, "mcp")
            return {"completed": True, "date_verified": True, "external_tool_calls": 1, "no_replay": True}

        def knowledge():
            agent, (version, core, models) = clone(inputs["knowledge_source"], "knowledge", "jiuwen", inputs["child_model"])
            assert core == "jiuwen"
            marker = "KB_" + directory.name
            cid, events, final, rows = run(agent, version, models[0],
                f"请必须检索已配置F1知识库的F1规则.docx：排位赛Q1、Q2、Q3分别决定哪些发车顺序？根据检索内容回答并注明来源文件，回复验收编号{marker}。", "knowledge")
            assert any(e.get("type") == "tool" and e.get("tool_name") == "knowledge_base_search" for e in events)
            evidence = [e for e in events if e.get("type") in {"search_content", "tool_result"}]
            rendered = json.dumps(evidence, ensure_ascii=False)
            assert "F1规则.docx" in rendered and "Q1" in rendered and "Q3" in rendered, "Actual indexed content missing"
            assert all(value in final for value in [marker, "Q1", "Q2", "Q3"])
            follow(agent, version, models[0], cid, marker, rows, "knowledge")
            return {"completed": True, "indexed_source_verified": True, "real_search": True, "no_replay": True}

        def mixed():
            agent, (version, core, models) = clone(inputs["knowledge_source"], "parent", "smolagents", inputs["parent_model"],
                enabled_tool_ids=[], related_agents=[{"agent_id": child, "version_no": child_version}],
                prompt="Delegate every document generation task to the configured file generation child. Report the actual child file link and result. Never generate the document yourself.")
            with get_db_session() as session:
                relation = session.query(AgentRelation).filter_by(parent_agent_id=agent, version_no=version, delete_flag="N").one()
                assert relation.selected_agent_id == child and relation.selected_agent_version_no == child_version
            assert core == "smolagents" and models[0] != child_models[0]
            marker = "MIXED_" + directory.name
            cid, events, final, rows = run(agent, version, models[0],
                f"请调用文件生成子智能体，实际生成并上传一个docx文件，正文包含验收编号{marker}。让子智能体遵循docx Skill的JavaScript/docx库工作流，实际运行生成脚本，不要改用python-docx。最终回复文件链接和编号。", "mixed")
            starts = [e for e in events if e.get("type") == "subagent_start"]
            ends = [e for e in events if e.get("type") == "subagent_end"]
            assert len(starts) == len(ends) == 1 and starts[0]["invocation_id"] == ends[0]["invocation_id"]
            start_payload = json.loads(starts[0]["content"])
            assert str(starts[0]["agent_id"]) == str(child) and start_payload["version_no"] == child_version
            invocation = starts[0]["invocation_id"]
            steps = [e for e in events if e.get("type") == "step_observation" and e.get("invocation_id") == invocation]
            assert steps, "Jiuwen child public steps missing"
            names = [e.get("tool_name") for e in events if e.get("type") == "tool" and e.get("invocation_id") == invocation]
            assert "read_skill_md" in names and "nexent_execute_python" in names and "upload_to_s3" in names
            require_successful_workspace_script(events)
            verify_docx(final, marker)
            follow(agent, version, models[0], cid, marker, rows, "mixed")
            return {"completed": True, "parent_core": core, "child_core": child_core, "independent_models": True,
                    "child_docx_verified": True, "workspace_script_verified": True,
                    "child_tools": names, "no_replay": True}

        available_scenarios = [("external_mcp", mcp), ("knowledge", knowledge), ("skills", skills), ("mixed_core", mixed)]
        selected = inputs.get("diagnostic_scenarios", [label for label, _ in available_scenarios])
        assert selected and len(set(selected)) == len(selected)
        assert set(selected).issubset({label for label, _ in available_scenarios}), "Unknown diagnostic scenario"
        report["not_executed"] = [label for label, _ in available_scenarios if label not in selected]
        for label, execute in available_scenarios:
            if label not in selected:
                continue
            try:
                report["scenarios"][label] = execute()
            except Exception as error:  # noqa: BLE001 -- Retain each diagnostic failure and continue independent scenarios.
                report["scenarios"][label] = {"completed": False, "error_type": type(error).__name__, "reason": str(error)[:180]}
                (directory / (label + ".trace")).write_text(traceback.format_exc())
            save()
            print("RESOURCE_SCENARIO=" + json.dumps({label: report["scenarios"][label]}), flush=True)
    except Exception as error:  # noqa: BLE001 -- Fixture boundary must record setup failure and run owned cleanup.
        report["setup_error"] = type(error).__name__ + ": " + str(error)[:180]
        (directory / "setup.trace").write_text(traceback.format_exc())
    finally:
        try:
            if config:
                for source, (row_hash, export_hash) in snapshots.items():
                    assert helper.digest(helper.source_rows(source)) == row_hash, "Original source changed"
                    assert helper.digest(helper.export_agent(config, source)) == export_hash, "Original bindings changed"
                from management.db.models import ConversationMessage

                with get_db_session() as session:
                    conversations = [r.conversation_id for r in session.query(ConversationRecord).filter(
                        ConversationRecord.agent_id.in_(owned), ConversationRecord.created_by == inputs["user_id"]).all()]
                    artifact_conversations = [r.conversation_id for r in session.query(ConversationRecord).filter(
                        ConversationRecord.agent_id.in_([*owned, state.get("agent_id")]),
                        ConversationRecord.created_by == inputs["user_id"]).all()]
                    for message in session.query(ConversationMessage).filter(
                            ConversationMessage.conversation_id.in_(artifact_conversations)):
                        for reference in re.findall(r"s3://[^\s)\]<>\"']+", message.message_content or ""):
                            parts = reference[5:].split("/", 1)
                            if len(parts) == 2 and parts[1].startswith("workspace/" + inputs["user_id"] + "/"):
                                objects.add(parts[1])
                for key in objects:
                    helper.checked(config.delete("/file/storage/" + key))
                for cid in conversations:
                    helper.checked(runtime.delete(f"/conversation/{cid}"))
                for agent in reversed(owned):
                    helper.checked(config.request("DELETE", "/agent", json={"agent_id": agent}))
            if state_path.exists():
                fixture("cleanup")
            report["cleanup"] = True
            report["source_unchanged"] = True
        except Exception as error:  # noqa: BLE001 -- Cleanup failure must remain a failing acceptance result.
            report["cleanup"] = False
            report["cleanup_error"] = type(error).__name__ + ": " + str(error)[:180]
        finally:
            if config:
                config.close()
                runtime.close()
        report["status"] = (("PASS" if len(report["scenarios"]) == 4 else "PARTIAL_PASS")
            if (report["scenarios"] and all(row["completed"] for row in report["scenarios"].values())
                and report.get("cleanup")) else "FAIL")
        save()
        print("RESOURCE_RESULT=" + json.dumps(report), flush=True)
    return report["status"] == "PASS"


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
