# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import os
from pathlib import Path
from dotenv import load_dotenv
from ..configuration import parse_positive_float, parse_positive_int, _require_positive, _build_otlp_headers, _resolve_app_version

# Environment initialization
# Repository-root callers import this module through the backend namespace.
# Load environment variables
# Explicitly sourced deployment variables take precedence over a nearby
# developer .env file. This is required for tmux/K8s-local verification and
# avoids silently replacing operator-provided service addresses.
_ENVIRONMENT_LOADED = load_dotenv(override=False)
_CONFIG_DIRECTORY = Path(__file__).resolve().parents[2] / 'configs'

# Elasticsearch Configuration
ES_HOST = os.getenv('ELASTICSEARCH_HOST')
ES_API_KEY = os.getenv('ELASTICSEARCH_API_KEY')
ES_PASSWORD = os.getenv('ELASTIC_PASSWORD')
ELASTICSEARCH_SERVICE = os.getenv('ELASTICSEARCH_SERVICE')

# Data Processing Service Configuration
DATA_PROCESS_SERVICE = os.getenv('DATA_PROCESS_SERVICE')
RUNTIME_SERVICE_URL = os.getenv('RUNTIME_SERVICE_URL', 'http://localhost:5014').rstrip('/')
CLIP_MODEL_PATH = os.getenv('CLIP_MODEL_PATH')
TABLE_TRANSFORMER_MODEL_PATH = os.getenv('TABLE_TRANSFORMER_MODEL_PATH')
UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH = os.getenv('UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH')

# Knowledge-base uploads have an independently configurable hard ceiling.
MAX_KNOWLEDGE_FILE_SIZE_MB = parse_positive_int(os.getenv('MAX_KNOWLEDGE_FILE_SIZE_MB'), 'MAX_KNOWLEDGE_FILE_SIZE_MB', 100)
MAX_KNOWLEDGE_FILE_SIZE_BYTES = MAX_KNOWLEDGE_FILE_SIZE_MB * 1024 * 1024
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')
AGENT_WORKSPACE_ROOT = os.getenv('AGENT_WORKSPACE_ROOT', '/mnt/nexent/workdir')
NEXENT_SANDBOX_WORKSPACE_MODE = os.getenv('NEXENT_SANDBOX_WORKSPACE_MODE', 'legacy')
NEXENT_SANDBOX_CONTAINER_WORKSPACE_ROOT = os.getenv('NEXENT_SANDBOX_CONTAINER_WORKSPACE_ROOT', '')
NEXENT_SANDBOX_FAILURE_POLICY = os.getenv('NEXENT_SANDBOX_FAILURE_POLICY', 'local')
ROOT_DIR = os.getenv('ROOT_DIR')
PER_WAVE_TIMEOUT = int(os.getenv('DP_SPLIT_WAIT_TIMEOUT_PER_WAVE_S', '30'))
MAX_TIMEOUT = int(os.getenv('DP_SPLIT_WAIT_TIMEOUT_MAX_S', '1800'))

# Document deletion coordination.  The Redis deletion fence itself never
# expires; these values only bound one drain attempt and background retry
# cadence while workers finish an in-flight request.
DOCUMENT_DELETE_DRAIN_TIMEOUT_S = float(os.getenv('DOCUMENT_DELETE_DRAIN_TIMEOUT_S', '30'))
DOCUMENT_DELETE_RETRY_INTERVAL_S = float(os.getenv('DOCUMENT_DELETE_RETRY_INTERVAL_S', '2'))

# Agent automation runtime configuration
AGENT_AUTOMATION_ENABLED = os.getenv('AGENT_AUTOMATION_ENABLED', 'true').lower() in ('true', '1', 'yes', 'on')
AGENT_AUTOMATION_POLL_INTERVAL_SECONDS = int(os.getenv('AGENT_AUTOMATION_POLL_INTERVAL_SECONDS', '5'))
AGENT_AUTOMATION_MAX_CONCURRENT_RUNS = int(os.getenv('AGENT_AUTOMATION_MAX_CONCURRENT_RUNS', '2'))

# Unified tag document retrieval projection rollout flag. When enabled, document
# assignments are projected to retrieval providers and tracked in the
# document_tag_projection ledger; canonical assignments are never rolled back
# when a provider rejects or delays a projection.
TAG_DOCUMENT_PROJECTION_ENABLED = os.getenv('TAG_DOCUMENT_PROJECTION_ENABLED', 'true').lower() in ('true', '1', 'yes', 'on')
AGENT_AUTOMATION_LEASE_SECONDS = int(os.getenv('AGENT_AUTOMATION_LEASE_SECONDS', '120'))
AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS = int(os.getenv('AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS', '1800'))
AGENT_AUTOMATION_SHUTDOWN_GRACE_SECONDS = int(os.getenv('AGENT_AUTOMATION_SHUTDOWN_GRACE_SECONDS', '30'))
AGENT_AUTOMATION_MIN_INTERVAL_SECONDS = int(os.getenv('AGENT_AUTOMATION_MIN_INTERVAL_SECONDS', '5'))

# Container-internal skills storage path
CONTAINER_SKILLS_PATH = os.getenv('SKILLS_PATH')

# Container-internal official skills ZIP directory
OFFICIAL_SKILLS_ZIP_PATH = os.getenv('OFFICIAL_SKILLS_ZIP_PATH', '/mnt/nexent/official-skills-zip')

