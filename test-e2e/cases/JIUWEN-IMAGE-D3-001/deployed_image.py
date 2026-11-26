# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Qualify an authorized image through the deployed assistant without altering its configuration."""

import json
import sys
import time
import traceback

import httpx
from infrastructure.rdb.client import get_db_session
from management.db.models import AgentInfo, ConversationMessage, ConversationMessageUnit, ConversationRecord
from management.services.permission.identity.session import generate_session_jwt


def main():
    agent_id, source_id = int(sys.argv[1]), int(sys.argv[2])
    user, expected = sys.argv[3:5]
    vision_model_id = int(sys.argv[5]) if sys.argv[5] else None
    with get_db_session() as session:
        source = session.query(ConversationMessage).filter_by(message_id=source_id, message_role="user").one()
        owner = session.query(ConversationRecord).filter_by(conversation_id=source.conversation_id).one()
        assert owner.created_by == user, "Source image ownership mismatch"
        files = json.loads(source.minio_files) if isinstance(source.minio_files, str) else source.minio_files
        assert files and any(f.get("type", "").startswith("image/") for f in files), "Image fixture required"
        agent_name = session.query(AgentInfo).filter_by(
            agent_id=agent_id, version_no=0, created_by=user, delete_flag="N"
        ).one().name

    headers = {"Authorization": "Bearer " + generate_session_jwt(user, expires_in=1800)}
    conversation = None
    with httpx.Client(base_url="http://nexent-gateway:5013/api", headers=headers, trust_env=False, timeout=240) as client:
        deployment = client.get("/tenant_config/deployment_version")
        assert deployment.status_code == 200 and deployment.json().get("agent_core") == "jiuwen"
        try:
            response = client.put("/conversation/create", json={"title": "Jiuwen image regression verification"})
            assert response.status_code == 200, "Conversation creation failed"
            conversation = response.json()["data"]["conversation_id"]
            saved = None
            counts = []
            for index, query in enumerate(
                [
                    "分析一下上传图片的内容，请调用图片分析工具，根据实际结果回答。",
                    "根据上轮已经完成的图片分析，图中衣服的主要颜色是什么？只用已有结果，不要重新调用任何工具。",
                ]
            ):
                tool_configuration = {}
                if vision_model_id is not None:
                    tool_configuration = {"tool_params": {"agents": {
                        agent_name: {"tools": {"analyze_image": {"selected_model_id": vision_model_id}}},
                    }}}
                response = client.post(
                    "/agent/run",
                    json={
                        "agent_id": agent_id,
                        "conversation_id": conversation,
                        "query": query,
                        "history": [],
                        "minio_files": files if not index else [],
                        **tool_configuration,
                    },
                )
                assert response.status_code == 200, "Runtime HTTP failed"
                events = [
                    json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:") and line[5:].strip() != "[DONE]"
                ]
                finals = [e for e in events if e.get("type") == "final_answer"
                          and e.get("answer_phase") == "complete" and not e.get("invocation_id")]
                assert len(finals) == 1 and not any(e.get("type") == "error" for e in events), "Root execution failed"
                calls = [e for e in events if e.get("type") == "tool"]
                if not index:
                    image_calls = [e for e in calls if e.get("tool_name") == "analyze_image"]
                    assert len(image_calls) == 1, "Image must actually be analyzed once"
                    results = [
                        e
                        for e in events
                        if e.get("type") == "execution_logs"
                        and e.get("tool_call_id") == image_calls[0]["tool_call_id"]
                        and isinstance(e.get("is_error"), bool)
                    ]
                    if len(results) != 1 or results[0].get("is_error") is True:
                        print("IMAGE_FAILURE=" + json.dumps({
                            "matched_results": len(results),
                            "execution_logs": sum(e.get("type") == "execution_logs" for e in events),
                            "tool_result_error": any(e.get("is_error") is True for e in results),
                        }), flush=True)
                    assert len(results) == 1 and results[0].get("is_error") is not True, "Image tool failed"
                    text = str(results[0].get("content", ""))
                    assert len(text) > 40 and expected in text, "Visual result lacks expected fixture fact"
                else:
                    assert not calls, "Follow-up replayed a tool"
                final = finals[0].get("content") or ""
                assert len(final) > 3 and expected in final, "Answer lacks the known image fact"
                for _ in range(40):
                    with get_db_session() as session:
                        messages = (
                            session.query(ConversationMessage)
                            .filter_by(conversation_id=conversation)
                            .order_by(ConversationMessage.message_index, ConversationMessage.message_id)
                            .all()
                        )
                        snapshot = [
                            (m.message_id, m.message_index, m.message_role, m.status, m.message_content)
                            for m in messages
                        ]
                    if len(snapshot) == (index + 1) * 2 and snapshot[-1][3] == "completed":
                        break
                    time.sleep(0.1)
                assert len(snapshot) == (index + 1) * 2 and snapshot[-1][3] == "completed"
                assert [m[1] for m in snapshot] == list(range(len(snapshot))), "Message order regressed"
                assert expected in snapshot[-1][4]
                with get_db_session() as session:
                    persisted_terminal = session.query(ConversationMessageUnit).filter_by(
                        message_id=snapshot[-1][0], unit_type="run_terminal"
                    ).all()
                    root_terminal = [unit for unit in persisted_terminal if not unit.invocation_id]
                    assert len(root_terminal) == 1
                    assert json.loads(root_terminal[0].unit_content)["status"] == "completed"
                if saved:
                    assert snapshot[: len(saved)] == saved, "Earlier messages changed"
                saved = snapshot
                counts.append(len(calls))
            loaded = client.get(f"/conversation/{conversation}")
            assert loaded.status_code == 200 and expected in loaded.text, "Reload lost image facts"
        finally:
            if conversation:
                assert client.delete(f"/conversation/{conversation}").status_code == 200, "Cleanup failed"
    print(
        "IMAGE_RESULT="
        + json.dumps(
            {"completed": True, "tool_counts": counts, "messages": 4, "followup_no_replay": True, "cleanup": True}
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        line = next(
            (frame.lineno for frame in reversed(traceback.extract_tb(error.__traceback__))
             if frame.filename == __file__),
            None,
        )
        print("IMAGE_FAILURE=" + json.dumps({"type": type(error).__name__, "line": line}), flush=True)
        raise SystemExit(1)
