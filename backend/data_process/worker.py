"""
Celery worker script for data processing tasks

This script is used to start Celery workers for processing data
and forwarding to vector storage.

Enhanced with worker initialization signal design pattern.

Usage:
    # Start a worker that handles both queues
    python worker.py

    # Start a worker for processing only (high concurrency)
    QUEUES=process_q WORKER_CONCURRENCY=8 python worker.py

    # Start a worker for forwarding only (lower concurrency)
    QUEUES=forward_q WORKER_CONCURRENCY=2 python worker.py
"""

import logging
import os
import sys
import time
import threading
import traceback

import ray
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
    ELASTICSEARCH_SERVICE,
    QUEUES,
    RAY_ADDRESS,
    RAY_preallocate_plasma,
    REDIS_URL,
    WORKER_CONCURRENCY,
    WORKER_NAME,
    RAY_GLOBAL_ACTOR_POOL_SIZE,
)

from .app import app
from .ray_config import RayConfig

# Global worker state for monitoring and debugging
worker_state = {
    'initialized': False,
    'ready': False,
    'start_time': None,
    'process_id': None,
    'tasks_completed': 0,
    'tasks_failed': 0,
    'environment_validated': False,
    'services_validated': False
}

logger = logging.getLogger("data_process.worker")


# ============================================================================
# WORKER INITIALIZATION SIGNALS
# ============================================================================
@worker_init.connect
def setup_worker_environment(**kwargs):
    """
    Call when initializing worker environment
    This is the earliest initialization step - environment variables and basic configuration
    """
    start_time = time.time()
    worker_state['start_time'] = start_time
    worker_state['process_id'] = os.getpid()

    logger.info("="*60)
    logger.info("🚀 Celery Worker initialization started")
    logger.info(f"Process ID: {os.getpid()}")
    logger.info("="*60)

    try:
        # Disable verbose Celery task success logging
        logging.getLogger('celery.worker.strategy').setLevel(logging.WARNING)

        # Initialize Ray - connect to existing cluster
        if not ray.is_initialized():
            logger.info("🔮 Ray connecting to existing cluster...")

            # Get Ray address from environment
            ray_address = RAY_ADDRESS

            try:
                os.environ["RAY_preallocate_plasma"] = str(
                    RAY_preallocate_plasma).lower()

                # Initialize Ray using the centralized RayConfig helper
                if not RayConfig.init_ray_for_worker(ray_address):
                    logger.warning("Warning: fallback to direct ray.init")
                    # Fallback to direct ray.init if helper fails
                    ray.init(
                        address=ray_address,
                        ignore_reinit_error=True,
                    )

                logger.info(
                    f"✅ Ray connected to cluster at {ray_address} successfully.")

            except Exception as e:
                logger.error(f"❌ Failed to connect to Ray cluster: {str(e)}")
                logger.error(
                    "💡 Please make sure Ray cluster is started before workers!")
                logger.error(
                    "💡 You can start it via: python data_process_service.py")
                raise ConnectionError(
                    f"Cannot connect to Ray cluster: {str(e)}")

        # Check environment variables
        logger.info("🔍 Check sensitive variables")
        sensitive_vars = {
            'REDIS_URL': REDIS_URL,
            'ELASTICSEARCH_SERVICE': ELASTICSEARCH_SERVICE
        }

        for var_name, var_value in sensitive_vars.items():
            if var_value:
                logger.debug(f"  ✅ {var_name}: SET")
            else:
                logger.error(f"  ❌ {var_name}: NOT SET")

        worker_state['initialized'] = True
        elapsed = time.time() - start_time
        logger.debug(
            f"✅ Worker environment initialized (time: {elapsed:.2f} s)")

    except Exception as e:
        logger.error(f"❌ Worker environment initialization failed: {str(e)}")
        logger.error(f"Error details: {traceback.format_exc()}")
        # Do not exit here, let Celery handle the error
        raise


