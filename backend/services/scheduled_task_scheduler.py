"""Global scheduler singleton that periodically polls for due scheduled tasks and executes them."""

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger("scheduled_task_scheduler")


def _save_simple_message(conversation_id, msg_idx, role, content, user_id, tenant_id):
    """Save a single text message to the conversation."""
    from services.conversation_management_service import save_message
    from consts.model import MessageRequest, MessageUnit
    save_message(
        MessageRequest(
            conversation_id=conversation_id,
            message_idx=msg_idx,
            role=role,
            message=[MessageUnit(type="string", content=content)],
            minio_files=None,
        ),
        user_id=user_id,
        tenant_id=tenant_id,
    )


def _run_scheduled_task_from_db(task_dict: dict):
    """Execute a due scheduled task synchronously in a background thread.

    The function:
      1. Gets the max message index to avoid collisions.
      2. Saves a user message containing the task prompt with scheduling context.
      3. Creates an AgentRunInfo via create_agent_run_info.
      4. Removes ScheduledTaskTool from the agent's tools to prevent recursive scheduling.
      5. Runs the agent and saves the assistant response.
    """
    task_uuid = task_dict.get("task_uuid", "unknown")
    task_prompt = task_dict.get("task_prompt", "")
    agent_id = task_dict.get("agent_id")
    conversation_id = task_dict.get("conversation_id")
    tenant_id = task_dict.get("tenant_id")
    user_id = task_dict.get("user_id")

    if not all([agent_id, tenant_id, user_id, conversation_id]):
        logger.error(f"Task {task_uuid} is missing required fields, skipping execution")
        return

    try:
        asyncio.run(_execute_task(
            task_uuid=task_uuid, task_prompt=task_prompt, agent_id=agent_id,
            conversation_id=conversation_id, tenant_id=tenant_id, user_id=user_id,
        ))
        logger.info(f"Scheduled task {task_uuid} executed successfully")
    except Exception as e:
        # Intentionally broad: this runs in a worker thread and must not
        # propagate (which would crash the worker). exc_info keeps the cause.
        logger.error(f"Failed to execute scheduled task {task_uuid}: {e}", exc_info=True)


async def _execute_task(task_uuid, task_prompt, agent_id, conversation_id, tenant_id, user_id):
    """Run the full scheduled-task lifecycle within a single event loop.

    Combines message persistence, agent run info creation, tool filtering,
    and the agent run so that no event loop is created/destroyed more than
    once per task execution.
    """
    from database.conversation_db import get_max_message_index
    from agents.create_agent_info import create_agent_run_info
    from nexent.core.agents.run_agent import agent_run
    from consts.const import MESSAGE_ROLE

    # Get current max message index to avoid collisions
    max_idx = get_max_message_index(conversation_id)

    # The message shown to the user is a short, human-readable trigger line.
    # The full instruction is passed only to the agent as the run query, so
    # the internal prompt is never displayed in the chat bubble.
    display_content = f"⏰ {task_prompt}"
    agent_query = (
        f"[定时任务触发] 一个定时任务到期了。请理解下面任务内容的意图，"
        f"直接向用户输出对应的回复，不要复述任务原文，"
        f"不要提问、不要追问、不要建议其他任务、不要调用任何工具。\n\n"
        f"任务内容：{task_prompt}"
    )
    _save_simple_message(
        conversation_id, max_idx + 1, MESSAGE_ROLE["USER"],
        display_content, user_id, tenant_id,
    )

    # Create agent run info
    agent_run_info = await create_agent_run_info(
        agent_id=agent_id,
        minio_files=None,
        query=agent_query,
        history=[],
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )

    # Remove ScheduledTaskTool from agent_config.tools to prevent recursive scheduling
    if hasattr(agent_run_info, "agent_config") and hasattr(agent_run_info.agent_config, "tools"):
        agent_run_info.agent_config.tools = [
            t for t in agent_run_info.agent_config.tools
            if t.class_name != "ScheduledTaskTool"
        ]

    # Run agent and collect response chunks (each chunk is a JSON string)
    chunks = []
    async for chunk in agent_run(agent_run_info):
        chunks.append(chunk)

    # Parse and merge chunks into message units (same logic as
    # save_conversation_assistant) so the frontend renders them correctly —
    # thinking folded, final_answer shown as the answer — instead of dumping
    # raw JSON. Only a final_answer / model_output units are kept; metadata
    # chunks (step_count, token_count, agent_new_run) are dropped.
    _save_assistant_chunks(conversation_id, max_idx + 2, chunks, user_id, tenant_id)


def _save_assistant_chunks(conversation_id, msg_idx, chunks, user_id, tenant_id):
    """Persist an assistant message from agent_run chunks.

    Chunks are JSON strings like '{"type": "final_answer", "content": "..."}'.
    They are parsed and merged (consecutive same-type units concatenated),
    mirroring save_conversation_assistant so the frontend can render each
    unit by type.
    """
    import json as _json
    from services.conversation_management_service import save_message
    from consts.model import MessageRequest, MessageUnit
    from consts.const import MESSAGE_ROLE
    from nexent.core.utils.observer import ProcessType

    mergeable = {ProcessType.MODEL_OUTPUT_CODE.value, ProcessType.MODEL_OUTPUT_THINKING.value}
    message_list = []
    for item in chunks:
        try:
            message = _json.loads(item) if isinstance(item, str) else dict(item)
        except (ValueError, TypeError):
            continue
        mtype = message.get("type")
        content = message.get("content", "")
        # Skip non-content metadata chunks
        if mtype in ("step_count", "token_count", "agent_new_run", "parsing", "execution", "executing"):
            continue
        if not content:
            continue
        if mtype in mergeable and message_list and message_list[-1]["type"] == mtype:
            message_list[-1]["content"] += content
        else:
            message_list.append({"type": mtype, "content": content})

    # Fallback: if no content units were produced, store a plain placeholder
    if not message_list:
        message_list = [{"type": "string", "content": "(task completed with no output)"}]

    save_message(
        MessageRequest(
            conversation_id=conversation_id,
            message_idx=msg_idx,
            role=MESSAGE_ROLE["ASSISTANT"],
            message=[MessageUnit(**m) for m in message_list],
            minio_files=None,
        ),
        user_id=user_id,
        tenant_id=tenant_id,
    )


