import os
from enum import Enum
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
# Explicitly sourced deployment variables take precedence over a nearby
# developer .env file. This is required for tmux/K8s-local verification and
# avoids silently replacing operator-provided service addresses.
load_dotenv(override=False)

# TODO: Analyze every variable if this is used
# Test voice file path (WAV format for volcengine STT)
TEST_VOICE_PATH = os.path.join(os.path.dirname(
    os.path.dirname(__file__)), 'assets', 'test.wav')
# Test PCM file path (raw PCM format for Ali STT)
TEST_PCM_PATH = os.path.join(os.path.dirname(
    os.path.dirname(__file__)), 'assets', 'test_voice.pcm')


# Vector database providers
class VectorDatabaseType(str, Enum):
    ELASTICSEARCH = "elasticsearch"
    DATAMATE = "datamate"


# Elasticsearch Configuration
ES_HOST = os.getenv("ELASTICSEARCH_HOST")
ES_API_KEY = os.getenv("ELASTICSEARCH_API_KEY")
ES_PASSWORD = os.getenv("ELASTIC_PASSWORD")
ES_USERNAME = "elastic"
ELASTICSEARCH_SERVICE = os.getenv("ELASTICSEARCH_SERVICE")

# Data Processing Service Configuration
DATA_PROCESS_SERVICE = os.getenv("DATA_PROCESS_SERVICE")
RUNTIME_SERVICE_URL = os.getenv("RUNTIME_SERVICE_URL", "http://localhost:5014").rstrip("/")
CLIP_MODEL_PATH = os.getenv("CLIP_MODEL_PATH")
TABLE_TRANSFORMER_MODEL_PATH = os.getenv("TABLE_TRANSFORMER_MODEL_PATH")
UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH = os.getenv(
    "UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH"
)


# Upload Configuration
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
MAX_CONCURRENT_UPLOADS = 5
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')
AGENT_WORKSPACE_ROOT = os.getenv('AGENT_WORKSPACE_ROOT', '/mnt/nexent/workdir')
ROOT_DIR = os.getenv("ROOT_DIR")

PER_WAVE_TIMEOUT = int(os.getenv("DP_SPLIT_WAIT_TIMEOUT_PER_WAVE_S", "30"))
MAX_TIMEOUT = int(os.getenv("DP_SPLIT_WAIT_TIMEOUT_MAX_S", "1800"))

# Agent automation runtime configuration
AGENT_AUTOMATION_ENABLED = os.getenv(
    "AGENT_AUTOMATION_ENABLED", "true"
).lower() in ("true", "1", "yes", "on")
AGENT_AUTOMATION_POLL_INTERVAL_SECONDS = int(
    os.getenv("AGENT_AUTOMATION_POLL_INTERVAL_SECONDS", "5")
)
AGENT_AUTOMATION_MAX_CONCURRENT_RUNS = int(
    os.getenv("AGENT_AUTOMATION_MAX_CONCURRENT_RUNS", "2")
)
AGENT_AUTOMATION_LEASE_SECONDS = int(
    os.getenv("AGENT_AUTOMATION_LEASE_SECONDS", "120")
)
AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS = int(
    os.getenv("AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS", "1800")
)
AGENT_AUTOMATION_SHUTDOWN_GRACE_SECONDS = int(
    os.getenv("AGENT_AUTOMATION_SHUTDOWN_GRACE_SECONDS", "30")
)
AGENT_AUTOMATION_MIN_INTERVAL_SECONDS = int(
    os.getenv("AGENT_AUTOMATION_MIN_INTERVAL_SECONDS", "5")
)


# Container-internal skills storage path
CONTAINER_SKILLS_PATH = os.getenv("SKILLS_PATH")

# Container-internal official skills ZIP directory
OFFICIAL_SKILLS_ZIP_PATH = "/mnt/nexent/official-skills-zip"


# Preview Configuration
FILE_PREVIEW_SIZE_LIMIT = 100 * 1024 * 1024  # 100MB
# Limit concurrent Office-to-PDF conversions
MAX_CONCURRENT_CONVERSIONS = 5
# LibreOffice profile directory
LIBREOFFICE_PROFILE_DIR = os.getenv(
    "LIBREOFFICE_PROFILE_DIR",
    str(Path.home() / ".cache" / "nexent" / "libreoffice-profile"),
)
# Supported Office file MIME types
OFFICE_MIME_TYPES = [
    'application/msword',  # .doc
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
    'application/vnd.ms-excel',  # .xls
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # .xlsx
    'application/vnd.ms-powerpoint',  # .ppt
    'application/vnd.openxmlformats-officedocument.presentationml.presentation'  # .pptx
]


# Supabase Configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
SERVICE_ROLE_KEY = os.getenv('SERVICE_ROLE_KEY', SUPABASE_KEY)
# JWT secret for verifying Supabase-signed access tokens.
# GoTrue uses GOTRUE_JWT_SECRET (= JWT_SECRET in docker setup) to sign tokens.
SUPABASE_JWT_SECRET = os.getenv(
    'SUPABASE_JWT_SECRET') or os.getenv('JWT_SECRET', '')