@worker_process_init.connect
def setup_worker_process_resources(**kwargs):
    """
    Call when initializing each worker process
    Suitable for initializing process-specific resources (e.g. database connection pool)
    """
    process_id = os.getpid()
    logger.info(f"⚙️ Initialize worker process {process_id}")

    try:
        # Initialize process-specific resources
        # e.g. database connection pool, cache client, etc.

        # Validate critical service connections
        logger.debug("🔍 Validate service connections")
        validate_service_connections()
        worker_state['services_validated'] = True
        logger.debug("✅ Service connections validated")

        # Initialize heavy objects like DataProcessCore
        logger.debug("⚙️ Initialize data processing components")
        # Here we can pre-initialize global objects to avoid delays on the first task

        logger.debug(f"✅ Worker process {process_id} initialized")

    except Exception as e:
        logger.error(
            f"❌ Worker process {process_id} initialization failed: {str(e)}")
        raise


@worker_ready.connect
def worker_ready_handler(**kwargs):
    """
    Call when worker is fully ready
    Suitable for registering services, starting monitoring, etc.
    """
    process_id = os.getpid()
    start_time = worker_state.get('start_time')
    total_startup_time = time.time() - start_time if start_time else 0

    worker_state['ready'] = True

    logger.debug("✅ " + "="*50)
    logger.info("✅ Celery Worker is fully ready!")
    logger.debug(f"Process ID: {process_id}")
    logger.debug(f"Total startup time: {total_startup_time:.2f} s")
    logger.debug("✅ " + "="*50)

    # Display worker status summary
    logger.debug("📊 Worker status summary:")
    for key, value in worker_state.items():
        logger.debug(f"  {key}: {value}")

    # Register health check endpoints, start monitoring, etc.
    logger.debug("🔍 Worker is ready to receive tasks")

    # Prewarm Ray actors for process-related queues to reduce first-task latency.
    # IMPORTANT: run asynchronously so worker queue registration is never blocked.
    try:
        queue_set = {q.strip() for q in QUEUES.split(",") if q.strip()}
        if "process_q" in queue_set or "process_part_q" in queue_set:
            from data_process.tasks import prewarm_ray_actors

            # Prewarm a cluster-global shared actor pool once at startup.
            # Multiple workers may trigger this, but pool manager is idempotent.
            target = RAY_GLOBAL_ACTOR_POOL_SIZE

            def _prewarm_in_background():
                try:
                    warmed = prewarm_ray_actors(target_size=target)
                    logger.info(
                        f"Prewarmed Ray actor pool in background, warmed_actors={warmed}, target={target}, queues={sorted(queue_set)}"
                    )
                except Exception as exc:
                    logger.warning(f"Background prewarm failed: {exc}")

            threading.Thread(target=_prewarm_in_background, daemon=True).start()
    except Exception as exc:
        logger.warning(f"Failed to schedule Ray actor prewarm on worker ready: {exc}")

    # Periodic concurrency + Ray CPU availability log for process_part_q.
    try:
        queue_set = {q.strip() for q in QUEUES.split(",") if q.strip()}
        if "process_part_q" in queue_set:
            def _log_part_concurrency():
                while True:
                    try:
                        inspector = app.control.inspect(timeout=1)
                        active = inspector.active() or {}
                        part_active = 0
                        for _, tasks in active.items():
                            for t in tasks or []:
                                if t.get("name") == "data_process.tasks.process_part":
                                    part_active += 1
                        try:
                            ray_available = ray.available_resources() if ray.is_initialized() else {}
                        except Exception:
                            ray_available = {}
                        avail_cpu = ray_available.get("CPU", 0.0)
                        logger.info(
                            f"[process_part] active={part_active}, ray_available_cpu={avail_cpu}"
                        )
                    except Exception as exc:
                        logger.debug(f"Failed to collect process_part concurrency stats: {exc}")
                    time.sleep(5)

            threading.Thread(target=_log_part_concurrency, daemon=True).start()
    except Exception as exc:
        logger.warning(f"Failed to start process_part concurrency logger: {exc}")


