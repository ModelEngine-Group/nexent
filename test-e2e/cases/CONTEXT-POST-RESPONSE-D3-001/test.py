# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Post-response context maintenance over the real HTTP/SSE model pipeline."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest
from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime
from smolagents.memory import TaskStep, ActionStep
from smolagents.monitoring import Timing
from nexent.core.agents.context import ContextItemInput, ContextManager, ContextManagerConfig
from nexent.core.models.capacity_budget import CapacityReservePolicy, ContextBudgetCalculator
from nexent.core.models.capacity_resolver import resolve_capacity
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from shared.model_service_profiles import resolved_profile_for_test

pytestmark = [pytest.mark.case_id("CONTEXT-POST-RESPONSE-D3-001"), pytest.mark.stage("D3")]


@pytest.mark.parametrize("old_input,old_reserve", [(2000, 1024), (9000, 512)])
@pytest.mark.parametrize("entrypoint", ["runtime", "agent", "agent_tools"])
def test_usage_calibrates_post_response_maintenance(old_input, old_reserve, entrypoint):
    requests = []
    window = 100000 if entrypoint.startswith("agent") else 10000
    actual_input = window - 1000

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            returned_text = "<final_answer>HELLO</final_answer>" if entrypoint.startswith("agent") else "HELLO"
            if entrypoint == "agent_tools" and len(requests) == 1:
                returned_text = '<code>print("TOOL_OK")</code>'
            request_input = 20000 if entrypoint == "agent_tools" and len(requests) > 1 else actual_input
            chunk = {"id": "context-controlled", "model": "qwen3.5-plus", "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": returned_text}, "finish_reason": "stop"}]}
            usage = {"id": "context-controlled", "choices": [], "usage": {
                "prompt_tokens": request_input, "completion_tokens": 5, "total_tokens": request_input + 5,
                "prompt_tokens_details": {"cached_tokens": 8000}}}
            body = ("data: " + json.dumps(chunk) + "\n\ndata: " + json.dumps(usage)
                    + "\n\ndata: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        data = resolved_profile_for_test(f"http://127.0.0.1:{server.server_port}/v1").model_dump(mode="json")
        data["capabilities"]["context"] = {"combined_window": window, "input_limit": old_input, "output_limit": 2048}
        data["context_configuration"]["output_reserve_tokens"] = old_reserve
        data["parameter_values"]["max_output_tokens"] = 4096
        model = LegacyChatModel.from_profile(ResolvedModelProfile.model_validate(data), "controlled-key")
        capacity = resolve_capacity(model_id="qwen3.5-plus", provider="alibaba", capability_profiles={},
            operator_overrides={"context_window_tokens": window, "max_output_tokens": 2048,
                                "max_input_tokens": old_input, "default_output_reserve_tokens": old_reserve})
        budget = ContextBudgetCalculator().calculate_context_budget(
            capacity_snapshot=capacity, reserve_policy=CapacityReservePolicy())
        assert budget.compaction_trigger_threshold_tokens == window - min(window // 5, 20000)
        assert budget.compaction_target_tokens == window - 2 * min(window // 5, 20000)
        model.context_budget_snapshot = budget
        runtime = ManagedContextRuntime(ContextManager(ContextManagerConfig(
            context_window_tokens=window, effective_input_limit_tokens=window,
            compaction_trigger_threshold_tokens=budget.compaction_trigger_threshold_tokens,
            compaction_target_tokens=budget.compaction_target_tokens,
            policy_layers={"platform": {"processing_mode": "adaptive_compact"}})), items=[
                ContextItemInput(id="kb:large", type="knowledge_base", content={"text": "evidence " * (10000 if entrypoint.startswith("agent") else 1000)})])
        if entrypoint.startswith("agent"):
            from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
            agent = CoreAgent(observer=model.observer, model=model, tools=[], name="context_policy",
                enable_protocol_repair_retry=True, max_steps=2, context_runtime=runtime)
            assert str(agent.run("Respond briefly")) == "HELLO"
            memory = agent.memory
            evidence = runtime.last_maintenance_evidence
            first_size = len(str(requests[0]["messages"]))
            after = runtime.context_manager.assemble_final_context(model=model, memory=memory,
                current_run_start_idx=0, run_context=runtime._run_context)
        else:
            memory = SimpleNamespace(steps=[TaskStep(task="Respond briefly")])
            first = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
            assert not runtime.context_manager._representation_overrides
            first_size = len(str(first.messages))
            response = model.generate(first.messages)
            assert response.content == "HELLO" and response.token_usage.input_tokens == actual_input
            memory.steps.append(ActionStep(step_number=1, model_output="HELLO", model_output_message=response,
                timing=Timing(start_time=0)))
            evidence = runtime.complete_step(model=model, memory=memory, current_run_start_idx=0, response=response)
            after = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
        assert evidence.maintenance_phase == "post_response"
        assert evidence.usage_source == "provider_calibrated" and evidence.provider_input_tokens == actual_input
        assert runtime.context_manager._representation_overrides
        assert runtime.usage_baseline.actual_input_tokens == (20000 if entrypoint == "agent_tools" else None)
        assert len(str(after.messages)) < first_size
        model.generate(after.messages)
        assert len(requests) == (3 if entrypoint == "agent_tools" else 2)
        if entrypoint == "agent_tools":
            assert "TOOL_OK" in str(requests[1]["messages"])
            assert len(str(requests[1]["messages"])) < len(str(requests[0]["messages"]))
        for body in requests:
            assert not {"max_tokens", "max_completion_tokens", "max_output_tokens"}.intersection(body)
        wire_text = "\n".join(
            message["content"] if isinstance(message.get("content"), str)
            else "".join(part.get("text", "") for part in message.get("content", []) if isinstance(part, dict))
            for message in requests[0]["messages"])
        assert memory.steps[0].task.startswith("Respond briefly")
        assert memory.steps[0].task in wire_text
        assert "HELLO" in memory.steps[-1].model_output
        assert runtime.finalize_evidence(status="success").model_call_count == (2 if entrypoint == "agent_tools" else 1 if entrypoint == "agent" else 2)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


@pytest.mark.parametrize("outcome", ["accepted", "invalid_summary", "main_failure"])
def test_rejected_capacity_recovers_transactionally_over_http(outcome):
    requests, committed = [], []
    summary = "# Compact Result of History\n\n" + "\n\n".join(
        "## " + heading + "\n\n" + "The old fact remains available."
        for heading in ["Task Overview", "Completed Work", "Key Decisions", "Unresolved Issues",
                        "Pending Items", "Next Steps", "Context To Preserve"])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(request)
            is_summary = "NEW_CURRENT_TASK" not in str(request["messages"])
            text = (summary if outcome != "invalid_summary" else "unstructured rejected summary") if is_summary else "MAIN_OK"
            if not is_summary and outcome == "main_failure":
                body = json.dumps({"error": {"message": "controlled authentication failure", "type": "authentication_error"}}).encode()
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
            else:
                chunk = {"id": "owned-recovery", "model": "qwen3.5-plus", "choices": [{"index": 0,
                    "delta": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}
                usage = {"id": "owned-recovery", "choices": [], "usage": {
                    "prompt_tokens": 900, "completion_tokens": 100, "total_tokens": 1000}}
                body = ("data: " + json.dumps(chunk) + "\n\ndata: " + json.dumps(usage)
                        + "\n\ndata: [DONE]\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        data = resolved_profile_for_test(f"http://127.0.0.1:{server.server_port}/v1").model_dump(mode="json")
        data["capabilities"]["context"] = {"combined_window": 20000, "input_limit": 1000, "output_limit": 5000}
        model = LegacyChatModel.from_profile(ResolvedModelProfile.model_validate(data), "owned-key")
        original_service = model.service
        runtime = ManagedContextRuntime(ContextManager(ContextManagerConfig(
            context_window_tokens=20000, effective_input_limit_tokens=20000, chars_per_token=1,
            compaction_trigger_threshold_tokens=16000, compaction_target_tokens=12000,
            history_summary_sink=committed.append,
            policy_layers={"platform": {"processing_mode": "adaptive_compact"}})), items=[
                ContextItemInput(id="old", type="conversation_turn", content={"user_message": "h" * 14000,
                    "assistant_final_answer": "old fact", "user_message_id": 1, "assistant_message_id": 2})])
        memory = SimpleNamespace(steps=[TaskStep(task="NEW_CURRENT_TASK" + "n" * 8000)])
        runtime.prepare_run(memory=memory, fallback_system_prompt="MANDATORY_SYSTEM")
        if outcome == "invalid_summary":
            with pytest.raises(ValueError, match="combined context window"):
                runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
            first_calls = len(requests)
            with pytest.raises(ValueError):
                runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
            assert len(requests) == first_calls and not committed
            assert runtime.context_manager._history_candidate is None
            assert runtime.context_manager._pending_capacity_candidate is None
        else:
            prepared = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
            assert prepared.evidence.maintenance_phase == "local_capacity_recovery"
            assert prepared.evidence.provider_input_tokens is None
            assert runtime._estimate(prepared.messages, prepared.tools) < 20000
            assert len(committed) == 1 and committed[0].covered_through_message_id == 2
            if outcome == "main_failure":
                from nexent.core.model_errors import ModelInvocationTerminalError
                with pytest.raises(ModelInvocationTerminalError):
                    model.generate(prepared.messages)
            else:
                assert model.generate(prepared.messages).content == "MAIN_OK"
            assert runtime.context_manager._history_candidate is committed[0]
            assert runtime.usage_baseline.actual_input_tokens is None
            assert "NEW_CURRENT_TASK" in str(requests[-1]["messages"])
            assert "MANDATORY_SYSTEM" in str(requests[-1]["messages"])
        assert 1 <= runtime._capacity_budget.summary_calls <= 3
        assert model.service is original_service
        assert all(not {"max_tokens", "max_completion_tokens", "max_output_tokens"}.intersection(body) for body in requests)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


@pytest.mark.parametrize(
    "source_kind", ["user_message", "tool_result", "execution_result"]
)
def test_source_backed_bulk_and_checkpoint_restore_over_http(source_kind):
    from contracts.agentos import PreparedHistoryCheckpoint
    from nexent.core.agents.context import ContextItem
    from nexent.core.agents.context.action_history import register_authorized_sources
    from nexent.core.agents.context.execution_history import (
        ExecutionHistory,
        result_text,
    )

    bodies = []
    summary = "# Compact Result of History\n\n" + "\n\n".join(
        "## "
        + heading
        + "\n\ncritical-business-001 = Keep-123. The old task remains recoverable."
        for heading in [
            "Task Overview",
            "Completed Work",
            "Key Decisions",
            "Unresolved Issues",
            "Pending Items",
            "Next Steps",
            "Context To Preserve",
        ]
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            bodies.append(request)
            content = "MAIN_OK" if "NEW_TASK" in str(request["messages"]) else summary
            chunk = {
                "id": "owned-source",
                "model": "qwen3.5-plus",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            }
            usage = {
                "id": "owned-source",
                "choices": [],
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 100,
                    "total_tokens": 1100,
                },
            }
            payload = (
                "data: "
                + json.dumps(chunk)
                + "\n\ndata: "
                + json.dumps(usage)
                + "\n\ndata: [DONE]\n\n"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        data = resolved_profile_for_test(
            f"http://127.0.0.1:{server.server_port}/v1"
        ).model_dump(mode="json")
        data["capabilities"]["context"] = {
            "combined_window": 20000,
            "input_limit": 1000,
            "output_limit": 5000,
        }
        model = LegacyChatModel.from_profile(
            ResolvedModelProfile.model_validate(data), "owned-key"
        )
        raw = json.dumps(
            {
                "rows": [
                    {
                        "record": f"business-record-{i:05d}",
                        "amount": 100000 + i,
                        "credit": 100 + i,
                        "detail": "original value " * 30,
                    }
                    for i in range(60)
                ]
            },
            separators=(",", ":"),
        )
        user = "OLD_TASK. Explicit critical-business-001 = Keep-123." + (
            ("\n" + raw) if source_kind == "user_message" else ""
        )
        turn = {
            "user_message": user,
            "assistant_final_answer": "Old accepted work.",
            "user_message_id": 1,
            "assistant_message_id": 2,
            "execution_records": [],
        }
        sources = [
            {
                "record_type": "user_message",
                "message_id": 1,
                "unit_index": None,
                "content": user,
            }
        ]
        reference = "message:1/user-message"
        readable = user
        if source_kind == "tool_result":
            common = {
                "schema_version": 1,
                "runtime_mode": "native_agent",
                "agent_core": "jiuwen",
                "local_call_id": "native-local",
                "tool_call_id": "native-local",
                "provider_call_id": "native-provider",
                "turn_id": "native-turn",
                "invocation_id": None,
                "parent_call_id": None,
            }
            call = {
                **common,
                "type": "tool",
                "call_group_id": "native-group",
                "call_index": 0,
                "call_count": 1,
                "tool_name": "lookup",
                "tool_arguments": {},
                "raw_arguments": "{}",
                "source_protocol": "model_native_fc",
            }
            result = {**common, "type": "tool_result", "result": raw, "is_error": False}
            turn["execution_records"] = [
                {
                    "record_type": "tool",
                    "unit_index": 1,
                    "tool_call_id": "native-local",
                    "content": json.dumps(call),
                },
                {
                    "record_type": "tool_result",
                    "unit_index": 2,
                    "tool_call_id": "native-local",
                    "content": json.dumps(result),
                },
            ]
            sources.append({**turn["execution_records"][1], "message_id": 2})
            reference = "message:2/unit-index:2"
            readable = raw
        elif source_kind == "execution_result":
            body = {
                "content": result_text({"STDOUT": raw, "ERROR": "\x1b[31mTool observation: failed to resolve input\x1b[0m"}),
                "covered_unit_indices": [],
                "model_action": {
                    "schema_version": 1,
                    "agent_core": "smolagents",
                    "dispatch_state": "dispatched",
                    "step_number": 1,
                    "tool_calls": [
                        {
                            "id": "code-call",
                            "name": "python_interpreter",
                            "arguments": "load_rows()",
                        }
                    ],
                },
            }
            turn["execution_records"] = [
                {
                    "record_type": "execution_result",
                    "unit_index": 2,
                    "content": json.dumps(body),
                }
            ]
            sources.append({**turn["execution_records"][0], "message_id": 2})
            reference = "message:2/unit-index:2"
            readable = body["content"]
        history = ExecutionHistory()
        items = register_authorized_sources(
            [
                ContextItem.from_input(
                    ContextItemInput(id="old", type="conversation_turn", content=turn)
                )
            ],
            history,
            "old-owner",
        )

        def runtime(store, owner, items):
            return ManagedContextRuntime(
                ContextManager(
                    ContextManagerConfig(
                        context_window_tokens=20000,
                        effective_input_limit_tokens=20000,
                        chars_per_token=1,
                        compaction_trigger_threshold_tokens=16000,
                        compaction_target_tokens=12000,
                        execution_history=store,
                        execution_owner=owner,
                        policy_layers={
                            "platform": {"processing_mode": "adaptive_compact"}
                        },
                    )
                ),
                items,
            )

        managed = runtime(history, "old-owner", items)
        memory = SimpleNamespace(steps=[TaskStep(task="NEW_TASK")])
        managed.prepare_run(
            memory=memory, fallback_system_prompt="Mandatory instructions"
        )
        recovered = managed.prepare_step(
            model=model, memory=memory, current_run_start_idx=0
        )
        assert recovered.evidence.maintenance_phase == "local_capacity_recovery"
        assert managed._estimate(recovered.messages, recovered.tools) < 20000
        assert "business-record-00059" not in str(
            recovered.messages
        ) and reference in str(recovered.messages)
        assert "critical-business-001" in str(recovered.messages) and "Keep-123" in str(
            recovered.messages
        )
        assert model.generate(recovered.messages).content == "MAIN_OK"
        candidate = managed.context_manager._history_candidate
        checkpoint = PreparedHistoryCheckpoint.model_validate(
            {"unit_id": 99, **candidate.as_item().content, "execution_sources": sources}
        )
        checkpoint_item = ContextItem.from_input(
            ContextItemInput(
                id="checkpoint",
                type="history_summary",
                content=checkpoint.model_dump(mode="json"),
            )
        )
        next_history = ExecutionHistory()
        restored = register_authorized_sources(
            [checkpoint_item], next_history, "new-owner"
        )
        offset = readable.index("business-record-00030")
        assert (
            json.loads(next_history.read("new-owner", reference, offset, 100))["text"]
            == readable[offset : offset + 100]
        )
        if source_kind == "execution_result":
            error_offset = readable.index("\x1b")
            assert json.loads(next_history.read("new-owner", reference, error_offset, 100))["text"] == readable[error_offset:error_offset + 100]
        with pytest.raises(PermissionError):
            next_history.read("old-owner", reference)
        continued = runtime(next_history, "new-owner", restored)
        next_memory = SimpleNamespace(
            steps=[TaskStep(task="NEW_TASK_AFTER_CHECKPOINT")]
        )
        continued.prepare_run(
            memory=next_memory, fallback_system_prompt="Mandatory instructions"
        )
        before = len(bodies)
        final = continued.prepare_step(
            model=model, memory=next_memory, current_run_start_idx=0
        )
        assert len(bodies) == before and final.evidence.maintenance_phase == "prepare"
        assert model.generate(final.messages).content == "MAIN_OK"
        assert all(
            not {
                "max_tokens",
                "max_completion_tokens",
                "max_output_tokens",
            }.intersection(body)
            for body in bodies
        )
        assert len(bodies) == 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()