# Dedicated signing key for opaque independent-AIDP image references. The JWT
# fallback keeps existing deployments functional while allowing key separation.
IND_AIDP_IMAGE_SIGNING_KEY = os.getenv(
    'IND_AIDP_IMAGE_SIGNING_KEY') or SUPABASE_JWT_SECRET


# OAuth Configuration
OAUTH_CALLBACK_BASE_URL = os.getenv("OAUTH_CALLBACK_BASE_URL", "").rstrip("/")
OAUTH_SSL_VERIFY = os.getenv("OAUTH_SSL_VERIFY", "true").lower() == "true"
OAUTH_CA_BUNDLE = os.getenv("OAUTH_CA_BUNDLE", "")
# OAuth login mode:
# - disabled: hide OAuth login entries and disable automatic OAuth redirects.
# - button: show configured OAuth providers as optional login entries.
# - force: automatically redirect when exactly one OAuth provider is configured.
OAUTH_LOGIN_MODE = os.getenv("OAUTH_LOGIN_MODE", "button").lower()


# CAS SSO Configuration
CAS_ENABLED = os.getenv("CAS_ENABLED", "false").lower() in ("true", "1", "yes", "on")
CAS_SERVER_URL = os.getenv("CAS_SERVER_URL", "").rstrip("/")
CAS_VALIDATE_PATH = os.getenv("CAS_VALIDATE_PATH", "/p3/serviceValidate")
CAS_CALLBACK_BASE_URL = os.getenv("CAS_CALLBACK_BASE_URL", OAUTH_CALLBACK_BASE_URL).rstrip("/")
# CAS login mode:
# - disabled: disable CAS login entry and automatic CAS redirects.
# - button: show CAS as an optional login entry.
# - force: automatically redirect unauthenticated users to CAS login.
CAS_LOGIN_MODE = os.getenv("CAS_LOGIN_MODE", "disabled").lower()
CAS_USER_ATTRIBUTE = os.getenv("CAS_USER_ATTRIBUTE", "")
CAS_EMAIL_ATTRIBUTE = os.getenv("CAS_EMAIL_ATTRIBUTE", "email")
CAS_ROLE_ATTRIBUTE = os.getenv("CAS_ROLE_ATTRIBUTE", "role")
CAS_DEFAULT_ROLE = os.getenv("CAS_DEFAULT_ROLE", "USER").strip().upper()
CAS_TENANT_ATTRIBUTE = os.getenv("CAS_TENANT_ATTRIBUTE", "tenant_id")
CAS_DEFAULT_TENANT_ID = os.getenv("CAS_DEFAULT_TENANT_ID", "tenant_id")
CAS_ROLE_MAP_JSON = os.getenv("CAS_ROLE_MAP_JSON", "")
CAS_SESSION_MAX_AGE_SECONDS = int(os.getenv("CAS_SESSION_MAX_AGE_SECONDS", "3600") or 3600)
LOCAL_SESSION_MAX_AGE_SECONDS = int(os.getenv("LOCAL_SESSION_MAX_AGE_SECONDS", "3600") or 3600)
CAS_HEARTBEAT_URL = os.getenv("CAS_HEARTBEAT_URL", "").strip()
CAS_HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("CAS_HEARTBEAT_INTERVAL_SECONDS", "300") or 300)
CAS_HEARTBEAT_COOKIE_NAME = os.getenv("CAS_HEARTBEAT_COOKIE_NAME", "").strip()
CAS_RENEW_BEFORE_SECONDS = int(os.getenv("CAS_RENEW_BEFORE_SECONDS", "300") or 300)
CAS_RENEW_TIMEOUT_SECONDS = int(os.getenv("CAS_RENEW_TIMEOUT_SECONDS", "10") or 10)
CAS_SYNTHETIC_EMAIL_DOMAIN = os.getenv("CAS_SYNTHETIC_EMAIL_DOMAIN", "")
CAS_LOGOUT_URL = os.getenv("CAS_LOGOUT_URL", "")
CAS_SSL_VERIFY = os.getenv("CAS_SSL_VERIFY", "true").lower() == "true"
CAS_CA_BUNDLE = os.getenv("CAS_CA_BUNDLE", "")


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
IMAGE_FILTER = os.getenv("IMAGE_FILTER", "false").lower() == "true"


# Default User and Tenant IDs
DEFAULT_USER_ID = "user_id"
DEFAULT_TENANT_ID = "tenant_id"

# Tenant resource hard limits. These values are intentionally not configurable.
MAX_TENANT_COUNT = 100
MAX_USERS_PER_TENANT = 10_000
MAX_GROUPS_PER_TENANT = 1_000
MAX_SUPER_ADMIN_COUNT = 1
MAX_ADMINS_PER_TENANT = 1_000

# Invitation code type for asset administrator registration
ASSET_OWNER_INVITE_CODE_TYPE = "ASSET_OWNER_INVITE"

# User role identifier for asset administrators
ASSET_OWNER_ROLE = "ASSET_OWNER"

# Tenant ID for asset administrators (virtual tenant, not a real tenant)
ASSET_OWNER_TENANT_ID = "asset_owner_tenant_id"

