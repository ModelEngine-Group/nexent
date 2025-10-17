"""
Celery application configuration for data processing tasks
"""
import logging

from celery import Celery
from celery.backends.base import DisabledBackend

from consts.const import ELASTICSEARCH_SERVICE, REDIS_BACKEND_URL, REDIS_URL

# Configure logging
logger = logging.getLogger("data_process.app")

# Determine package path dynamically
import_path = 'data_process.tasks'
logger.debug(f"Using import path: {import_path}")

if not REDIS_URL or not REDIS_BACKEND_URL:
    raise ValueError(
        "FATAL: REDIS_URL or REDIS_BACKEND_URL is not configured. Please check the environment variables in this container.")

logger.debug(f"Broker URL from config: {REDIS_URL}")
logger.debug(f"Backend URL from config: {REDIS_BACKEND_URL}")

# Create Celery app instance
app = Celery(
    'nexent',
    broker=REDIS_URL,
    backend=REDIS_BACKEND_URL,
    elasticsearch_service=ELASTICSEARCH_SERVICE,
    include=[import_path]
)

# Critical check: If backend is still DisabledBackend, it means configuration failed, crash immediately
if isinstance(app.backend, DisabledBackend):
    raise RuntimeError(
        "Celery result backend is disabled! "
        "This likely means REDIS_URL or REDIS_BACKEND_URL was not available during Celery app instantiation. "
        "Check your environment variables in this container."
    )

# Configure Celery settings
app.conf.update(
    # Explicitly set result backend
    broker_url=REDIS_URL,
    result_backend=REDIS_BACKEND_URL,
    # Two task queues for processing and forward steps
    task_routes={
        f'{import_path}.process': {'queue': 'process_q'},
        f'{import_path}.forward': {'queue': 'forward_q'},
        f'{import_path}.process_and_forward': {'queue': 'process_q'}
    },
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    enable_utc=True,
    # Result backend settings
    task_ignore_result=False,  # Task results must be stored for chains to work
    task_track_started=True,   # Track when tasks start
    task_store_eager_result=True,  # Store results for eager tasks
    result_backend_always_retry=True,  # Always retry backend operations
    result_backend_max_retries=10,  # Max retries for backend operations
    task_time_limit=3600,      # 1 hour time limit per task
    worker_prefetch_multiplier=1,  # Fair scheduling; avoid batchy prefetch
    worker_max_tasks_per_child=1000,  # Reduce restart frequency
    # Important for task chains
    task_acks_late=True,       # Tasks are acknowledged after completion
    task_reject_on_worker_lost=True,  # Tasks are rejected if worker is lost
    # Result storage settings
    result_expires=None,       # Results never expire
    result_persistent=True,    # Persist results to backend
    # Monitoring and task events for Flower
    task_send_sent_event=True,  # Send task-sent events
    worker_send_task_events=True,  # Enable task events from workers
    worker_hijack_root_logger=False,  # Don't hijack logging
    # Redis-specific settings for result backend
    result_backend_transport_options={
        'retry_policy': {
            'timeout': 5.0
        }
    },

    # Add broker connection configuration
    broker_connection_retry=True,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=10,
    broker_heartbeat=30,  # Heartbeat check
    broker_pool_limit=10,  # Connection pool size

    # Add transport options
    broker_transport_options={
        'visibility_timeout': 3600,
        'max_retries': 5,
        'interval_start': 0,
        'interval_step': 0.2,
        'interval_max': 0.5,
        'master_name': 'mymaster',  # If using Redis Sentinel
    }
)