# Container-internal official agents bundle directory (one JSON per agent)
OFFICIAL_AGENTS_PATH = os.getenv('OFFICIAL_AGENTS_PATH', '/mnt/nexent/official-agents')
OFFICIAL_AGENT_PROFILES = os.getenv('OFFICIAL_AGENT_PROFILES', '')

# LibreOffice profile directory
LIBREOFFICE_PROFILE_DIR = os.getenv('LIBREOFFICE_PROFILE_DIR', str(Path.home() / '.cache' / 'nexent' / 'libreoffice-profile'))

# Supabase Configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
SERVICE_ROLE_KEY = os.getenv('SERVICE_ROLE_KEY', SUPABASE_KEY)

# JWT secret for verifying Supabase-signed access tokens.
# GoTrue uses GOTRUE_JWT_SECRET (= JWT_SECRET in docker setup) to sign tokens.
SUPABASE_JWT_SECRET = os.getenv('SUPABASE_JWT_SECRET') or os.getenv('JWT_SECRET', '')

# Dedicated signing key for opaque independent-AIDP image references. The JWT
# fallback keeps existing deployments functional while allowing key separation.
IND_AIDP_IMAGE_SIGNING_KEY = os.getenv('IND_AIDP_IMAGE_SIGNING_KEY') or SUPABASE_JWT_SECRET

# OAuth Configuration
OAUTH_CALLBACK_BASE_URL = os.getenv('OAUTH_CALLBACK_BASE_URL', '').rstrip('/')
OAUTH_SSL_VERIFY = os.getenv('OAUTH_SSL_VERIFY', 'true').lower() == 'true'
OAUTH_CA_BUNDLE = os.getenv('OAUTH_CA_BUNDLE', '')

# OAuth login mode:
# - disabled: hide OAuth login entries and disable automatic OAuth redirects.
# - button: show configured OAuth providers as optional login entries.
# - force: automatically redirect when exactly one OAuth provider is configured.
OAUTH_LOGIN_MODE = os.getenv('OAUTH_LOGIN_MODE', 'button').lower()

# CAS SSO Configuration
CAS_ENABLED = os.getenv('CAS_ENABLED', 'false').lower() in ('true', '1', 'yes', 'on')
CAS_SERVER_URL = os.getenv('CAS_SERVER_URL', '').rstrip('/')

# Optional backend-only URL for CAS servers reachable through an internal container network.
CAS_INTERNAL_SERVER_URL = os.getenv('CAS_INTERNAL_SERVER_URL', '').rstrip('/')
CAS_VALIDATE_PATH = os.getenv('CAS_VALIDATE_PATH', '/p3/serviceValidate')
CAS_CALLBACK_BASE_URL = os.getenv('CAS_CALLBACK_BASE_URL', OAUTH_CALLBACK_BASE_URL).rstrip('/')

# CAS login mode:
# - disabled: disable CAS login entry and automatic CAS redirects.
# - button: show CAS as an optional login entry.
# - force: automatically redirect unauthenticated users to CAS login.
CAS_LOGIN_MODE = os.getenv('CAS_LOGIN_MODE', 'disabled').lower()
CAS_USER_ATTRIBUTE = os.getenv('CAS_USER_ATTRIBUTE', '')
CAS_EMAIL_ATTRIBUTE = os.getenv('CAS_EMAIL_ATTRIBUTE', 'email')
CAS_ROLE_ATTRIBUTE = os.getenv('CAS_ROLE_ATTRIBUTE', 'role')
CAS_DEFAULT_ROLE = os.getenv('CAS_DEFAULT_ROLE', 'USER').strip().upper()
CAS_TENANT_ATTRIBUTE = os.getenv('CAS_TENANT_ATTRIBUTE', 'tenant_id')
CAS_DEFAULT_TENANT_ID = os.getenv('CAS_DEFAULT_TENANT_ID', 'tenant_id')
CAS_ROLE_MAP_JSON = os.getenv('CAS_ROLE_MAP_JSON', '')
CAS_SESSION_MAX_AGE_SECONDS = int(os.getenv('CAS_SESSION_MAX_AGE_SECONDS', '3600') or 3600)
LOCAL_SESSION_MAX_AGE_SECONDS = int(os.getenv('LOCAL_SESSION_MAX_AGE_SECONDS', '3600') or 3600)
CAS_HEARTBEAT_URL = os.getenv('CAS_HEARTBEAT_URL', '').strip()
CAS_HEARTBEAT_INTERVAL_SECONDS = int(os.getenv('CAS_HEARTBEAT_INTERVAL_SECONDS', '300') or 300)
CAS_HEARTBEAT_COOKIE_NAME = os.getenv('CAS_HEARTBEAT_COOKIE_NAME', '').strip()
CAS_RENEW_BEFORE_SECONDS = int(os.getenv('CAS_RENEW_BEFORE_SECONDS', '300') or 300)
CAS_RENEW_TIMEOUT_SECONDS = int(os.getenv('CAS_RENEW_TIMEOUT_SECONDS', '10') or 10)
CAS_SYNTHETIC_EMAIL_DOMAIN = os.getenv('CAS_SYNTHETIC_EMAIL_DOMAIN', '')
CAS_LOGOUT_URL = os.getenv('CAS_LOGOUT_URL', '')
CAS_SSL_VERIFY = os.getenv('CAS_SSL_VERIFY', 'true').lower() == 'true'
CAS_CA_BUNDLE = os.getenv('CAS_CA_BUNDLE', '')