# MinIO prefix for ASSET_OWNER-scoped attachment uploads (attachments/asset_owner/{user_id}/...)
ASSET_OWNER_ATTACHMENTS_PREFIX = "attachments/asset_owner"

# When false, block ASSET_OWNER invites, registrations, and sign-in.
ENABLE_ASSET_OWNER_ROLE = os.getenv(
    "ENABLE_ASSET_OWNER_ROLE", "false").lower() == "true"

# HTTP detail key: asset owner must register via OAuth, not email/password signup.
ASSET_OWNER_SIGNUP_USE_OAUTH_DETAIL = "ASSET_OWNER_USE_OAUTH"

# Roles that can edit all resources within a tenant (permission = EDIT).
# Keep this centralized to avoid drifting role logic across modules.
CAN_EDIT_ALL_USER_ROLES = {"SU", "ADMIN", "SPEED", "ASSET_OWNER"}

# Permission constants used by list endpoints (e.g., /agent/list, /mcp/list).
PERMISSION_READ = "READ_ONLY"
PERMISSION_EDIT = "EDIT"
PERMISSION_PRIVATE = "PRIVATE"

# Response flag when system prompts are withheld from non-ASSET_OWNER callers.
AGENT_PROMPTS_HIDDEN_FLAG = "prompts_hidden"

# W11 capacity suggestion rollout flags.
CAPACITY_SUGGESTION_ENABLED = os.getenv(
    "CAPACITY_SUGGESTION_ENABLED", "true").lower() in ("true", "1", "yes", "on")
CAPACITY_VISIBILITY_ENABLED = os.getenv(
    "CAPACITY_VISIBILITY_ENABLED", "true").lower() in ("true", "1", "yes", "on")


# Deployment Version Configuration
DEPLOYMENT_VERSION = os.getenv("DEPLOYMENT_VERSION", "speed")
IS_SPEED_MODE = DEPLOYMENT_VERSION == "speed"

# AIDP Knowledge Base configuration
ENABLE_AIDP_KNOWLEDGE = os.getenv("ENABLE_AIDP_KNOWLEDGE", "false").lower() in ("true", "1", "yes", "on")
AIDP_SERVER_URL = os.getenv("AIDP_SERVER_URL", "")
AIDP_API_KEY = os.getenv("AIDP_API_KEY", "")
AIDP_TENANT_ID = os.getenv("AIDP_TENANT_ID", "aidp")
# Minio Configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_REGION = os.getenv("MINIO_REGION")
MINIO_DEFAULT_BUCKET = os.getenv("MINIO_DEFAULT_BUCKET")
MINIO_SECURE = os.getenv("MINIO_SECURE", "true").lower() == "true"
S3_URL_PREFIX = "s3://"


# Postgres Configuration
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_USER = os.getenv("POSTGRES_USER")
NEXENT_POSTGRES_PASSWORD = os.getenv("NEXENT_POSTGRES_PASSWORD")
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")


# Data Processing Service Configuration
REDIS_URL = os.getenv("REDIS_URL")
REDIS_BACKEND_URL = os.getenv("REDIS_BACKEND_URL")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
RUNTIME_STATE_REDIS_URL = os.getenv("RUNTIME_STATE_REDIS_URL") or REDIS_URL
RUNTIME_STREAM_TTL_SECONDS = int(os.getenv("RUNTIME_STREAM_TTL_SECONDS", "86400"))
RUNTIME_STREAM_MAX_LEN = int(os.getenv("RUNTIME_STREAM_MAX_LEN", "10000"))
RUNTIME_STREAM_LOCAL_REPLAY_MAX_BYTES = int(
    os.getenv("RUNTIME_STREAM_LOCAL_REPLAY_MAX_BYTES", str(8 * 1024 * 1024))
)
RUNTIME_RUN_TTL_SECONDS = int(os.getenv("RUNTIME_RUN_TTL_SECONDS", "86400"))
RUNTIME_CANCEL_TTL_SECONDS = int(os.getenv("RUNTIME_CANCEL_TTL_SECONDS", "86400"))
RUNTIME_COMPLETED_TTL_SECONDS = int(os.getenv("RUNTIME_COMPLETED_TTL_SECONDS", "300"))
RUNTIME_CANCEL_POLL_INTERVAL_SECONDS = float(os.getenv("RUNTIME_CANCEL_POLL_INTERVAL_SECONDS", "1.0"))
NORTHBOUND_IDEMPOTENCY_TTL_SECONDS = int(os.getenv("NORTHBOUND_IDEMPOTENCY_TTL_SECONDS", "600"))
NORTHBOUND_RATE_LIMIT_ENABLED = os.getenv("NORTHBOUND_RATE_LIMIT_ENABLED", "true").lower() == "true"
NORTHBOUND_RATE_LIMIT_PER_MINUTE = int(os.getenv("NORTHBOUND_RATE_LIMIT_PER_MINUTE", "120"))
FLOWER_PORT = int(os.getenv("FLOWER_PORT", "5555"))
DP_REDIS_CHUNKS_WAIT_TIMEOUT_S = int(os.getenv("DP_REDIS_CHUNKS_WAIT_TIMEOUT_S", "300"))
DP_REDIS_CHUNKS_POLL_INTERVAL_MS = int(os.getenv("DP_REDIS_CHUNKS_POLL_INTERVAL_MS", "200"))
REDIS_ERROR_INFO_TTL_SECONDS = int(os.getenv("REDIS_ERROR_INFO_TTL_SECONDS", str(1 * 24 * 60 * 60)))
REDIS_ERROR_INFO_SCAN_COUNT = int(os.getenv("REDIS_ERROR_INFO_SCAN_COUNT", "500"))
FORWARD_REDIS_RETRY_DELAY_S = int(os.getenv("FORWARD_REDIS_RETRY_DELAY_S", "5"))
FORWARD_REDIS_RETRY_MAX = int(os.getenv("FORWARD_REDIS_RETRY_MAX", "12"))


