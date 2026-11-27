# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run a trajectory through the real Runtime environment in a fresh process."""

import argparse
import asyncio
import json
import logging
import threading

from contracts.conversation import MessageRequest
from infrastructure.rdb.client import db_client
from management.services.conversation.service import save_message
from nexent.core.agents.contracts.config import AgentConfig, ModelConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.cores.smolagents.agent import NexentAgent
from nexent.core.agents.orchestration.entry import agent_run_thread
from nexent.core.agents.sandbox.config import SandboxConfig
from nexent.core.agents.sandbox.execution import SandboxPoolManager
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ManagedThreadSpec, RunCancellationScope, ThreadManager
from nexent.core.utils.observer import MessageObserver
from nexent.monitor import AgentRunMetadata, agent_monitoring_context
from runtime.trajectory import configure_runtime_trajectory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--conversation", required=True, type=int)
    parser.add_argument("--source", required=True, type=int)
    args = parser.parse_args()

    # Exercise the backend's real configuration, authority and DB initialization.
    processor = configure_runtime_trajectory()
    assert processor is not None
    manager = ThreadManager("capture-pg", {
        lane: LanePolicy(lane, 2, 2)
        for lane in ("agent-run", "model-tool-io", "sandbox", "control-io", "background-service")
    })
    manager.start()
    clients = []
    original = NexentAgent.create_model

    def track_model(agent, *positional, **keywords):
        model = original(agent, *positional, **keywords)
        clients.append(model.client)
        return model

    NexentAgent.create_model = track_model
    try:
        processor.start(manager, ManagedThreadSpec("writer", "capture-pg", close_hook=processor.request_stop))
        observer = MessageObserver()
        stop = threading.Event()
        metadata = AgentRunMetadata(
            tenant_id="tenant", user_id="owner", agent_id=7, conversation_id=args.conversation,
            extra_metadata={"trajectory_source_message_id": str(args.source)},
        )
        info = AgentRunInfo(
            query="Controlled PG question", observer=observer, history=[],
            agent_config=AgentConfig(name="root", description="Controlled Agent", tools=[],
                                     model_name="model", max_steps=2),
            model_config_list=[ModelConfig(cite_name="model", model_name="model", url=args.provider,
                                          api_key="synthetic")],
            conversation_id=args.conversation, user_id="owner", stop_event=stop,
            cancellation_scope=RunCancellationScope(stop), thread_manager=manager,
            sandbox_config=SandboxConfig(auto_sync_outputs=False),
        )
        with agent_monitoring_context(metadata):
            task = manager.submit("agent-run", ManagedTaskSpec("capture", "capture-pg"), agent_run_thread, info)
        task.future.result(timeout=25)
        assert info.attempt_outcome == "completed"
        answer = observer.get_final_answer()
        assert answer == "committed-answer"
        message_id = save_message(
            MessageRequest(conversation_id=args.conversation, message_idx=1, role="assistant",
                           message=[{"type": "final_answer", "content": answer}]),
            "owner", "tenant",
        )
        assert processor.force_flush(3000)
    finally:
        NexentAgent.create_model = original
        for client in clients:
            client.close()
            assert client.is_closed
        pool = SandboxPoolManager._instance
        if pool is not None:
            task = manager.submit("control-io", ManagedTaskSpec("sandbox-cleanup", "capture-pg"),
                                  pool.shutdown, logging.getLogger(__name__))
            task.future.result(timeout=5)
        processor.shutdown()
        asyncio.run(manager.shutdown(timeout=3))
        db_client.engine.dispose()
        assert manager.snapshot().active_count == 0
    print(json.dumps({"assistant_message_id": message_id, "active_workers": 0}), flush=True)


if __name__ == "__main__":
    main()
