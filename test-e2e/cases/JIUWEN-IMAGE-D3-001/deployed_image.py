"""Qualify an authorized image through the deployed assistant without altering its configuration."""

import json
import sys
import time

import httpx
from database.client import get_db_session
from database.db_models import AgentInfo, ConversationMessage, ConversationRecord
from utils.auth_utils import generate_session_jwt


def main():
    agent_id, source_id = int(sys.argv[1]), int(sys.argv[2])
    user, expected = sys.argv[3:5]
    with get_db_session() as session:
        source = session.query(ConversationMessage).filter_by(message_id=source_id, message_role="user").one()
        owner = session.query(ConversationRecord).filter_by(conversation_id=source.conversation_id).one()
        assert owner.created_by == user, "Source image ownership mismatch"
        files = json.loads(source.minio_files) if isinstance(source.minio_files, str) else source.minio_files
        assert files and any(f.get("type", "").startswith("image/") for f in files), "Image fixture required"
        assert session.query(AgentInfo).filter_by(agent_id=agent_id, agent_core="jiuwen", delete_flag="N").count()
    headers = {"Authorization": "Bearer " + generate_session_jwt(user, expires_in=1800)}
    conversation = None
    with httpx.Client(base_url="http://127.0.0.1:5014", headers=headers, trust_env=False, timeout=240) as client:
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
                response = client.post(
                    "/agent/run",
                    json={
                        "agent_id": agent_id,
                        "conversation_id": conversation,
                        "query": query,
                        "history": [],
                        "minio_files": files if not index else [],
                    },
                )
                assert response.status_code == 200, "Runtime HTTP failed"
                events = [
                    json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")
                ]
                terminal = [e for e in events if e.get("type") == "run_terminal" and not e.get("invocation_id")]
                assert len(terminal) == 1 and terminal[0]["status"] == "completed", "Root execution failed"
                calls = [e for e in events if e.get("type") == "tool"]
                if not index:
                    image_calls = [e for e in calls if e.get("tool_name") == "analyze_image"]
                    assert len(image_calls) == 1, "Image must actually be analyzed once"
                    results = [
                        e
                        for e in events
                        if e.get("type") == "tool_result" and e.get("local_call_id") == image_calls[0]["local_call_id"]
                    ]
                    assert len(results) == 1 and results[0].get("is_error") is False, "Image tool failed"
                    text = json.dumps(results[0].get("result"), ensure_ascii=False)
                    assert len(text) > 40 and expected in text, "Visual result lacks expected fixture fact"
                else:
                    assert not calls, "Follow-up replayed a tool"
                final = terminal[0].get("final_content") or ""
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
        print("IMAGE_FAILURE=" + type(error).__name__, flush=True)
        raise SystemExit(1)