# ===== To be migrated to frontend configuration =====
# Email Configuration
IMAP_SERVER = os.getenv('IMAP_SERVER')
IMAP_PORT = os.getenv('IMAP_PORT')
SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PORT = os.getenv('SMTP_PORT')
MAIL_USERNAME = os.getenv('MAIL_USERNAME')
MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')

# EXASearch Configuration
EXA_SEARCH_API_KEY = os.getenv('EXA_SEARCH_API_KEY')

# Image Filter Configuration
IMAGE_FILTER = os.getenv('IMAGE_FILTER', 'false').lower() == 'true'

# Tenant resource hard limits. Environment variables override these defaults.
MAX_TENANT_COUNT = parse_positive_int(os.getenv('MAX_TENANT_COUNT'), 'MAX_TENANT_COUNT', 100)
MAX_USERS_PER_TENANT = parse_positive_int(os.getenv('MAX_USERS_PER_TENANT'), 'MAX_USERS_PER_TENANT', 10000)
MAX_GROUPS_PER_TENANT = parse_positive_int(os.getenv('MAX_GROUPS_PER_TENANT'), 'MAX_GROUPS_PER_TENANT', 1000)
MAX_SUPER_ADMIN_COUNT = parse_positive_int(os.getenv('MAX_SUPER_ADMIN_COUNT'), 'MAX_SUPER_ADMIN_COUNT', 1)
MAX_ADMINS_PER_TENANT = parse_positive_int(os.getenv('MAX_ADMINS_PER_TENANT'), 'MAX_ADMINS_PER_TENANT', 1000)
MAX_KNOWLEDGE_BASES_PER_TENANT = parse_positive_int(os.getenv('MAX_KNOWLEDGE_BASES_PER_TENANT'), 'MAX_KNOWLEDGE_BASES_PER_TENANT', 10000)
MAX_KNOWLEDGE_BASES_PER_USER = parse_positive_int(os.getenv('MAX_KNOWLEDGE_BASES_PER_USER'), 'MAX_KNOWLEDGE_BASES_PER_USER', 10)
MAX_PRIVILEGED_KNOWLEDGE_BASES_PER_USER = parse_positive_int(os.getenv('MAX_PRIVILEGED_KNOWLEDGE_BASES_PER_USER'), 'MAX_PRIVILEGED_KNOWLEDGE_BASES_PER_USER', 1000)
MAX_CONVERSATION_TURNS = parse_positive_int(os.getenv('MAX_CONVERSATION_TURNS'), 'MAX_CONVERSATION_TURNS', 100)
MAX_CONVERSATIONS_PER_USER = parse_positive_int(os.getenv('MAX_CONVERSATIONS_PER_USER'), 'MAX_CONVERSATIONS_PER_USER', 1000)
MAX_AGENTS_PER_TENANT = parse_positive_int(os.getenv('MAX_AGENTS_PER_TENANT'), 'MAX_AGENTS_PER_TENANT', 1000)

# Skill resource hard limits. Environment variables override these defaults.
MAX_SKILLS_PER_TENANT = parse_positive_int(os.getenv('MAX_SKILLS_PER_TENANT'), 'MAX_SKILLS_PER_TENANT', 1000)
MAX_SKILL_UPLOAD_SIZE_MB = parse_positive_int(os.getenv('MAX_SKILL_UPLOAD_SIZE_MB'), 'MAX_SKILL_UPLOAD_SIZE_MB', 10)
MAX_SKILL_UPLOAD_SIZE_BYTES = MAX_SKILL_UPLOAD_SIZE_MB * 1024 * 1024

# Evaluation-set Excel uploads.
MAX_EVALUATION_SET_FILE_SIZE_MB = parse_positive_int(os.getenv('MAX_EVALUATION_SET_FILE_SIZE_MB'), 'MAX_EVALUATION_SET_FILE_SIZE_MB', 20)
MAX_EVALUATION_SET_FILE_SIZE_BYTES = MAX_EVALUATION_SET_FILE_SIZE_MB * 1024 * 1024

# When false, block ASSET_OWNER invites, registrations, and sign-in.
ENABLE_ASSET_OWNER_ROLE = os.getenv('ENABLE_ASSET_OWNER_ROLE', 'false').lower() == 'true'

# W11 capacity suggestion rollout flags.
CAPACITY_SUGGESTION_ENABLED = os.getenv('CAPACITY_SUGGESTION_ENABLED', 'true').lower() in ('true', '1', 'yes', 'on')
CAPACITY_VISIBILITY_ENABLED = os.getenv('CAPACITY_VISIBILITY_ENABLED', 'true').lower() in ('true', '1', 'yes', 'on')

# Deployment Version Configuration
DEPLOYMENT_VERSION = os.getenv('DEPLOYMENT_VERSION', 'speed')
IS_SPEED_MODE = DEPLOYMENT_VERSION == 'speed'

# AIDP Knowledge Base configuration
ENABLE_AIDP_KNOWLEDGE = os.getenv('ENABLE_AIDP_KNOWLEDGE', 'false').lower() in ('true', '1', 'yes', 'on')