# Ray Configuration
DP_PART_PROCESSOR_COUNT = int(os.getenv("DP_PART_PROCESSOR_COUNT", "3"))
DP_FILE_SPLIT_SIZE_MB = int(os.getenv("DP_FILE_SPLIT_SIZE_MB", "5"))
RAY_ACTOR_NUM_CPUS = int(os.getenv("RAY_ACTOR_NUM_CPUS", "2"))
RAY_DASHBOARD_PORT = int(os.getenv("RAY_DASHBOARD_PORT", "8265"))
RAY_DASHBOARD_HOST = os.getenv("RAY_DASHBOARD_HOST", "0.0.0.0")
RAY_NUM_CPUS = DP_PART_PROCESSOR_COUNT * RAY_ACTOR_NUM_CPUS
RAY_OBJECT_STORE_MEMORY_GB = float(os.getenv("RAY_OBJECT_STORE_MEMORY_GB", "0.25"))
RAY_TEMP_DIR = os.getenv("RAY_TEMP_DIR", "/tmp/ray")
RAY_LOG_LEVEL = os.getenv("RAY_LOG_LEVEL", "INFO").upper()
# Disable plasma preallocation to reduce idle memory usage
# When set to false, Ray will allocate object store memory on-demand instead of preallocating
RAY_preallocate_plasma = os.getenv("RAY_preallocate_plasma", "false").lower() == "true"


# Service Control Flags
DISABLE_RAY_DASHBOARD = os.getenv(
    "DISABLE_RAY_DASHBOARD", "false").lower() == "true"
DISABLE_CELERY_FLOWER = os.getenv(
    "DISABLE_CELERY_FLOWER", "false").lower() == "true"
DOCKER_ENVIRONMENT = os.getenv("DOCKER_ENVIRONMENT", "false").lower() == "true"
NEXENT_MCP_DOCKER_IMAGE = os.getenv(
    "NEXENT_MCP_DOCKER_IMAGE", "nexent/nexent-mcp:latest")
ENABLE_UPLOAD_IMAGE = os.getenv(
    "ENABLE_UPLOAD_IMAGE", "false").lower() == "true"
ENABLE_JIUWEN_SDK = os.getenv("NEXENT_ENABLE_JIUWEN_SDK", "true").lower() == "true"


# Celery Configuration
CELERY_WORKER_PREFETCH_MULTIPLIER = int(
    os.getenv("CELERY_WORKER_PREFETCH_MULTIPLIER", "1"))
CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "3600"))
ELASTICSEARCH_REQUEST_TIMEOUT = int(
    os.getenv("ELASTICSEARCH_REQUEST_TIMEOUT", "30"))


# Worker Configuration
RAY_ADDRESS = os.getenv("RAY_ADDRESS", "auto")
QUEUES = os.getenv(
    "QUEUES",
    "process_q,process_part_q,forward_q,forward_part_q,forward_aggregate_q",
)
# Will be dynamically set based on PID if not provided
WORKER_NAME = os.getenv("WORKER_NAME")
# The data-process service sets a queue-specific value for each child worker.
# Keep the historical default when the variable is not provided.
WORKER_CONCURRENCY = int(
    os.getenv("WORKER_CONCURRENCY", str(DP_PART_PROCESSOR_COUNT + 1))
)
RAY_WARM_ACTOR_POOL_SIZE_PART = int(
    os.getenv("RAY_WARM_ACTOR_POOL_SIZE_PART", "2"))
RAY_WARM_ACTOR_POOL_SIZE_PROCESS = int(
    os.getenv("RAY_WARM_ACTOR_POOL_SIZE_PROCESS", "1"))
RAY_ACTOR_WARM_TIMEOUT_S = float(os.getenv("RAY_ACTOR_WARM_TIMEOUT_S", "60"))
RAY_GLOBAL_ACTOR_POOL_NAME = os.getenv(
    "RAY_GLOBAL_ACTOR_POOL_NAME", "nexent_global_data_processor_pool")
RAY_GLOBAL_ACTOR_POOL_NAMESPACE = os.getenv(
    "RAY_GLOBAL_ACTOR_POOL_NAMESPACE", "nexent-data-process")


# Voice Service Configuration
APPID = os.getenv("APPID", "")
TOKEN = os.getenv("TOKEN", "")
CLUSTER = os.getenv("CLUSTER", "volcano_tts")
VOICE_TYPE = os.getenv("VOICE_TYPE", "zh_male_jieshuonansheng_mars_bigtts")
SPEED_RATIO = float(os.getenv("SPEED_RATIO", "1.3"))


