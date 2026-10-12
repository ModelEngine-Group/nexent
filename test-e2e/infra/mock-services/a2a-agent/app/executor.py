"""Official A2A SDK executor returning deterministic test data."""

from __future__ import annotations

import uuid

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role, Task, TaskState, TaskStatus, TaskStatusUpdateEvent


def response_for(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("alarm", "security", "告警", "安全")):
        return "Security alarms: critical=2, major=4, minor=6, total=12."
    if any(word in lowered for word in ("flow", "pedestrian", "entrance", "人流", "出入口")):
        return "Pedestrian flow in the past 5 minutes: east=456, west=321, south=289, north=217, total=1283."
    return f"Nexent A2A mock received: {text}"


class DeterministicExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = ""
        if context.message:
            for part in context.message.parts or []:
                if part.text:
                    text = part.text
                    break
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or str(uuid.uuid4())
        await event_queue.enqueue_event(
            Task(
                id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED, message=context.message),
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_COMPLETED,
                    message=Message(
                        message_id=str(uuid.uuid4()),
                        role=Role.ROLE_AGENT,
                        parts=[Part(text=response_for(text))],
                        context_id=context_id,
                        task_id=task_id,
                    ),
                ),
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
            )
        )

