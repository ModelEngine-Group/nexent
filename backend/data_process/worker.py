"""
Celery worker entry point for data-processing and forwarding tasks.

Parser tasks run in a prefork pool so heavy native models are isolated per child.
Forwarding/orchestration workers continue to use the lightweight thread pool.
"""

from __future__ import annotations

import logging
import os
import sys
import time
import traceback
import uuid

from celery.signals import (
    task_failure,
    task_postrun,
    task_prerun,
    worker_init,
    worker_process_init,
    worker_ready,
    worker_shutting_down,
)

from consts.const import (
    CELERY_TASK_TIME_LIMIT,
    CELERY_WORKER_PREFETCH_MULTIPLIER,
    DP_PARSE_MAX_PROCESSES,
    DP_PARSE_MAX_TASKS_PER_CHILD,
    DP_PARSE_MIN_PROCESSES,
    DP_PARSE_THREADS_PER_PROCESS,
    DP_PARSER_WORKER_GENERATION,
    DP_PRELOAD_MODELS,
    QUEUES,
    REDIS_URL,
    WORKER_CONCURRENCY,
    WORKER_NAME,
)

from .app import app

logger = logging.getLogger("data_process.worker")

# Keep parent-worker validation independent from the SDK package.  Importing
# ``nexent.data_process`` executes the SDK package initializer and defeats the
# purpose of keeping Celery's main process light; the registry performs the
# authoritative model construction/validation inside the parser child.
SUPPORTED_PRELOAD_MODEL_ALIASES = {"unstructured_default", "table_transformer"}

worker_state = {
    "initialized": False,
    "ready": False,
    "start_time": None,
    "process_id": None,
    "tasks_completed": 0,
    "tasks_failed": 0,
    "environment_validated": False,
    "services_validated": False,
}
_worker_generation = DP_PARSER_WORKER_GENERATION or str(uuid.uuid4())


def _queue_set() -> set[str]:
    return {queue.strip() for queue in QUEUES.split(",") if queue.strip()}


def _is_parser_worker() -> bool:
    return "parse_q" in _queue_set()


def _validate_parser_config() -> None:
    if not _is_parser_worker():
        return
    if DP_PARSE_MAX_PROCESSES < 1:
        raise ValueError("DP_PARSE_MAX_PROCESSES must be >= 1")
    if DP_PARSE_MIN_PROCESSES < 0 or DP_PARSE_MIN_PROCESSES > DP_PARSE_MAX_PROCESSES:
        raise ValueError("DP_PARSE_MIN_PROCESSES must be between 0 and DP_PARSE_MAX_PROCESSES")
    if DP_PARSE_THREADS_PER_PROCESS < 1:
        raise ValueError("DP_PARSE_THREADS_PER_PROCESS must be >= 1")
    if DP_PARSE_MAX_TASKS_PER_CHILD < 0:
        raise ValueError("DP_PARSE_MAX_TASKS_PER_CHILD must be >= 0")
    aliases = [alias.strip() for alias in DP_PRELOAD_MODELS.split(",") if alias.strip()]
    unknown = sorted(set(aliases) - SUPPORTED_PRELOAD_MODEL_ALIASES)
    if unknown:
        raise ValueError(f"Unsupported preload model alias(es): {', '.join(unknown)}")


# ============================================================================
# Celery lifecycle signals
# ============================================================================

@worker_init.connect
def setup_worker_environment(**kwargs):
    start_time = time.time()
    worker_state["start_time"] = start_time
    worker_state["process_id"] = os.getpid()
    logger.info("Celery worker initialization started pid=%s queues=%s", os.getpid(), QUEUES)
    logging.getLogger("celery.worker.strategy").setLevel(logging.WARNING)

    _validate_parser_config()
    worker_state["initialized"] = True
    worker_state["environment_validated"] = True
    logger.info("Worker environment initialized in %.2fs", time.time() - start_time)


@worker_process_init.connect
def setup_worker_process_resources(**kwargs):
    """Initialize only child-safe lightweight resources.

    DataProcessCore and its models are intentionally initialized by ParserTask
    inside the prefork child immediately before parser work.
    """
    process_id = os.getpid()
    logger.debug("Initialize worker process pid=%s", process_id)
    try:
        from utils.monitoring import monitoring_manager

        logger.info(
            "Knowledge telemetry initialized in worker process: enabled=%s",
            monitoring_manager.is_enabled,
        )
    except Exception:
        logger.warning("Knowledge telemetry initialization failed; worker continues", exc_info=True)