# Memory Feature
MEMORY_SWITCH_KEY = "MEMORY_SWITCH"
DREAMING_SWITCH_KEY = "DREAMING_SWITCH"
MEMORY_AGENT_SHARE_KEY = "MEMORY_AGENT_SHARE"
DISABLE_AGENT_ID_KEY = "DISABLE_AGENT_ID"
DISABLE_USERAGENT_ID_KEY = "DISABLE_USERAGENT_ID"
DEFAULT_MEMORY_SWITCH_KEY = "Y"
DEFAULT_DREAMING_SWITCH_KEY = "Y"
DEFAULT_MEMORY_AGENT_SHARE_KEY = "always"
# Boolean value representations for configuration parsing
BOOLEAN_TRUE_VALUES = {"true", "1", "y", "yes", "on"}

# ===== Memory System =====

# MMR (Maximal Marginal Relevance) configuration
MMR_LAMBDA = float(os.getenv("MMR_LAMBDA", "0.7"))
MMR_CANDIDATE_TOP_K = int(os.getenv("MMR_CANDIDATE_TOP_K", "10"))
MMR_FINAL_TOP_K = int(os.getenv("MMR_FINAL_TOP_K", "5"))
MMR_DUPLICATE_THRESHOLD = float(os.getenv("MMR_DUPLICATE_THRESHOLD", "0.92"))

# Temporal decay (only applied to internal agent short-term memory)
AGENT_SHORT_TERM_HALF_LIFE_DAYS = int(
    os.getenv("AGENT_SHORT_TERM_HALF_LIFE_DAYS", "14")
)

# Score fusion source weights
W_AGENT_SHORT_TERM = float(os.getenv("W_AGENT_SHORT_TERM", "1.0"))
W_EXTERNAL = float(os.getenv("W_EXTERNAL", "0.8"))

# Token budget selection
MEMORY_TOKEN_BUDGET = int(os.getenv("MEMORY_TOKEN_BUDGET", "2000"))

# Dreaming promotion thresholds
LIGHT_SLEEP_WINDOW_DAYS = int(os.getenv("LIGHT_SLEEP_WINDOW_DAYS", "7"))
RECENCY_HALF_LIFE_DAYS = int(os.getenv("RECENCY_HALF_LIFE_DAYS", "14"))
MIN_PROMOTION_SCORE = float(os.getenv("MIN_PROMOTION_SCORE", "0.75"))
MIN_RECALL_COUNT = int(os.getenv("MIN_RECALL_COUNT", "3"))
MIN_UNIQUE_QUERIES = int(os.getenv("MIN_UNIQUE_QUERIES", "3"))
DREAMING_SOURCE_LIMIT = int(os.getenv("DREAMING_SOURCE_LIMIT", "10"))
DREAMING_LONG_TERM_MAX_CHARS = int(
    os.getenv("DREAMING_LONG_TERM_MAX_CHARS", "10000")
)
DREAMING_SUMMARIZATION_MAX_ATTEMPTS = int(
    os.getenv("DREAMING_SUMMARIZATION_MAX_ATTEMPTS", "2")
)
DREAMING_SCHEDULER_POLL_SECONDS = float(os.getenv("DREAMING_SCHEDULER_POLL_SECONDS", "5.0"))
DREAMING_SCHEDULER_LEASE_SECONDS = float(os.getenv("DREAMING_SCHEDULER_LEASE_SECONDS", "120.0"))
DREAMING_SCHEDULER_MAX_CONCURRENCY = int(os.getenv("DREAMING_SCHEDULER_MAX_CONCURRENCY", "1"))
DREAMING_SCHEDULER_ENABLED = os.getenv("DREAMING_SCHEDULER_ENABLED", "true").lower() in ("true", "1", "yes")
DREAMING_MAX_AGE_DAYS = int(os.getenv("DREAMING_MAX_AGE_DAYS", "30"))
DREAMING_SUMMARIZATION_BACKOFF_BASE_SECONDS = float(os.getenv("DREAMING_SUMMARIZATION_BACKOFF_BASE_SECONDS", "1.0"))

# External provider retry / timeout
PROVIDER_RETRY_MAX_ATTEMPTS = int(os.getenv("PROVIDER_RETRY_MAX_ATTEMPTS", "3"))
PROVIDER_RETRY_BACKOFF_BASE_SECONDS = int(
    os.getenv("PROVIDER_RETRY_BACKOFF_BASE_SECONDS", "1")
)
PROVIDER_REQUEST_TIMEOUT_SECONDS = int(
    os.getenv("PROVIDER_REQUEST_TIMEOUT_SECONDS", "30")
)

# External provider toggles (configured per provider elsewhere; these constants
# describe protocol-level defaults)
EXTERNAL_MEMORY_DEFAULT_ALLOWED_UNIT_TYPES = (
    "model_output",
    "model_output_thinking",
    "model_output_deep_thinking",
    "model_output_code",
    "final_answer",
    "error",
    "search_content",
    "tool",
    "parse",
    "execution_logs",
    "picture_web",
    "memory_search",
    "verification",
    "max_steps_reached",
)


