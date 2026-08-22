import logging
import threading
import asyncio
from typing import Dict, Set
from threading import Event

logger = logging.getLogger("preprocess_manager")


class PreprocessTask:
    def __init__(self, task_id: str, conversation_id: int):
        self.task_id = task_id
        self.conversation_id = conversation_id
        self.stop_event = Event()
        self.is_running = True
        self.task = None  # asyncio.Task reference


class PreprocessManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(PreprocessManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            # task_id -> PreprocessTask
            self.preprocess_tasks: Dict[str, PreprocessTask] = {}
            # conversation_id -> Set[task_id]
            self.conversation_tasks: Dict[int, Set[str]] = {}
            self._initialized = True

    def register_preprocess_task(self, task_id: str, conversation_id: int, task: asyncio.Task):
        """Register a preprocess task"""
        with self._lock:
            preprocess_task = PreprocessTask(task_id, conversation_id)
            preprocess_task.task = task
            self.preprocess_tasks[task_id] = preprocess_task

            if conversation_id not in self.conversation_tasks:
                self.conversation_tasks[conversation_id] = set()
            self.conversation_tasks[conversation_id].add(task_id)

            logger.info(
                f"Registered preprocess task {task_id} for conversation {conversation_id}")

    def unregister_preprocess_task(self, task_id: str):
        """Unregister a preprocess task"""
        with self._lock:
            if task_id in self.preprocess_tasks:
                task = self.preprocess_tasks[task_id]
                conversation_id = task.conversation_id

                # Remove from conversation_tasks
                if conversation_id in self.conversation_tasks:
                    self.conversation_tasks[conversation_id].discard(task_id)
                    if not self.conversation_tasks[conversation_id]:
                        del self.conversation_tasks[conversation_id]

                # Remove from preprocess_tasks
                del self.preprocess_tasks[task_id]

                logger.info(f"Unregistered preprocess task {task_id}")

    def stop_preprocess_tasks(self, conversation_id: int) -> bool:
        """Stop all preprocess tasks for a conversation"""
        with self._lock:
            if conversation_id not in self.conversation_tasks:
                return False

            task_ids = self.conversation_tasks[conversation_id].copy()
            stopped_count = 0

            for task_id in task_ids:
                if task_id in self.preprocess_tasks:
                    task = self.preprocess_tasks[task_id]
                    if task.is_running:
                        task.stop_event.set()
                        task.is_running = False

                        # Cancel the asyncio task if it exists
                        if task.task and not task.task.done():
                            task.task.cancel()

                        stopped_count += 1
                        logger.info(
                            f"Stopped preprocess task {task_id} for conversation {conversation_id}")

            return stopped_count > 0

    def is_preprocess_running(self, conversation_id: int) -> bool:
        """Check if any preprocess task is running for a conversation"""
        with self._lock:
            if conversation_id not in self.conversation_tasks:
                return False

            for task_id in self.conversation_tasks[conversation_id]:
                if task_id in self.preprocess_tasks:
                    task = self.preprocess_tasks[task_id]
                    if task.is_running and not task.stop_event.is_set():
                        return True

            return False

    def get_preprocess_status(self, conversation_id: int) -> Dict:
        """Get preprocess status for a conversation"""
        with self._lock:
            if conversation_id not in self.conversation_tasks:
                return {"running": False, "task_count": 0}

            running_tasks = []
            for task_id in self.conversation_tasks[conversation_id]:
                if task_id in self.preprocess_tasks:
                    task = self.preprocess_tasks[task_id]
                    running_tasks.append({
                        "task_id": task_id,
                        "is_running": task.is_running,
                        "stopped": task.stop_event.is_set()
                    })

            return {
                "running": any(task["is_running"] for task in running_tasks),
                "task_count": len(running_tasks),
                "tasks": running_tasks
            }


# Create singleton instance
preprocess_manager = PreprocessManager()
