"""Isolated PostgreSQL and real Core/model transport proof for saved CM and history."""

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import httpx
import time
import uuid
from contextlib import contextmanager, nullcontext
from threading import Event
from unittest.mock import Mock

from jiuwen_bridge_fixture import profile_for
from nexent.core.agents.agent_model import (
    AgentConfig,
    AgentRunInfo,
    ModelConfig,
    ToolConfig,
)
from nexent.core.agents.context import ContextManagerConfig
from nexent.core.agents.run_agent import agent_run
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.core.utils.observer import MessageObserver
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.orm import sessionmaker

if sys.platform == "win32":
    for folder in ("pywin32_system32", "win32", "win32/lib"):
        sys.path.append(str(Path(httpx.__file__).resolve().parents[1] / folder))


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=40, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise AssertionError("Isolated context PostgreSQL command failed")
    return result.stdout.strip()


@contextmanager
def context_database(monkeypatch):
    name = "codex-jiuwen-context-" + uuid.uuid4().hex[:10]
    docker("run", "-d", "--name", name, "-p", "127.0.0.1::5432",
           "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:15-alpine")
    engine = None
    try:
        port = int(docker("port", name, "5432/tcp").rsplit(":", 1)[1])
        for _ in range(150):
            ready = subprocess.run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"],
                capture_output=True, timeout=5, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if ready.returncode == 0:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("Isolated history PostgreSQL did not start")
        engine = create_engine(f"postgresql://postgres@127.0.0.1:{port}/postgres")
        from database import client, conversation_db
        from database.db_models import (
            AgentInfo,
            ConversationMessage,
            ConversationMessageUnit,
            ConversationRecord,
            ConversationSourceSearch,
            ConversationSourceImage,
        )

        monkeypatch.setattr(client.db_client, "session_maker", sessionmaker(bind=engine))
        # Authentication lookup is the controlled external boundary, not the history DAL.
        monkeypatch.setattr(conversation_db, "_get_user_tenant", lambda _: {"tenant_id": "spike-tenant"})
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA nexent"))
        for model in (AgentInfo, ConversationRecord, ConversationMessage, ConversationMessageUnit,
                      ConversationSourceSearch, ConversationSourceImage):
            model.__table__.create(engine)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        docker("rm", "-f", name)


def seed_agent(engine, core):
    from database.db_models import AgentInfo
    with engine.begin() as connection:
        for version in (0, 1):
            connection.execute(insert(AgentInfo).values(agent_id=42, version_no=version, agent_core=core,
                name="history_agent", description="History fixture", tenant_id="spike-tenant",
                current_version_no=1, enable_context_manager=False, created_by="owner", delete_flag="N"))


def save_configuration(engine, core, cm):
    from database.agent_db import (
        search_agent_info_by_agent_id,
        update_agent_draft_fields,
    )
    from database.db_models import AgentInfo
    assert update_agent_draft_fields(42, "spike-tenant", {"agent_core": core, "enable_context_manager": cm}) == 1
    assert search_agent_info_by_agent_id(42, "spike-tenant", 1)["agent_core"] != core
    # Publishing is an existing external boundary: prepare its immutable new snapshot,
    # rather than mutating the old version or testing an unrelated publication workflow.
    with engine.begin() as connection:
        connection.execute(insert(AgentInfo).values(agent_id=42, version_no=2, agent_core=core,
            name="history_agent", description="History fixture", tenant_id="spike-tenant",
            enable_context_manager=cm, created_by="owner", delete_flag="N"))
    assert update_agent_draft_fields(42, "spike-tenant", {"current_version_no": 2}) == 1


def message(conversation, index, role, content, files=None, status="completed"):
    from database.conversation_db import create_conversation_message
    return create_conversation_message({"conversation_id": conversation, "message_idx": index,
        "role": role, "content": content, "minio_files": files}, "owner", status=status)


