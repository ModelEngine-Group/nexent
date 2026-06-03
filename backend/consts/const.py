import os
from enum import Enum
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

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
CLIP_MODEL_PATH = os.getenv("CLIP_MODEL_PATH")
TABLE_TRANSFORMER_MODEL_PATH = os.getenv("TABLE_TRANSFORMER_MODEL_PATH")
UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH = os.getenv(
    "UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH"
)


# Upload Configuration
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
MAX_CONCURRENT_UPLOADS = 5
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')
ROOT_DIR = os.getenv("ROOT_DIR")

PER_WAVE_TIMEOUT = int(os.getenv("DP_SPLIT_WAIT_TIMEOUT_PER_WAVE_S", "30"))
MAX_TIMEOUT = int(os.getenv("DP_SPLIT_WAIT_TIMEOUT_MAX_S", "1800"))


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


# OAuth Configuration
OAUTH_CALLBACK_BASE_URL = os.getenv("OAUTH_CALLBACK_BASE_URL", "")
OAUTH_SSL_VERIFY = os.getenv("OAUTH_SSL_VERIFY", "true").lower() == "true"
OAUTH_CA_BUNDLE = os.getenv("OAUTH_CA_BUNDLE", "")


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


# Deployment Version Configuration
DEPLOYMENT_VERSION = os.getenv("DEPLOYMENT_VERSION", "speed")
IS_SPEED_MODE = DEPLOYMENT_VERSION == "speed"
DEFAULT_APP_DESCRIPTION_ZH = "Nexent 是一个开源智能体平台，基于 MCP 工具生态系统，提供灵活的多模态问答、检索、数据分析、处理等能力。"
DEFAULT_APP_DESCRIPTION_EN = "Nexent is an open-source agent platform built on the MCP tool ecosystem, providing flexible multi-modal Q&A, retrieval, data analysis, and processing capabilities."
DEFAULT_APP_NAME_ZH = "Nexent 智能体"
DEFAULT_APP_NAME_EN = "Nexent Agent"

# Minio Configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_REGION = os.getenv("MINIO_REGION")
MINIO_DEFAULT_BUCKET = os.getenv("MINIO_DEFAULT_BUCKET")
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
FLOWER_PORT = int(os.getenv("FLOWER_PORT", "5555"))
DP_REDIS_CHUNKS_WAIT_TIMEOUT_S = int(
    os.getenv("DP_REDIS_CHUNKS_WAIT_TIMEOUT_S", "30"))
DP_REDIS_CHUNKS_POLL_INTERVAL_MS = int(
    os.getenv("DP_REDIS_CHUNKS_POLL_INTERVAL_MS", "200"))
FORWARD_REDIS_RETRY_DELAY_S = int(
    os.getenv("FORWARD_REDIS_RETRY_DELAY_S", "5"))
FORWARD_REDIS_RETRY_MAX = int(os.getenv("FORWARD_REDIS_RETRY_MAX", "12"))


# Ray Configuration
RAY_ACTOR_NUM_CPUS = int(os.getenv("RAY_ACTOR_NUM_CPUS", "2"))
RAY_DASHBOARD_PORT = int(os.getenv("RAY_DASHBOARD_PORT", "8265"))
RAY_DASHBOARD_HOST = os.getenv("RAY_DASHBOARD_HOST", "0.0.0.0")
RAY_NUM_CPUS = int(os.getenv("RAY_NUM_CPUS", "4"))
RAY_OBJECT_STORE_MEMORY_GB = float(
    os.getenv("RAY_OBJECT_STORE_MEMORY_GB", "0.25"))
RAY_TEMP_DIR = os.getenv("RAY_TEMP_DIR", "/tmp/ray")
RAY_LOG_LEVEL = os.getenv("RAY_LOG_LEVEL", "INFO").upper()
# Disable plasma preallocation to reduce idle memory usage
# When set to false, Ray will allocate object store memory on-demand instead of preallocating
RAY_preallocate_plasma = os.getenv(
    "RAY_preallocate_plasma", "false").lower() == "true"


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


# Celery Configuration
CELERY_WORKER_PREFETCH_MULTIPLIER = int(
    os.getenv("CELERY_WORKER_PREFETCH_MULTIPLIER", "1"))
CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "3600"))
ELASTICSEARCH_REQUEST_TIMEOUT = int(
    os.getenv("ELASTICSEARCH_REQUEST_TIMEOUT", "30"))