@worker_ready.connect
def worker_ready_handler(**kwargs):
    worker_state["ready"] = True
    start_time = worker_state.get("start_time")
    elapsed = time.time() - start_time if start_time else 0
    logger.info("Celery worker is ready pid=%s elapsed=%.2fs queues=%s", os.getpid(), elapsed, QUEUES)

    if not _is_parser_worker():
        return

    # Queue one bootstrap task per minimum child.  This keeps idle startup
    # lightweight; autoscaled children run the same ParserTask initialization
    # before their first business task.
    try:
        from data_process.parse_tasks import parser_bootstrap

        target = max(1, DP_PARSE_MIN_PROCESSES)
        for _ in range(target):
            parser_bootstrap.apply_async(
                args=[_worker_generation, target],
                queue="parse_q",
                priority=0,
            )
        logger.info(
            "Parser bootstrap dispatched generation=%s target_children=%s preload_models=%s",
            _worker_generation,
            target,
            DP_PRELOAD_MODELS,
        )
    except Exception:
        logger.exception("Failed to dispatch parser bootstrap tasks")


@worker_shutting_down.connect
def worker_shutdown_handler(**kwargs):
    process_id = worker_state.get("process_id", os.getpid())
    uptime = time.time() - worker_state.get("start_time", time.time())
    logger.info(
        "Celery worker shutting down pid=%s uptime=%.2fs completed=%s failed=%s",
        process_id,
        uptime,
        worker_state.get("tasks_completed", 0),
        worker_state.get("tasks_failed", 0),
    )


@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, **kwds):
    logger.debug("Task started %s[%s]", task.name if task else sender, task_id)


@task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, state=None, **kwds):
    if state == "SUCCESS":
        worker_state["tasks_completed"] += 1
    else:
        logger.debug("Task ended %s[%s] state=%s", task.name if task else sender, task_id, state)


@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, **kwds):
    worker_state["tasks_failed"] += 1
    logger.error("Task failed %s[%s]: %s", sender.name if sender else "unknown", task_id, exception)


# ============================================================================
# Service validation
# ============================================================================

def validate_service_connections() -> bool:
    try:
        validate_redis_connection()
        worker_state["services_validated"] = True
        return True
    except Exception as exc:
        logger.error("Service connection validation failed: %s", exc)
        return False


def validate_redis_connection() -> bool:
    try:
        import redis

        client = redis.from_url(REDIS_URL, socket_timeout=5)
        client.ping()
        return True
    except ImportError:
        logger.warning("Redis client not installed; skipping connection validation")
        return False
    except Exception:
        logger.exception("Redis connection failed")
        raise


# ============================================================================
# Worker startup
# ============================================================================

def _set_native_thread_limits() -> None:
    """Prevent each parser child from multiplying its process by BLAS threads."""
    if not _is_parser_worker():
        return
    value = str(DP_PARSE_THREADS_PER_PROCESS)
    for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(variable, value)


def start_worker():
    """Start a Celery worker with queue-specific pool settings."""
    try:
        from utils.monitoring import monitoring_manager

        logger.info(
            "Knowledge telemetry initialized before worker start: enabled=%s",
            monitoring_manager.is_enabled,
        )
    except Exception:
        logger.warning("Knowledge telemetry initialization failed; worker continues", exc_info=True)

    queues = QUEUES
    worker_name = WORKER_NAME
    parser_worker = "parse_q" in _queue_set()
    _validate_parser_config()
    _set_native_thread_limits()

    logger.info("Start Celery worker '%s' queues=%s", worker_name, queues)
    logger.info("Worker concurrency=%s parser_worker=%s", WORKER_CONCURRENCY, parser_worker)
    logger.debug("Broker URL: %s", app.conf.broker_url)
    logger.debug("Backend URL: %s", app.conf.result_backend)
    logger.debug("Task time limit: %ss", CELERY_TASK_TIME_LIMIT)
    logger.debug("Worker prefetch multiplier: %s", CELERY_WORKER_PREFETCH_MULTIPLIER)

    worker_args = [
        "worker",
        "--loglevel=info",
        f"--queues={queues}",
        f"--hostname={worker_name}@%h",
        "--task-events",
        "-Ofair",
    ]
    if parser_worker:
        worker_args.extend(["--pool=prefork", f"--autoscale={DP_PARSE_MAX_PROCESSES},{DP_PARSE_MIN_PROCESSES}"])
        if DP_PARSE_MAX_TASKS_PER_CHILD > 0:
            worker_args.append(f"--max-tasks-per-child={DP_PARSE_MAX_TASKS_PER_CHILD}")
    else:
        worker_args.extend(["--pool=threads", f"--concurrency={WORKER_CONCURRENCY}"])

    try:
        sys.stdout.flush()
        app.worker_main(worker_args)
    except KeyboardInterrupt:
        logger.info("Worker '%s' interrupted", worker_name)
        sys.exit(0)
    except Exception as exc:
        logger.error("Error starting worker '%s': %s", worker_name, exc)
        logger.error("Error details: %s", traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    start_worker()
else:
    logger.info("Worker module imported, will not start worker automatically")