def record_output(conversation, index, output):
    from database.conversation_db import create_message_units
    from utils.agent_stream_utils import serialize_stream_unit_content
    answer = "".join(event.get("content", "") for event in output if event.get("type") == "final_answer")
    mid = message(conversation, index, "assistant", answer)
    units = []
    for event in output:
        if event.get("type") == "history_summary":
            continue
        content = event.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content)
        units.append({"type": event["type"], "content": serialize_stream_unit_content(event, content),
            "unit_index": len(units), "unit_type": event["type"],
            "unit_content": serialize_stream_unit_content(event, content), "unit_status": "completed",
            "tool_call_id": event.get("tool_call_id"), "invocation_id": event.get("invocation_id")})
    from database.conversation_db import update_message_unit_status
    for unit_id in create_message_units(units, mid, conversation, "owner"):
        update_message_unit_status(unit_id, "completed", user_id="owner")
    return mid


async def run_context_scenario(monkeypatch, engine, original="smolagents", protocol="native", cm=False,
                               fault=None, existing_checkpoint=False):
    from database.agent_db import search_agent_info_by_agent_id
    from database.agent_version_db import query_current_version_no
    from database.conversation_db import (
        create_conversation,
        get_conversation_history,
        get_historical_context,
    )
    from database.db_models import ConversationMessageUnit
    from nexent.core.agents import nexent_agent
    from services.conversation_management_service import (
        persist_history_summary_candidate,
    )
    from smolagents import Tool

    changed = "jiuwen" if original == "smolagents" else "smolagents"
    seed_agent(engine, original)
    conversation = create_conversation("Existing Core conversation", "owner", agent_id=42)["conversation_id"]
    effects, calls, summary_requests, read_errors = [], [], [], []
    phase = {"value": "seed", "stage_calls": 0, "summary_started": False, "closed": False}
    summary_schema = ContextManagerConfig().summary_json_schema
    markdown = "# Compact Result of History\n" + "\n".join(
        "## " + key.replace("_", " ").title() + "\nOLD_FACT_ALPHA s3://files/old.txt TOOL_RESULT_ALPHA"
        for key in summary_schema)

    async def handle(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = int(next(line.split(b":", 1)[1] for line in headers.split(b"\r\n")
                              if line.lower().startswith(b"content-length:")))
            body = json.loads(await reader.readexactly(length))
            is_summary = any("exact seven" in str(m.get("content")) or "Produce a structured summary" in
                             str(m.get("content")) or "Update the summary keeping" in str(m.get("content"))
                             for m in body["messages"])
            if is_summary:
                summary_requests.append(body)
                phase["summary_started"] = True
                if fault == "cancel_summary":
                    await reader.read()
                    phase["closed"] = True
                    return
                source = str(body["messages"])
                markers = sorted(set(re.findall(r"\b(?=[A-Za-z0-9-]*\d)[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+){2,}\b", source)))
                content, tool_calls = ("Invalid summary" if fault == "invalid_summary" else
                                       markdown + "\nPreserved identifiers: " + " ".join(markers)), []
            else:
                calls.append((phase["value"], body))
                phase["stage_calls"] += 1
                core = original if phase["value"] == "seed" else changed
                first = phase["value"] == "seed" and phase["stage_calls"] == 1
                if first and core == "jiuwen" and protocol == "native":
                    content = ""
                    tool_calls = [{"id": "saved-provider-call", "type": "function", "function": {
                        "name": "remember", "arguments": "{}"}}]
                elif first:
                    content, tool_calls = "<code>\nprint(remember())\n</code>", []
                else:
                    content, tool_calls = ("OLD_FACT_ALPHA" if phase["value"] == "seed" else "FOLLOWUP_ALPHA"), []
                    if core == "smolagents":
                        content = "<final_answer>" + content + "</final_answer>"
            value = {"id": "context-response", "model": body["model"], "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content,
                    **({"tool_calls": tool_calls} if tool_calls else {})},
                    "finish_reason": "tool_calls" if tool_calls else "stop"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}}
            if body.get("stream"):
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n")
                delta = value["choices"][0]["message"]
                if tool_calls:
                    delta["tool_calls"] = [{"index": i, **call} for i, call in enumerate(tool_calls)]
                chunk = {**value, "object": "chat.completion.chunk", "choices": [
                    {"index": 0, "delta": delta, "finish_reason": None}]}
                chunk.pop("usage", None)
                writer.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                chunk["choices"] = [{"index": 0, "delta": {}, "finish_reason": value["choices"][0]["finish_reason"]}]
                chunk["usage"] = value["usage"]
                writer.write(("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode())
            else:
                encoded = json.dumps(value).encode()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                             + str(len(encoded)).encode() + b"\r\nConnection: close\r\n\r\n" + encoded)
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception as error:  # noqa: BLE001 - Collect fixture failures for terminal assertions.
            read_errors.append(type(error).__name__)
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    class RememberTool(Tool):
        name, description, inputs, output_type = "remember", "Remember a historical fact", {}, "string"
        def forward(self):
            effects.append("once")
            return "TOOL_RESULT_ALPHA"
    monkeypatch.setattr(nexent_agent, "RememberTool", RememberTool, raising=False)
    monitoring = Mock()
    monitoring.trace_llm_request.side_effect = lambda *a, **k: nullcontext(None)
    monkeypatch.setattr("nexent.core.model_service.service.get_monitoring_manager", lambda: monitoring)
    def forbidden(*a, **k):
        raise AssertionError("Jiuwen native provider client must not send")
    monkeypatch.setattr("openjiuwen.core.foundation.llm.model.create_model_client", forbidden)
    profile = profile_for(url, protocol)
    manager = ThreadManager("context-runtime", {name: LanePolicy(name=name, max_workers=2, max_queue_size=8)
        for name in ("agent-run", "model-tool-io", "mcp-session", "control-io", "sandbox", "background-service")})
    manager.start()
    infos, outputs = [], []
    async def info_for(query, current_mid):
        version = query_current_version_no(42, "spike-tenant")
        saved = search_agent_info_by_agent_id(42, "spike-tenant", version)
        from agents.create_agent_info import build_agent_context_policy
        cm_config = ContextManagerConfig(effective_input_limit_tokens=200000,
            compaction_trigger_threshold_tokens=35000, compaction_target_tokens=30000,
            max_summary_input_tokens=120000,
            max_summary_reduce_tokens=1000, policy_layers=build_agent_context_policy(saved["enable_context_manager"]))
        cm_config.history_summary_sink = lambda candidate: persist_history_summary_candidate(
            conversation, candidate, "owner", "spike-tenant")
        info = AgentRunInfo(query=query, stop_event=Event(), observer=MessageObserver(lang="en"),
            thread_manager=manager, tenant_id="spike-tenant", user_id="owner", conversation_id=conversation,
            model_config_list=[ModelConfig(cite_name="fixture", model_name=profile.identity.request_model_id,
                url=profile.connection.base_url, api_key="fixture-only", resolved_profile=profile)],
            agent_config=AgentConfig(name="history_agent", description="History fixture", agent_core=saved["agent_core"],
                version_no=version, model_name="fixture", max_steps=3, context_manager_config=cm_config,
                tools=[ToolConfig(name="remember", class_name="RememberTool", source="local", params={})]))
        from consts.model import AgentRequest, HistoryItem
        from management.services.agent import run as application
        from unittest.mock import AsyncMock

        monkeypatch.setattr(application, "create_agent_run_info", AsyncMock(return_value=info))
        monkeypatch.setattr(application, "build_memory_context", lambda *a, **k: None)
        monkeypatch.setattr(application.agent_run_manager, "register_agent_run", lambda *a, **k: None)
        request = AgentRequest(agent_id=42, conversation_id=conversation, query=query, is_debug=False,
            history=[HistoryItem(role="user", content="UNTRUSTED_CLIENT_HISTORY")])
        info, _ = await application.prepare_agent_run(request, "owner", "spike-tenant", language="en")
        infos.append(info)
        return info
    try:
        async with server:
            first = message(conversation, 1, "user", "Perform the original task", files=[{
                "name": "old.txt", "url": "s3://files/old.txt"}])
            info = await info_for("Perform the original task", first)
            output = [json.loads(chunk) async for chunk in agent_run(info, thread_manager=manager)]
            assert info.attempt_outcome == "completed", output[-2:]
            old_assistant = record_output(conversation, 2, output)
            if existing_checkpoint or fault is not None:
                persist_history_summary_candidate(conversation, {"summary": {"markdown": markdown},
                    "covered_through_message_id": old_assistant}, "owner", "spike-tenant")
            outputs.append(output)
            for index in range(3, 19, 2):
                message(conversation, index, "user", "Completed earlier request " + "old data " * 500)
                message(conversation, index + 1, "assistant", "Completed earlier answer " + "old data " * 500)
            save_configuration(engine, changed, cm)
            before = get_conversation_history(conversation, "owner")
            phase.update(value="followup", stage_calls=0)
            current_mid = message(conversation, 19, "user", "Recall the completed fact; do not repeat tools")
            info = await info_for("CURRENT_FOLLOWUP_ONLY", current_mid)
            async def cancel_summary():
                for _ in range(1000):
                    if phase["summary_started"]:
                        phase["cancel_started"] = time.monotonic()
                        info.stop_event.set()
                        return
                    await asyncio.sleep(0.01)
                raise AssertionError("Summary did not start")
            canceller = asyncio.create_task(cancel_summary()) if fault == "cancel_summary" else None
            try:
                output = [json.loads(chunk) async for chunk in agent_run(info, thread_manager=manager)]
            finally:
                if canceller:
                    await canceller
            outputs.append(output)
            cancelled = fault == "cancel_summary"
            if cancelled:
                phase["cancel_elapsed"] = time.monotonic() - phase["cancel_started"]
            if not cancelled:
                assert info.attempt_outcome == "completed", output[-2:]
                record_output(conversation, 20, output)
            else:
                assert info.attempt_outcome == "stopped"
                message(conversation, 20, "assistant", "Stopped before final response", status="stopped")
            with engine.connect() as connection:
                checkpoints_before_recovery = connection.execute(select(ConversationMessageUnit.unit_content).where(
                    ConversationMessageUnit.unit_type == "history_summary")).scalars().all()
            fault = None
            phase.update(value="reload", stage_calls=0)
            current_mid = message(conversation, 21, "user", "Continue after reloading")
            reloaded = await info_for("RELOADED_CURRENT_ONLY", current_mid)
            result = [json.loads(chunk) async for chunk in agent_run(reloaded, thread_manager=manager)]
            assert reloaded.attempt_outcome == "completed", result[-2:]
            outputs.append(result)
            after = get_conversation_history(conversation, "owner")
            for old_message in before["message_records"]:
                reloaded_message = next(message for message in after["message_records"]
                                        if message["message_id"] == old_message["message_id"])
                for field in ("message_content", "status", "minio_files", "role", "message_index"):
                    assert reloaded_message[field] == old_message[field]
                for old_unit in old_message["units"]:
                    assert old_unit in reloaded_message["units"]
            with engine.connect() as connection:
                checkpoints = connection.execute(select(ConversationMessageUnit.unit_content).where(
                    ConversationMessageUnit.unit_type == "history_summary")).scalars().all()
            assert get_historical_context(conversation, current_mid, "other-owner", "spike-tenant") is None
            assert get_historical_context(conversation, current_mid, "owner", "other-tenant") is None
            assert get_historical_context(conversation, 999999, "owner", "spike-tenant") is None
            assert not read_errors
            return {"infos": infos, "calls": calls, "summaries": summary_requests, "checkpoints": checkpoints,
                    "checkpoints_before_recovery": checkpoints_before_recovery,
                    "effects": effects, "before": before, "after": after, "outputs": outputs, "phase": phase}
    finally:
        drained = await manager.shutdown(timeout=5)
        assert not drained.stuck_execution_ids and manager.snapshot().active_count == 0