# Defaults are on so a fresh deployment lands on the Agent Workbench with the
# standalone Home page hidden. Set either variable to a falsey value to opt out.
ENABLE_AGENT_WORKBENCH = os.getenv('ENABLE_AGENT_WORKBENCH', 'true').lower() in ('true', '1', 'yes', 'on')
HIDE_HOME_PAGE = os.getenv('HIDE_HOME_PAGE', 'true').lower() in ('true', '1', 'yes', 'on')
AIDP_SERVER_URL = os.getenv('AIDP_SERVER_URL', '')
AIDP_API_KEY = os.getenv('AIDP_API_KEY', '')
AIDP_TENANT_ID = os.getenv('AIDP_TENANT_ID', 'aidp')

# Minio Configuration
MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT')
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY')
MINIO_REGION = os.getenv('MINIO_REGION')
MINIO_DEFAULT_BUCKET = os.getenv('MINIO_DEFAULT_BUCKET')
MINIO_SECURE = os.getenv('MINIO_SECURE', 'true').lower() == 'true'

# Postgres Configuration
POSTGRES_HOST = os.getenv('POSTGRES_HOST')
POSTGRES_USER = os.getenv('POSTGRES_USER')
NEXENT_POSTGRES_PASSWORD = os.getenv('NEXENT_POSTGRES_PASSWORD')
POSTGRES_DB = os.getenv('POSTGRES_DB')
POSTGRES_PORT = os.getenv('POSTGRES_PORT')

# Data Processing Service Configuration
REDIS_URL = os.getenv('REDIS_URL')
REDIS_BACKEND_URL = os.getenv('REDIS_BACKEND_URL')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
RUNTIME_STATE_REDIS_URL = os.getenv('RUNTIME_STATE_REDIS_URL') or REDIS_URL
RUNTIME_STREAM_TTL_SECONDS = int(os.getenv('RUNTIME_STREAM_TTL_SECONDS', '86400'))
RUNTIME_STREAM_MAX_LEN = int(os.getenv('RUNTIME_STREAM_MAX_LEN', '10000'))
RUNTIME_STREAM_LOCAL_REPLAY_MAX_BYTES = int(os.getenv('RUNTIME_STREAM_LOCAL_REPLAY_MAX_BYTES', str(8 * 1024 * 1024)))
RUNTIME_RUN_TTL_SECONDS = int(os.getenv('RUNTIME_RUN_TTL_SECONDS', '86400'))
RUNTIME_CANCEL_TTL_SECONDS = int(os.getenv('RUNTIME_CANCEL_TTL_SECONDS', '86400'))
RUNTIME_COMPLETED_TTL_SECONDS = int(os.getenv('RUNTIME_COMPLETED_TTL_SECONDS', '300'))
RUNTIME_CANCEL_POLL_INTERVAL_SECONDS = float(os.getenv('RUNTIME_CANCEL_POLL_INTERVAL_SECONDS', '1.0'))
RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS = int(os.getenv('RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS', '50'))
RUNTIME_AGENT_THREAD_MAX_WORKERS = int(os.getenv('RUNTIME_AGENT_THREAD_MAX_WORKERS', '200'))
RUNTIME_AGENT_THREAD_MAX_QUEUE_SIZE = int(os.getenv('RUNTIME_AGENT_THREAD_MAX_QUEUE_SIZE', '32'))
_VALIDATED_RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS = _require_positive(RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS, 'RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS must be greater than zero')
_VALIDATED_RUNTIME_AGENT_THREAD_MAX_WORKERS = _require_positive(RUNTIME_AGENT_THREAD_MAX_WORKERS, 'RUNTIME_AGENT_THREAD_MAX_WORKERS must be greater than zero')
RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS = float(os.getenv('RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS', '30'))
_VALIDATED_RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS = _require_positive(RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS, 'RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS must be greater than zero')
RUNTIME_AGENT_THREAD_CANCEL_GRACE_SECONDS = float(os.getenv('RUNTIME_AGENT_THREAD_CANCEL_GRACE_SECONDS', '5'))
RUNTIME_MCP_TOOL_TIMEOUT_SECONDS = float(os.getenv('RUNTIME_MCP_TOOL_TIMEOUT_SECONDS', '60'))
RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS = int(os.getenv('RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS', '120'))
_VALIDATED_RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS = _require_positive(RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS, 'RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS must be greater than zero')
RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS = float(os.getenv('RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS', '5'))
_VALIDATED_RUNTIME_MCP_TOOL_TIMEOUT_SECONDS = _require_positive(RUNTIME_MCP_TOOL_TIMEOUT_SECONDS, 'RUNTIME_MCP_TOOL_TIMEOUT_SECONDS must be greater than zero')
_VALIDATED_RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS = _require_positive(RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS, 'RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS must be greater than zero')
RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS = float(os.getenv('RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS', '30'))
NORTHBOUND_CONTROL_THREAD_MAX_WORKERS = int(os.getenv('NORTHBOUND_CONTROL_THREAD_MAX_WORKERS', '8'))
NORTHBOUND_CONTROL_THREAD_MAX_QUEUE_SIZE = int(os.getenv('NORTHBOUND_CONTROL_THREAD_MAX_QUEUE_SIZE', '64'))
NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS = float(os.getenv('NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS', '15'))
NORTHBOUND_IDEMPOTENCY_TTL_SECONDS = int(os.getenv('NORTHBOUND_IDEMPOTENCY_TTL_SECONDS', '600'))
NORTHBOUND_RATE_LIMIT_ENABLED = os.getenv('NORTHBOUND_RATE_LIMIT_ENABLED', 'true').lower() == 'true'
NORTHBOUND_RATE_LIMIT_PER_MINUTE = int(os.getenv('NORTHBOUND_RATE_LIMIT_PER_MINUTE', '120'))
FLOWER_PORT = int(os.getenv('FLOWER_PORT', '5555'))
DP_REDIS_CHUNKS_WAIT_TIMEOUT_S = int(os.getenv('DP_REDIS_CHUNKS_WAIT_TIMEOUT_S', '300'))
DP_REDIS_CHUNKS_POLL_INTERVAL_MS = int(os.getenv('DP_REDIS_CHUNKS_POLL_INTERVAL_MS', '200'))
REDIS_ERROR_INFO_TTL_SECONDS = int(os.getenv('REDIS_ERROR_INFO_TTL_SECONDS', str(1 * 24 * 60 * 60)))
REDIS_ERROR_INFO_SCAN_COUNT = int(os.getenv('REDIS_ERROR_INFO_SCAN_COUNT', '500'))
FORWARD_REDIS_RETRY_DELAY_S = int(os.getenv('FORWARD_REDIS_RETRY_DELAY_S', '5'))
FORWARD_REDIS_RETRY_MAX = int(os.getenv('FORWARD_REDIS_RETRY_MAX', '12'))