DEFAULT_LLM_MAX_TOKENS = 4096


# Embedding Model Chunk Size Defaults
DEFAULT_EXPECTED_CHUNK_SIZE = 1024
DEFAULT_MAXIMUM_CHUNK_SIZE = 1536


# MCP Server
LOCAL_MCP_SERVER = os.getenv("NEXENT_MCP_SERVER")
MCP_MANAGEMENT_API = os.getenv("MCP_MANAGEMENT_API", "http://localhost:5015")


# Invite code
INVITE_CODE = os.getenv("INVITE_CODE")

# Access-token lifetime in seconds. This must match GoTrue's GOTRUE_JWT_EXP.
JWT_EXPIRY_SECONDS = int(os.getenv("JWT_EXPIRY", "7200") or 7200)
if JWT_EXPIRY_SECONDS <= 0:
    raise ValueError("JWT_EXPIRY must be a positive number of seconds")

# Debug JWT expiration time (seconds), not set or 0 means not effective
DEBUG_JWT_EXPIRE_SECONDS = int(os.getenv('DEBUG_JWT_EXPIRE_SECONDS', '0') or 0)

# User info query source control: "supabase" or "pg" (default: "supabase" for backward compatibility)
USER_INFO_QUERY_SOURCE = os.getenv(
    'USER_INFO_QUERY_SOURCE', 'supabase').lower()

# Memory Search Status Messages (for i18n placeholders)
MEMORY_SEARCH_START_MSG = "<MEM_START>"
MEMORY_SEARCH_DONE_MSG = "<MEM_DONE>"
MEMORY_SEARCH_FAIL_MSG = "<MEM_FAILED>"

# Tool Type Mapping (for display normalization)
TOOL_TYPE_MAPPING = {
    "mcp": "MCP",
    "langchain": "LangChain",
    "local": "Local",
}

# Default Language Configuration
LANGUAGE = {
    "ZH": "zh",
    "EN": "en"
}

# Message Role Constants
MESSAGE_ROLE = {
    "USER": "user",
    "ASSISTANT": "assistant",
    "SYSTEM": "system"
}

# Knowledge summary max token limits
KNOWLEDGE_SUMMARY_MAX_TOKENS_ZH = 300
KNOWLEDGE_SUMMARY_MAX_TOKENS_EN = 120

# Host Configuration Constants
LOCALHOST_IP = "127.0.0.1"
LOCALHOST_NAME = "localhost"
DOCKER_INTERNAL_HOST = "host.docker.internal"


# Mock User Management Configuration (for speed mode)
MOCK_USER = {
    "id": DEFAULT_USER_ID,
    "email": "mock@example.com",
    "role": "admin"
}

MOCK_SESSION = {
    "access_token": "mock_access_token",
    "refresh_token": "mock_refresh_token",
    "expires_at": None,  # Will be set dynamically
    "expires_in_seconds": 315360000  # 10 years
}

MODEL_CONFIG_MAPPING = {
    "llm": "LLM_ID",
    "embedding": "EMBEDDING_ID",
    "multiEmbedding": "MULTI_EMBEDDING_ID",
    "rerank": "RERANK_ID",
    "vlm": "VLM_ID",
    "vlm2": "VLM2_ID",
    "vlm3": "VLM3_ID",
    "vlm4": "VLM4_ID",
    "stt": "STT_ID",
    "tts": "TTS_ID"
}

ICON_TYPE = "ICON_TYPE"
ICON_KEY = "ICON_KEY"
AVATAR_URI = "AVATAR_URI"
CUSTOM_ICON_URL = "CUSTOM_ICON_URL"
TENANT_NAME = "TENANT_NAME"
TENANT_ID = "TENANT_ID"
DEFAULT_GROUP_ID = "DEFAULT_GROUP_ID"
DATAMATE_URL = "DATAMATE_URL"

# Task Status Constants
TASK_STATUS = {
    "WAIT_FOR_PROCESSING": "WAIT_FOR_PROCESSING",
    "WAIT_FOR_FORWARDING": "WAIT_FOR_FORWARDING",
    "PROCESSING": "PROCESSING",
    "FORWARDING": "FORWARDING",
    "COMPLETED": "COMPLETED",
    "PROCESS_FAILED": "PROCESS_FAILED",
    "FORWARD_FAILED": "FORWARD_FAILED",
}

# Deep Thinking Constants
THINK_START_PATTERN = "<think>"
THINK_END_PATTERN = "</think>"