@worker_shutting_down.connect
def worker_shutdown_handler(**kwargs):
    """Cleanup operations when the worker shuts down"""
    process_id = worker_state.get('process_id', os.getpid())
    uptime = time.time() - worker_state.get('start_time', time.time())

    logger.debug("🛑 " + "="*50)
    logger.info("🛑 Celery Worker is shutting down...")
    logger.debug(f"🛑 Process ID: {process_id}")
    logger.debug(f"🛑 Uptime: {uptime:.2f} s")
    logger.info(f"🛑 Completed tasks: {worker_state.get('tasks_completed', 0)}")
    logger.info(f"🛑 Failed tasks: {worker_state.get('tasks_failed', 0)}")
    logger.debug("🛑 " + "="*50)


@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds):
    """Handler before task execution"""
    logger.debug(f"📋 Task started: {task.name}[{task_id}]")


@task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **kwds):
    """Handler after task execution"""
    if state == 'SUCCESS':
        worker_state['tasks_completed'] += 1
        # No log output for successful tasks, to reduce noise
        pass
    else:
        logger.debug(f"⚠️ Task ended: {task.name}[{task_id}] - State: {state}")


@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, einfo=None, **kwds):
    """Handler when task fails"""
    worker_state['tasks_failed'] += 1
    logger.error(
        f"❌ Task failed: {sender.name}[{task_id}] - Exception: {str(exception)}")


# ============================================================================
# Service validation functions
# ============================================================================
def validate_service_connections() -> bool:
    """Validate critical service connections"""
    try:
        # Validate Redis connection
        logger.debug("🔍 Validate Redis connection")
        validate_redis_connection()
        logger.debug("✅ Redis connection is valid")

        return True

    except Exception as e:
        logger.error(f"❌ Service connection validation failed: {str(e)}")
        # Decide whether to raise an exception based on business requirements
        # Here we choose to log the error but not prevent the worker from starting
        return False


def validate_redis_connection() -> bool:
    """Validate Redis connection"""
    try:
        import redis
        redis_connection_url = REDIS_URL

        # Parse Redis URL and create connection
        redis_client = redis.from_url(redis_connection_url, socket_timeout=5)

        # Test connection
        redis_client.ping()
        return True

    except ImportError:
        logger.warning(
            "⚠️ Redis client not installed, skipping Redis connection validation")
        return False
    except Exception as e:
        logger.error(f"Redis connection failed: {str(e)}")
        raise


# ============================================================================
# Worker startup function
# ============================================================================
def start_worker():
    """Start Celery worker with appropriate settings"""

    # Read from runtime env first, so launcher-assigned values always win.
    queues = QUEUES
    worker_name = WORKER_NAME
    concurrency = WORKER_CONCURRENCY

    logger.info(f"Start Celery worker '{worker_name}' with queues: {queues}")
    logger.info(f"Worker concurrency: {concurrency}")

    # Display Celery configuration information
    logger.debug("📋 Celery configuration information:")
    logger.debug(f"  Broker URL: {app.conf.broker_url}")
    logger.debug(f"  Backend URL: {app.conf.result_backend}")
    logger.debug(f"  Task routes: {app.conf.task_routes}")
    logger.debug(f"  Task time limit: {CELERY_TASK_TIME_LIMIT} s")
    logger.debug(
        f"  Worker prefetch multiplier: {CELERY_WORKER_PREFETCH_MULTIPLIER}")

    # Worker startup parameters
    worker_args = [
        'worker',
        '--loglevel=info',
        f'--queues={queues}',
        f'--hostname={worker_name}@%h',
        f'--concurrency={concurrency}',
        '--pool=threads',
        '--task-events',
        '-Ofair'
    ]

    try:
        logger.info(f"⚙️ Starting worker '{worker_name}'...")

        # Flush stdout to ensure immediate output
        sys.stdout.flush()

        # Start worker - signal handlers will be executed at appropriate times
        app.worker_main(worker_args)

    except KeyboardInterrupt:
        logger.info(f"🛑 Worker '{worker_name}' was interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Error starting worker '{worker_name}': {str(e)}")
        logger.error(f"Error details: {traceback.format_exc()}")
        sys.exit(1)


if __name__ == '__main__':
    start_worker()
else:
    # Support importing this module and calling start_worker()
    logger.info("Worker module imported, will not start worker automatically")
