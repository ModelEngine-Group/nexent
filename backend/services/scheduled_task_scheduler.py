"""Global scheduler singleton that periodically polls for due scheduled tasks and executes them."""

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timezone

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

    # Save user message with scheduling instruction
    user_content = (
        f"[定时任务触发] 以下是一条已到期的定时任务，请直接执行任务内容并回复用户。"
        f"不要创建新的定时任务，不要调用 scheduled_task 工具。\n\n任务内容：{task_prompt}"
    )
    _save_simple_message(
        conversation_id, max_idx + 1, MESSAGE_ROLE["USER"],
        user_content, user_id, tenant_id,
    )

    # Create agent run info
    agent_run_info = await create_agent_run_info(
        agent_id=agent_id,
        minio_files=None,
        query=user_content,
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

    # Run agent and collect response chunks
    chunks = []
    async for chunk in agent_run(agent_run_info):
        chunks.append(chunk)

    # Build assistant response text from chunks
    response_parts = [
        c.get("content", "") if isinstance(c, dict) else str(c)
        for c in chunks
    ]
    assistant_content = "".join(p for p in response_parts if p) or "(task completed with no output)"

    # Save assistant message
    _save_simple_message(
        conversation_id, max_idx + 2, MESSAGE_ROLE["ASSISTANT"],
        assistant_content, user_id, tenant_id,
    )


def _run_and_reschedule(task_dict: dict):
    """Execute a task then update its fire count / next-fire time.

    Intended to run inside a worker thread of the scheduler's pool, so each
    task executes concurrently instead of blocking the polling loop.
    """
    from database.scheduled_task_db import update_task_status

    task_uuid = task_dict.get("task_uuid")
    try:
        _run_scheduled_task_from_db(task_dict)

        # Update fire count and schedule next run for cron tasks
        updates = {"fire_count": (task_dict.get("fire_count") or 0) + 1}
        task_type = task_dict.get("task_type")
        cron_expr = task_dict.get("cron_expression")
        max_fires = task_dict.get("max_fires")

        if task_type == "cron" and cron_expr:
            if max_fires is not None and updates["fire_count"] >= max_fires:
                updates["status"] = "completed"
            else:
                from nexent.core.tools.scheduled_task_tool import ScheduledTaskTool
                cron_parts = ScheduledTaskTool._parse_cron(cron_expr)
                if cron_parts:
                    next_fire = ScheduledTaskTool._compute_next_fire(
                        cron_parts, datetime.now(timezone.utc)
                    )
                    updates["next_fire_time"] = next_fire.replace(tzinfo=None)
                    updates["status"] = "pending"
                else:
                    updates["status"] = "error"
        # oneshot tasks stay as "fired"

        update_task_status(task_uuid, updates)
    except Exception as e:
        logger.error(f"Failed to process task {task_uuid}: {e}", exc_info=True)
        try:
            update_task_status(task_uuid, {"status": "error"})
        except Exception:
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
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"Task {task_uuid} raised an error: {e}", exc_info=True)
                    try:
                        update_task_status(task_uuid, {"status": "error"})
                    except Exception:
                        pass


# Module-level singleton
scheduled_task_scheduler = ScheduledTaskScheduler()