# Worker Configuration
RAY_ADDRESS = os.getenv("RAY_ADDRESS", "auto")
QUEUES = os.getenv("QUEUES", "process_q,process_part_q,forward_q")
# Will be dynamically set based on PID if not provided
WORKER_NAME = os.getenv("WORKER_NAME")
WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "4"))
RAY_WARM_ACTOR_POOL_SIZE_PART = int(
    os.getenv("RAY_WARM_ACTOR_POOL_SIZE_PART", "2"))
RAY_WARM_ACTOR_POOL_SIZE_PROCESS = int(
    os.getenv("RAY_WARM_ACTOR_POOL_SIZE_PROCESS", "1"))
# Global Ray actor pool (shared by process_q/process_part_q workers)
RAY_GLOBAL_ACTOR_POOL_SIZE = int(os.getenv("RAY_GLOBAL_ACTOR_POOL_SIZE", "3"))
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
MEMORY_AGENT_SHARE_KEY = "MEMORY_AGENT_SHARE"
DISABLE_AGENT_ID_KEY = "DISABLE_AGENT_ID"
DISABLE_USERAGENT_ID_KEY = "DISABLE_USERAGENT_ID"
DEFAULT_MEMORY_SWITCH_KEY = "Y"
DEFAULT_MEMORY_AGENT_SHARE_KEY = "always"
# Boolean value representations for configuration parsing
BOOLEAN_TRUE_VALUES = {"true", "1", "y", "yes", "on"}


DEFAULT_LLM_MAX_TOKENS = 4096


# Embedding Model Chunk Size Defaults
DEFAULT_EXPECTED_CHUNK_SIZE = 1024
DEFAULT_MAXIMUM_CHUNK_SIZE = 1536


# MCP Server
LOCAL_MCP_SERVER = os.getenv("NEXENT_MCP_SERVER")
MCP_MANAGEMENT_API = os.getenv("MCP_MANAGEMENT_API", "http://localhost:5015")


# Invite code
INVITE_CODE = os.getenv("INVITE_CODE")

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
    "stt": "STT_ID",
    "tts": "TTS_ID"
}

APP_NAME = "APP_NAME"
APP_DESCRIPTION = "APP_DESCRIPTION"
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
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "")
OTEL_EXPORTER_OTLP_PROTOCOL_RAW = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL")
OTEL_EXPORTER_OTLP_PROTOCOL = OTEL_EXPORTER_OTLP_PROTOCOL_RAW or "http"
OTEL_EXPORTER_OTLP_HEADERS_RAW = os.getenv("OTEL_EXPORTER_OTLP_HEADERS")
OTEL_EXPORTER_OTLP_HEADERS = OTEL_EXPORTER_OTLP_HEADERS_RAW or ""
OTEL_EXPORTER_OTLP_AUTHORIZATION = os.getenv("OTEL_EXPORTER_OTLP_AUTHORIZATION", "")
OTEL_EXPORTER_OTLP_X_API_KEY = os.getenv("OTEL_EXPORTER_OTLP_X_API_KEY", "")
OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION = os.getenv(
    "OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION", "")
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "")
OTEL_EXPORTER_OTLP_METRICS_ENABLED_RAW = os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENABLED")
OTEL_EXPORTER_OTLP_METRICS_ENABLED = (
    OTEL_EXPORTER_OTLP_METRICS_ENABLED_RAW or "true").lower() == "true"
MONITORING_INSTRUMENT_REQUESTS_RAW = os.getenv("MONITORING_INSTRUMENT_REQUESTS")
MONITORING_INSTRUMENT_REQUESTS = (
    MONITORING_INSTRUMENT_REQUESTS_RAW or "false").lower() == "true"
MONITORING_FASTAPI_INCLUDED_URLS = os.getenv("MONITORING_FASTAPI_INCLUDED_URLS", "")
MONITORING_FASTAPI_EXCLUDED_URLS = os.getenv("MONITORING_FASTAPI_EXCLUDED_URLS", "")
MONITORING_FASTAPI_EXCLUDE_SPANS = os.getenv("MONITORING_FASTAPI_EXCLUDE_SPANS", "receive,send")
MONITORING_PROJECT_NAME = os.getenv("MONITORING_PROJECT_NAME", "")
MONITORING_DASHBOARD_URL = os.getenv("MONITORING_DASHBOARD_URL", "")
MONITORING_TRACE_CONTENT_MODE = os.getenv("MONITORING_TRACE_CONTENT_MODE", "summary")
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


# APP Version
APP_VERSION = "v2.2.0"


# Skill Creation Streaming Configuration
STREAMABLE_CONTENT_TYPES = frozenset([
    "model_output_thinking",
    "model_output_code",
    "model_output_deep_thinking",
    "tool",
    "execution_logs",
])