# Telemetry and Monitoring Configuration (OTLP Protocol)
MONITORING_PROVIDER = os.getenv("MONITORING_PROVIDER", "")
ENABLE_TELEMETRY_RAW = os.getenv("ENABLE_TELEMETRY")
ENABLE_TELEMETRY = (ENABLE_TELEMETRY_RAW or "false").lower() == "true"
OTEL_SERVICE_NAME_RAW = os.getenv("OTEL_SERVICE_NAME")
OTEL_SERVICE_NAME = OTEL_SERVICE_NAME_RAW or "nexent-backend"
OTEL_EXPORTER_OTLP_ENDPOINT_RAW = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
OTEL_EXPORTER_OTLP_ENDPOINT = OTEL_EXPORTER_OTLP_ENDPOINT_RAW or "http://localhost:4318"
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = os.getenv(
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT = os.getenv(
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "")
OTEL_EXPORTER_OTLP_PROTOCOL_RAW = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL")
OTEL_EXPORTER_OTLP_PROTOCOL = OTEL_EXPORTER_OTLP_PROTOCOL_RAW or "http"
OTEL_EXPORTER_OTLP_HEADERS_RAW = os.getenv("OTEL_EXPORTER_OTLP_HEADERS")
OTEL_EXPORTER_OTLP_HEADERS = OTEL_EXPORTER_OTLP_HEADERS_RAW or ""
OTEL_EXPORTER_OTLP_AUTHORIZATION = os.getenv(
    "OTEL_EXPORTER_OTLP_AUTHORIZATION", "")
OTEL_EXPORTER_OTLP_X_API_KEY = os.getenv("OTEL_EXPORTER_OTLP_X_API_KEY", "")
OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION = os.getenv(
    "OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION", "")
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "")
OTEL_EXPORTER_OTLP_METRICS_ENABLED_RAW = os.getenv(
    "OTEL_EXPORTER_OTLP_METRICS_ENABLED")
OTEL_EXPORTER_OTLP_METRICS_ENABLED = (
    OTEL_EXPORTER_OTLP_METRICS_ENABLED_RAW or "true").lower() == "true"
MONITORING_INSTRUMENT_REQUESTS_RAW = os.getenv(
    "MONITORING_INSTRUMENT_REQUESTS")
MONITORING_INSTRUMENT_REQUESTS = (
    MONITORING_INSTRUMENT_REQUESTS_RAW or "false").lower() == "true"
MONITORING_FASTAPI_INCLUDED_URLS = os.getenv(
    "MONITORING_FASTAPI_INCLUDED_URLS", "")
MONITORING_FASTAPI_EXCLUDED_URLS = os.getenv(
    "MONITORING_FASTAPI_EXCLUDED_URLS", "")
MONITORING_FASTAPI_EXCLUDE_SPANS = os.getenv(
    "MONITORING_FASTAPI_EXCLUDE_SPANS", "receive,send")
MONITORING_PROJECT_NAME = os.getenv("MONITORING_PROJECT_NAME", "")
MONITORING_DASHBOARD_URL = os.getenv("MONITORING_DASHBOARD_URL", "")
MONITORING_TRACE_CONTENT_MODE = os.getenv(
    "MONITORING_TRACE_CONTENT_MODE", "summary")
MONITORING_TRACE_MAX_CHARS = os.getenv("MONITORING_TRACE_MAX_CHARS", "4000")
MONITORING_TRACE_MAX_ITEMS = os.getenv("MONITORING_TRACE_MAX_ITEMS", "20")
TELEMETRY_SAMPLE_RATE_RAW = os.getenv("TELEMETRY_SAMPLE_RATE")
TELEMETRY_SAMPLE_RATE = float(TELEMETRY_SAMPLE_RATE_RAW or "1.0")

# Parse OTLP headers into dict format


def _parse_otlp_headers(headers_str: str) -> dict:
    """Parse OTLP headers string into dict. Format: 'key1=value1,key2=value2'"""
    if not headers_str:
        return {}
    headers = {}
    for pair in headers_str.split(","):
        if "=" in pair:
            key, value = pair.split("=", 1)
            headers[key.strip()] = value.strip()
    return headers


OTLP_HEADERS = _parse_otlp_headers(OTEL_EXPORTER_OTLP_HEADERS)
if OTEL_EXPORTER_OTLP_AUTHORIZATION:
    OTLP_HEADERS["Authorization"] = OTEL_EXPORTER_OTLP_AUTHORIZATION
if OTEL_EXPORTER_OTLP_X_API_KEY:
    OTLP_HEADERS["x-api-key"] = OTEL_EXPORTER_OTLP_X_API_KEY
elif LANGSMITH_API_KEY:
    OTLP_HEADERS["x-api-key"] = LANGSMITH_API_KEY
if LANGSMITH_PROJECT:
    OTLP_HEADERS["Langsmith-Project"] = LANGSMITH_PROJECT
if OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION:
    OTLP_HEADERS["x-langfuse-ingestion-version"] = OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION


DEFAULT_ZH_TITLE = "新对话"
DEFAULT_EN_TITLE = "New Conversation"


# Model Engine Configuration
MODEL_ENGINE_ENABLED = os.getenv("MODEL_ENGINE_ENABLED")


# Container Platform Configuration
IS_DEPLOYED_BY_KUBERNETES = os.getenv(
    "IS_DEPLOYED_BY_KUBERNETES", "false").lower() == "true"
KUBERNETES_NAMESPACE = os.getenv("KUBERNETES_NAMESPACE", "nexent")

# Northbound API public base URL (used for A2A agent cards and external file proxy links)
NORTHBOUND_EXTERNAL_URL = os.getenv(
    "NORTHBOUND_EXTERNAL_URL", "http://localhost:5013/api").rstrip("/")