# Data processing parser configuration
DP_PART_PROCESSOR_COUNT = int(os.getenv('DP_PART_PROCESSOR_COUNT', '3'))
DP_FILE_SPLIT_SIZE_MB = int(os.getenv('DP_FILE_SPLIT_SIZE_MB', '5'))
DP_PARSE_MAX_PROCESSES = int(os.getenv('DP_PARSE_MAX_PROCESSES', '3'))
DP_PARSE_MIN_PROCESSES = int(os.getenv('DP_PARSE_MIN_PROCESSES', '1'))
DP_PARSE_THREADS_PER_PROCESS = int(os.getenv('DP_PARSE_THREADS_PER_PROCESS', '2'))
DP_PARSE_MAX_TASKS_PER_CHILD = int(os.getenv('DP_PARSE_MAX_TASKS_PER_CHILD', '1000'))
DP_PRELOAD_MODELS = os.getenv('DP_PRELOAD_MODELS', 'unstructured_default').strip()
DP_PARSER_STARTUP_TIMEOUT_S = int(os.getenv('DP_PARSER_STARTUP_TIMEOUT_S', '300'))
DP_PARSER_WORKER_GENERATION = os.getenv('DP_PARSER_WORKER_GENERATION', '').strip()

# Logging Configuration
LOG_DIR = os.getenv('LOG_DIR', 'logs')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