def _run_and_reschedule(task_dict: dict):
    """Execute a task then update its fire count / next-fire time.

    Intended to run inside a worker thread of the scheduler's pool, so each
    task executes concurrently instead of blocking the polling loop.
    """
    from database.scheduled_task_db import update_task_status, reschedule_if_active

    task_uuid = task_dict.get("task_uuid")
    try:
        _run_scheduled_task_from_db(task_dict)

        new_fire_count = (task_dict.get("fire_count") or 0) + 1
        task_type = task_dict.get("task_type")
        cron_expr = task_dict.get("cron_expression")
        max_fires = task_dict.get("max_fires")

        if task_type == "cron" and cron_expr:
            if max_fires is not None and new_fire_count >= max_fires:
                update_task_status(task_uuid, {"status": "completed", "fire_count": new_fire_count})
            else:
                from nexent.core.tools.scheduled_task_tool import ScheduledTaskTool
                cron_parts = ScheduledTaskTool._parse_cron(cron_expr)
                if cron_parts:
                    next_fire = ScheduledTaskTool._compute_next_fire(
                        cron_parts, datetime.now(timezone.utc)
                    )
                    # Re-arm only if the task was not cancelled mid-run.
                    re_armed = reschedule_if_active(
                        task_uuid, new_fire_count, next_fire.replace(tzinfo=None)
                    )
                    if not re_armed:
                        logger.info(
                            "Task %s was cancelled mid-run; not rescheduling",
                            task_uuid,
                        )
                else:
                    update_task_status(task_uuid, {"status": "error"})
        else:
            # oneshot tasks stay as 'fired'; just persist the fire count
            update_task_status(task_uuid, {"fire_count": new_fire_count})
    except Exception as e:
        # Intentionally broad: this runs in a worker thread and a single task
        # failure (DB error, model API error, etc.) must not crash the worker
        # or affect sibling tasks. We log with exc_info so the real cause is
        # never hidden, then mark the task as errored.
        logger.error(f"Failed to process task {task_uuid}: {e}", exc_info=True)
        try:
            update_task_status(task_uuid, {"status": "error"})
        except SQLAlchemyError:
            # Best-effort status update; if the DB is down there is nothing
            # more we can do for this task.
            pass


class ScheduledTaskScheduler:
    """Background scheduler that polls for due tasks and executes them."""

    # Maximum number of tasks executed in parallel per poll cycle.
    _MAX_WORKERS = 8
    # Per-task execution timeout in seconds.
    _TASK_TIMEOUT = 300

    def __init__(self, poll_interval: float = 10.0):
        self._poll_interval = poll_interval
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            logger.warning("ScheduledTaskScheduler is already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        logger.info("ScheduledTaskScheduler started")

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
            self._thread = None
        logger.info("ScheduledTaskScheduler stopped")

    def _scheduler_loop(self):
        while not self._stop_event.is_set():
            try:
                self._process_due_tasks()
            except Exception as e:
                # Intentionally broad: the daemon loop must survive any single
                # cycle failure, otherwise all scheduled tasks stop firing.
                # exc_info preserves the real cause in the logs.
                logger.error(f"Error in scheduler loop: {e}", exc_info=True)
            self._stop_event.wait(timeout=self._poll_interval)

    def _process_due_tasks(self):
        from database.scheduled_task_db import query_pending_tasks_due, update_task_status

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        due_tasks = query_pending_tasks_due(now)
        if not due_tasks:
            return

        # Mark all due tasks as fired first to prevent re-entrancy on the
        # next poll cycle, while execution happens concurrently below.
        for task_dict in due_tasks:
            update_task_status(task_dict.get("task_uuid"), {"status": "fired"})

        # Dispatch tasks in parallel so many due tasks don't queue up
        # behind each other.
        with ThreadPoolExecutor(max_workers=self._MAX_WORKERS) as executor:
            futures = {
                executor.submit(_run_and_reschedule, task_dict): task_dict.get("task_uuid")
                for task_dict in due_tasks
            }
            for future in futures:
                task_uuid = futures[future]
                try:
                    future.result(timeout=self._TASK_TIMEOUT)
                except TimeoutError:
                    logger.error(f"Task {task_uuid} timed out after {self._TASK_TIMEOUT}s")
                    try:
                        update_task_status(task_uuid, {"status": "error"})
                    except SQLAlchemyError:
                        pass
                except Exception as e:
                    # Intentionally broad: a single task's error must not crash
                    # the scheduler worker. exc_info preserves the real cause.
                    logger.error(f"Task {task_uuid} raised an error: {e}", exc_info=True)
                    try:
                        update_task_status(task_uuid, {"status": "error"})
                    except SQLAlchemyError:
                        pass


# Module-level singleton
scheduled_task_scheduler = ScheduledTaskScheduler()