def _collect_version_candidates():
    """Build the ordered list of candidate paths to read ``APP_VERSION`` from.

    The order is: env override (test/script hook), the container image path,
    and finally the local repository root. Exposed as a separate function so
    tests can drive the resolver deterministically without monkey-patching
    ``pathlib.Path`` globally.
    """
    candidates = []
    override = os.getenv("APP_VERSION_FILE")
    if override:
        candidates.append(Path(override))
    candidates.append(Path("/opt/nexent/VERSION"))
    # backend/consts/const.py -> backend/consts -> backend -> <repo-root>
    candidates.append(Path(__file__).resolve().parents[2] / "VERSION")
    return candidates


def _read_version_from(candidate):
    """Return the parsed version string from ``candidate`` or ``None``.

    Reads only the first non-blank line and strips surrounding whitespace.
    Returns ``None`` if the file is missing, unreadable, or its first line
    is empty after trimming.
    """
    try:
        if not candidate.is_file():
            return None
        first_line = candidate.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if not first_line:
        return None
    version = first_line[0].strip()
    return version or None


def _resolve_app_version(default: str = "v2.2.1") -> str:
    """Read the semantic app version from the VERSION file.

    Search order:
      1. Explicit ``APP_VERSION_FILE`` environment override (test/script hook).
      2. Container path ``/opt/nexent/VERSION`` (set by the runtime Dockerfile).
      3. ``<repo-root>/VERSION`` for local development, where ``<repo-root>`` is
         derived from this file's location (backend/consts -> repo root).
      4. Hardcoded default as a last resort.
    """
    for candidate in _collect_version_candidates():
        version = _read_version_from(candidate)
        if version is not None:
            return version
    return default


APP_VERSION = _resolve_app_version()


# =============================================================================
# Agent Sandbox Configuration
# =============================================================================

NEXENT_SANDBOX_DEFAULT_LEVEL = os.getenv("NEXENT_SANDBOX_DEFAULT_LEVEL", "local").lower()
"""Default sandbox isolation level: local / docker / wasm.
   Default 'local' preserves backward-compatibility for existing deployments."""

NEXENT_SANDBOX_DEFAULT_SCOPE = os.getenv("NEXENT_SANDBOX_DEFAULT_SCOPE", "system").lower()
"""Default sandbox container lifecycle scope: session / system.
   session  = one container per agent_run, destroyed on run end (strictest isolation).
   system   = persistent warm pool shared by all runs (lowest cold-start latency)."""

NEXENT_SANDBOX_DOCKER_IMAGE = os.getenv(
    "NEXENT_SANDBOX_DOCKER_IMAGE", "nexent/nexent-sandbox:latest"
)
"""Docker image used when level is 'docker'."""

NEXENT_SANDBOX_WORKSPACE_VOLUME = os.getenv(
    "NEXENT_SANDBOX_WORKSPACE_VOLUME", "nexent-agent-workspace"
)
"""Docker named volume shared by the runtime and the system-scoped sandbox."""

NEXENT_SANDBOX_MEMORY_LIMIT_MB = int(os.getenv("NEXENT_SANDBOX_MEMORY_LIMIT_MB", "2048"))

NEXENT_SANDBOX_CPU_QUOTA = float(os.getenv("NEXENT_SANDBOX_CPU_QUOTA", "1.0"))

NEXENT_SANDBOX_TIMEOUT_S = int(os.getenv("NEXENT_SANDBOX_TIMEOUT_S", "30"))

_NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_RAW = os.getenv(
    "NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_S", ""
).strip()
NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_S = (
    float(_NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_RAW)
    if _NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_RAW
    and float(_NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_RAW) > 0
    else None
)
"""Optional Runtime host-tool bridge timeout. Empty or non-positive disables it."""

NEXENT_SANDBOX_NETWORK_DISABLED = (
    os.getenv("NEXENT_SANDBOX_NETWORK", "disabled").lower() == "disabled"
)

NEXENT_SANDBOX_SHELL_POLICY = os.getenv(
    "NEXENT_SANDBOX_SHELL_POLICY", "disabled"
).lower()
"""Shell execution policy: disabled / restricted / boxed.
   'disabled' is recommended — blocks subprocess/os shell calls at AST-parse time."""

NEXENT_SANDBOX_OUTPUT_BUCKET = os.getenv(
    "NEXENT_SANDBOX_OUTPUT_BUCKET", "nexent-artifacts"
)
"""MinIO bucket for sandbox output file sync."""

NEXENT_SANDBOX_AUTO_SYNC_OUTPUTS = (
    os.getenv("NEXENT_SANDBOX_AUTO_SYNC_OUTPUTS", "true").lower() == "true"
)


# Skill Creation Streaming Configuration
STREAMABLE_CONTENT_TYPES = frozenset([
    "model_output_thinking",
    "model_output_code",
    "model_output_deep_thinking",
    "tool",
    "execution_logs",
])

# LLM Model Configuration
LLM_INCLUDE_LOGPROBS = os.getenv("LLM_INCLUDE_LOGPROBS", "false").lower() == "true"
"""When True, adds logprobs=true to every chat.completions.create request body,
enabling the provider to return log probability information in the response."""

# SSE streaming event type for status messages
STREAM_STATUS_EVENT = "event: stream_status\n"