# When IS_DEBUG=true, force DEBUG level for all loggers (overrides LOG_LEVEL).
IS_DEBUG = os.getenv('IS_DEBUG', 'false').lower() == 'true'
# days
LOG_ROTATION_INTERVAL = int(os.getenv('LOG_ROTATION_INTERVAL', '1'))
# 50 MB
LOG_MAX_BYTES = int(os.getenv('LOG_MAX_BYTES', str(50 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', '30'))

# Service Control Flags
DISABLE_CELERY_FLOWER = os.getenv('DISABLE_CELERY_FLOWER', 'false').lower() == 'true'
DOCKER_ENVIRONMENT = os.getenv('DOCKER_ENVIRONMENT', 'false').lower() == 'true'
NEXENT_MCP_DOCKER_IMAGE = os.getenv('NEXENT_MCP_DOCKER_IMAGE', 'nexent/nexent-mcp:latest')
ENABLE_UPLOAD_IMAGE = os.getenv('ENABLE_UPLOAD_IMAGE', 'false').lower() == 'true'
ENABLE_JIUWEN_SDK = os.getenv('NEXENT_ENABLE_JIUWEN_SDK', 'true').lower() == 'true'

# Celery Configuration
CELERY_WORKER_PREFETCH_MULTIPLIER = int(os.getenv('CELERY_WORKER_PREFETCH_MULTIPLIER', '1'))
CELERY_TASK_TIME_LIMIT = int(os.getenv('CELERY_TASK_TIME_LIMIT', '3600'))
ELASTICSEARCH_REQUEST_TIMEOUT = int(os.getenv('ELASTICSEARCH_REQUEST_TIMEOUT', '30'))

# Worker Configuration
QUEUES = os.getenv('QUEUES', 'process_q,parse_q,forward_q,forward_part_q,forward_aggregate_q')

# Will be dynamically set based on PID if not provided
WORKER_NAME = os.getenv('WORKER_NAME')

# The data-process service sets a queue-specific value for each child worker.
# Keep the historical default when the variable is not provided.
WORKER_CONCURRENCY = int(os.getenv('WORKER_CONCURRENCY', str(DP_PART_PROCESSOR_COUNT + 1)))

# Voice Service Configuration
APPID = os.getenv('APPID', '')
TOKEN = os.getenv('TOKEN', '')
CLUSTER = os.getenv('CLUSTER', 'volcano_tts')
VOICE_TYPE = os.getenv('VOICE_TYPE', 'zh_male_jieshuonansheng_mars_bigtts')
SPEED_RATIO = float(os.getenv('SPEED_RATIO', '1.3'))

# ===== Memory System =====
# MMR (Maximal Marginal Relevance) configuration
MMR_LAMBDA = float(os.getenv('MMR_LAMBDA', '0.7'))
MMR_CANDIDATE_TOP_K = int(os.getenv('MMR_CANDIDATE_TOP_K', '10'))
MMR_FINAL_TOP_K = int(os.getenv('MMR_FINAL_TOP_K', '5'))
MMR_DUPLICATE_THRESHOLD = float(os.getenv('MMR_DUPLICATE_THRESHOLD', '0.92'))

# Temporal decay (only applied to internal agent short-term memory)
AGENT_SHORT_TERM_HALF_LIFE_DAYS = int(os.getenv('AGENT_SHORT_TERM_HALF_LIFE_DAYS', '14'))

# Score fusion source weights
W_AGENT_SHORT_TERM = float(os.getenv('W_AGENT_SHORT_TERM', '1.0'))
W_EXTERNAL = float(os.getenv('W_EXTERNAL', '0.8'))

# Token budget selection
MEMORY_TOKEN_BUDGET = int(os.getenv('MEMORY_TOKEN_BUDGET', '2000'))

# Dreaming promotion thresholds
LIGHT_SLEEP_WINDOW_DAYS = int(os.getenv('LIGHT_SLEEP_WINDOW_DAYS', '7'))
RECENCY_HALF_LIFE_DAYS = int(os.getenv('RECENCY_HALF_LIFE_DAYS', '14'))
MIN_PROMOTION_SCORE = float(os.getenv('MIN_PROMOTION_SCORE', '0.75'))
MIN_RECALL_COUNT = int(os.getenv('MIN_RECALL_COUNT', '3'))
MIN_UNIQUE_QUERIES = int(os.getenv('MIN_UNIQUE_QUERIES', '3'))
DREAMING_SOURCE_LIMIT = int(os.getenv('DREAMING_SOURCE_LIMIT', '10'))
DREAMING_LONG_TERM_MAX_CHARS = int(os.getenv('DREAMING_LONG_TERM_MAX_CHARS', '10000'))
DREAMING_SUMMARIZATION_MAX_ATTEMPTS = int(os.getenv('DREAMING_SUMMARIZATION_MAX_ATTEMPTS', '2'))
DREAMING_SCHEDULER_POLL_SECONDS = float(os.getenv('DREAMING_SCHEDULER_POLL_SECONDS', '5.0'))
DREAMING_SCHEDULER_LEASE_SECONDS = float(os.getenv('DREAMING_SCHEDULER_LEASE_SECONDS', '120.0'))
DREAMING_SCHEDULER_MAX_CONCURRENCY = int(os.getenv('DREAMING_SCHEDULER_MAX_CONCURRENCY', '1'))
DREAMING_SCHEDULER_ENABLED = os.getenv('DREAMING_SCHEDULER_ENABLED', 'true').lower() in ('true', '1', 'yes')
DREAMING_MAX_AGE_DAYS = int(os.getenv('DREAMING_MAX_AGE_DAYS', '30'))
DREAMING_SUMMARIZATION_BACKOFF_BASE_SECONDS = float(os.getenv('DREAMING_SUMMARIZATION_BACKOFF_BASE_SECONDS', '1.0'))

# External provider retry / timeout
PROVIDER_RETRY_MAX_ATTEMPTS = int(os.getenv('PROVIDER_RETRY_MAX_ATTEMPTS', '3'))
PROVIDER_RETRY_BACKOFF_BASE_SECONDS = int(os.getenv('PROVIDER_RETRY_BACKOFF_BASE_SECONDS', '1'))
PROVIDER_REQUEST_TIMEOUT_SECONDS = int(os.getenv('PROVIDER_REQUEST_TIMEOUT_SECONDS', '30'))

# MCP Server
LOCAL_MCP_SERVER = os.getenv('NEXENT_MCP_SERVER')
MCP_MANAGEMENT_API = os.getenv('MCP_MANAGEMENT_API', 'http://localhost:5015')

# Maximum number of configured MCP services per tenant.
MAX_MCP_SERVICES_PER_TENANT = parse_positive_int(os.getenv('MAX_MCP_SERVICES_PER_TENANT'), 'MAX_MCP_SERVICES_PER_TENANT', 1000)

# Maximum time allowed to establish a connection and complete the MCP
# initialization handshake. This does not limit tool execution time.
MCP_REQUEST_TIMEOUT_SECONDS = parse_positive_float(os.getenv('MCP_REQUEST_TIMEOUT_SECONDS'), 'MCP_REQUEST_TIMEOUT_SECONDS', 10)

# Invite code
INVITE_CODE = os.getenv('INVITE_CODE')

# Access-token lifetime in seconds. This must match GoTrue's GOTRUE_JWT_EXP.
JWT_EXPIRY_SECONDS = int(os.getenv('JWT_EXPIRY', '7200') or 7200)
_VALIDATED_JWT_EXPIRY_SECONDS = _require_positive(JWT_EXPIRY_SECONDS, 'JWT_EXPIRY must be a positive number of seconds')

# Debug JWT expiration time (seconds), not set or 0 means not effective
DEBUG_JWT_EXPIRE_SECONDS = int(os.getenv('DEBUG_JWT_EXPIRE_SECONDS', '0') or 0)

# User info query source control: "supabase" or "pg" (default: "supabase" for backward compatibility)
USER_INFO_QUERY_SOURCE = os.getenv('USER_INFO_QUERY_SOURCE', 'supabase').lower()

# Telemetry and Monitoring Configuration (OTLP Protocol)
MONITORING_PROVIDER = os.getenv('MONITORING_PROVIDER', '')
ENABLE_TELEMETRY_RAW = os.getenv('ENABLE_TELEMETRY')
ENABLE_TELEMETRY = (ENABLE_TELEMETRY_RAW or 'false').lower() == 'true'
OTEL_SERVICE_NAME_RAW = os.getenv('OTEL_SERVICE_NAME')
OTEL_SERVICE_NAME = OTEL_SERVICE_NAME_RAW or 'nexent-backend'
OTEL_EXPORTER_OTLP_ENDPOINT_RAW = os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT')
OTEL_EXPORTER_OTLP_ENDPOINT = OTEL_EXPORTER_OTLP_ENDPOINT_RAW or 'http://localhost:4318'
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = os.getenv('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT', '')
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT = os.getenv('OTEL_EXPORTER_OTLP_METRICS_ENDPOINT', '')
OTEL_EXPORTER_OTLP_PROTOCOL_RAW = os.getenv('OTEL_EXPORTER_OTLP_PROTOCOL')
OTEL_EXPORTER_OTLP_PROTOCOL = OTEL_EXPORTER_OTLP_PROTOCOL_RAW or 'http'
OTEL_EXPORTER_OTLP_HEADERS_RAW = os.getenv('OTEL_EXPORTER_OTLP_HEADERS')
OTEL_EXPORTER_OTLP_HEADERS = OTEL_EXPORTER_OTLP_HEADERS_RAW or ''
OTEL_EXPORTER_OTLP_AUTHORIZATION = os.getenv('OTEL_EXPORTER_OTLP_AUTHORIZATION', '')
OTEL_EXPORTER_OTLP_X_API_KEY = os.getenv('OTEL_EXPORTER_OTLP_X_API_KEY', '')
OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION = os.getenv('OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION', '')
LANGSMITH_API_KEY = os.getenv('LANGSMITH_API_KEY', '')
LANGSMITH_PROJECT = os.getenv('LANGSMITH_PROJECT', '')
OTEL_EXPORTER_OTLP_METRICS_ENABLED_RAW = os.getenv('OTEL_EXPORTER_OTLP_METRICS_ENABLED')
OTEL_EXPORTER_OTLP_METRICS_ENABLED = (OTEL_EXPORTER_OTLP_METRICS_ENABLED_RAW or 'true').lower() == 'true'
MONITORING_INSTRUMENT_REQUESTS_RAW = os.getenv('MONITORING_INSTRUMENT_REQUESTS')
MONITORING_INSTRUMENT_REQUESTS = (MONITORING_INSTRUMENT_REQUESTS_RAW or 'false').lower() == 'true'
MONITORING_FASTAPI_INCLUDED_URLS = os.getenv('MONITORING_FASTAPI_INCLUDED_URLS', '')
MONITORING_FASTAPI_EXCLUDED_URLS = os.getenv('MONITORING_FASTAPI_EXCLUDED_URLS', '')
MONITORING_FASTAPI_EXCLUDE_SPANS = os.getenv('MONITORING_FASTAPI_EXCLUDE_SPANS', 'receive,send')

# Explicit empty values disable the respective export filter.
MONITORING_EXCLUDED_ELASTICSEARCH_OPERATIONS = os.getenv('MONITORING_EXCLUDED_ELASTICSEARCH_OPERATIONS', 'search,indices.stats,indices.get_settings,indices.get_alias,bulk,indices.exists,indices.delete')
MONITORING_EXCLUDED_SPAN_NAMES = os.getenv('MONITORING_EXCLUDED_SPAN_NAMES', 'knowledge.process.submit,knowledge.upload.batch')
MONITORING_PROJECT_NAME = os.getenv('MONITORING_PROJECT_NAME', '')
MONITORING_DASHBOARD_URL = os.getenv('MONITORING_DASHBOARD_URL', '')
MONITORING_DASHBOARD_ALLOWED_ROLES = os.getenv('MONITORING_DASHBOARD_ALLOWED_ROLES', 'SU,SPEED')
MONITORING_TRACE_CONTENT_MODE = os.getenv('MONITORING_TRACE_CONTENT_MODE', 'summary')
MONITORING_TRACE_MAX_CHARS = os.getenv('MONITORING_TRACE_MAX_CHARS', '4000')
MONITORING_TRACE_MAX_ITEMS = os.getenv('MONITORING_TRACE_MAX_ITEMS', '20')
TELEMETRY_SAMPLE_RATE_RAW = os.getenv('TELEMETRY_SAMPLE_RATE')
TELEMETRY_SAMPLE_RATE = float(TELEMETRY_SAMPLE_RATE_RAW or '1.0')

# Parse OTLP headers into dict format
OTLP_HEADERS = _build_otlp_headers(OTEL_EXPORTER_OTLP_HEADERS, OTEL_EXPORTER_OTLP_AUTHORIZATION, OTEL_EXPORTER_OTLP_X_API_KEY, LANGSMITH_API_KEY, LANGSMITH_PROJECT, OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION)

# Model Engine Configuration
MODEL_ENGINE_ENABLED = os.getenv('MODEL_ENGINE_ENABLED')

# Container Platform Configuration
IS_DEPLOYED_BY_KUBERNETES = os.getenv('IS_DEPLOYED_BY_KUBERNETES', 'false').lower() == 'true'
KUBERNETES_NAMESPACE = os.getenv('KUBERNETES_NAMESPACE', 'nexent')

# Northbound API public base URL (used for A2A agent cards and external file proxy links)
NORTHBOUND_EXTERNAL_URL = os.getenv('NORTHBOUND_EXTERNAL_URL', 'http://localhost:5013/api').rstrip('/')
APP_VERSION = _resolve_app_version(version_file=os.getenv("APP_VERSION_FILE"))

# =============================================================================
# Agent Sandbox Configuration
# =============================================================================
NEXENT_TOOL_FASTPATH_ENABLED = os.getenv('NEXENT_TOOL_FASTPATH_ENABLED', 'true').strip().lower() == 'true'
NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS = tuple(dict.fromkeys((item.strip() for item in os.getenv('NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS', 'KnowledgeBaseSearchTool,ReadSkillMdTool,ReadSkillConfigTool,AidpSearchTool').split(',') if item.strip())))
NEXENT_SANDBOX_DEFAULT_LEVEL = os.getenv('NEXENT_SANDBOX_DEFAULT_LEVEL', 'local').lower()
# Default sandbox isolation level: local / docker / wasm.
#    Default 'local' preserves backward-compatibility for existing deployments.
NEXENT_SANDBOX_DEFAULT_SCOPE = os.getenv('NEXENT_SANDBOX_DEFAULT_SCOPE', 'system').lower()
# Default sandbox container lifecycle scope: session / system.
#    session  = one container per agent_run, destroyed on run end (strictest isolation).
#    system   = persistent warm pool shared by all runs (lowest cold-start latency).
NEXENT_SANDBOX_DOCKER_IMAGE = os.getenv('NEXENT_SANDBOX_DOCKER_IMAGE', 'nexent/nexent-sandbox:latest')
# Docker image used when level is 'docker'.
NEXENT_SANDBOX_WORKSPACE_VOLUME = os.getenv('NEXENT_SANDBOX_WORKSPACE_VOLUME', 'nexent-agent-workspace')
# Docker named volume shared by the runtime and the system-scoped sandbox.
NEXENT_SANDBOX_MEMORY_LIMIT_MB = int(os.getenv('NEXENT_SANDBOX_MEMORY_LIMIT_MB', '2048'))
NEXENT_SANDBOX_CPU_QUOTA = float(os.getenv('NEXENT_SANDBOX_CPU_QUOTA', '1.0'))
NEXENT_SANDBOX_TIMEOUT_S = int(os.getenv('NEXENT_SANDBOX_TIMEOUT_S', '30'))
_NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_RAW = os.getenv('NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_S', '').strip()
NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_S = float(_NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_RAW) if _NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_RAW and float(_NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_RAW) > 0 else None
# Optional Runtime host-tool bridge timeout. Empty or non-positive disables it.
NEXENT_SANDBOX_NETWORK_DISABLED = os.getenv('NEXENT_SANDBOX_NETWORK', 'disabled').lower() == 'disabled'
NEXENT_SANDBOX_SHELL_POLICY = os.getenv('NEXENT_SANDBOX_SHELL_POLICY', 'disabled').lower()
# Shell execution policy: disabled / restricted / boxed.
#    'disabled' is recommended — blocks subprocess/os shell calls at AST-parse time.
NEXENT_SANDBOX_OUTPUT_BUCKET = os.getenv('NEXENT_SANDBOX_OUTPUT_BUCKET', 'nexent-artifacts')
# MinIO bucket for sandbox output file sync.
NEXENT_SANDBOX_AUTO_SYNC_OUTPUTS = os.getenv('NEXENT_SANDBOX_AUTO_SYNC_OUTPUTS', 'true').lower() == 'true'

# LLM Model Configuration
LLM_INCLUDE_LOGPROBS = os.getenv('LLM_INCLUDE_LOGPROBS', 'false').lower() == 'true'
# When True, adds logprobs=true to every chat.completions.create request body,
# enabling the provider to return log probability information in the response.

# Model Catalog - 预置模型目录配置文件路径
MODEL_CATALOG_JSON_PATH = os.getenv('MODEL_CATALOG_JSON_PATH', str(_CONFIG_DIRECTORY / 'model_catalog.json'))
# Nexent 预置模型目录 (JSON) 文件路径。可通过环境变量覆盖。
MODELS_DEV_CATALOG_JSON_PATH = os.getenv('MODELS_DEV_CATALOG_JSON_PATH', str(_CONFIG_DIRECTORY / 'models_dev_catalog.json'))
# models.dev capability catalog downloaded during the backend image build.

# External Memory Provider Configuration
MEMORY_PROVIDER_PLUGINS_DIR = os.getenv('MEMORY_PROVIDER_PLUGINS_DIR', '')

# Bundled LiteLLM catalog used for model capacity suggestions.
NEXENT_LITELLM_JSON = os.environ.get('NEXENT_LITELLM_JSON', '/opt/nexent/litellm_models.json')

# Exact, operator-verified endpoint/model reasoning transport overrides.
MODEL_RESPONSE_DIAGNOSTIC_CHUNKS = os.getenv('NEXENT_MODEL_DIAGNOSTIC_CHUNKS', os.getenv('NEXENT_PROTOCOL_DIAGNOSTIC_CONTENT', '0')) == '1'
# Read OAuth settings centrally, including provider-specific credential names.
GET_OAUTH_SETTING = os.getenv
