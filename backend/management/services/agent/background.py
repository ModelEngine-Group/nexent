# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Server-owned identity and terminal evidence for one background execution."""

import asyncio
from dataclasses import dataclass
from typing import Callable, Optional


async def settle_background_projection(projection):
    """Let an in-flight commit settle before propagating cancellation.

    The task is owned here and always joined. A second cancellation cannot
    leave an unobserved finalizer running after the scheduler has returned.
    """
    task = asyncio.create_task(projection)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        deadline = asyncio.get_running_loop().time() + 5
        while not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), max(0, deadline - asyncio.get_running_loop().time()))
            except asyncio.CancelledError:
                continue
            except asyncio.TimeoutError:
                task.cancel()
                break
            except Exception:
                break
        await asyncio.gather(task, return_exceptions=True)
        raise


@dataclass
class BackgroundExecutionState:
    runtime_generation: Optional[str] = None
    is_active: Optional[Callable] = None
    create_assistant: Optional[Callable] = None
    assistant_message_id: Optional[int] = None
    outcome: Optional[str] = None
    persisted: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    def fail(self, code: str, message: str) -> None:
        self.outcome = "failed"
        self.error_code = code
        self.error_message = message

    def result(self) -> dict:
        """Require positive terminal and persistence evidence before success."""
        if self.outcome == "completed" and (
            not self.persisted or self.assistant_message_id is None
        ):
            self.fail("AUTOMATION_PERSISTENCE_FAILED", "Assistant result was not saved.")
        elif self.outcome not in {"completed", "failed", "stopped"}:
            self.fail("AUTOMATION_OUTCOME_MISSING", "Execution ended without a terminal outcome.")
        if self.outcome == "failed" and not self.error_code:
            self.fail("AUTOMATION_EXECUTION_FAILED", "Agent execution failed.")
        return {
            "assistant_message_id": self.assistant_message_id,
            "status": self.outcome,
            "persisted": self.persisted,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }
