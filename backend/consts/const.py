import os
from enum import Enum
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# TODO: Analyze every variable if this is used
# Test voice file path
TEST_VOICE_PATH = os.path.join(os.path.dirname(
    os.path.dirname(__file__)), 'assets', 'test.wav')


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


# Upload Configuration
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
MAX_CONCURRENT_UPLOADS = 5
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')
ROOT_DIR = os.getenv("ROOT_DIR")


# Supabase Configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
SERVICE_ROLE_KEY = os.getenv('SERVICE_ROLE_KEY', SUPABASE_KEY)


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

# Roles that can edit all resources within a tenant (permission = EDIT).
# Keep this centralized to avoid drifting role logic across modules.
CAN_EDIT_ALL_USER_ROLES = {"SU", "ADMIN", "SPEED"}

# Permission constants used by list endpoints (e.g., /agent/list, /mcp/list).
PERMISSION_READ = "READ_ONLY"
PERMISSION_EDIT = "EDIT"


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
RAY_NUM_CPUS = os.getenv("RAY_NUM_CPUS")
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
QUEUES = os.getenv("QUEUES", "process_q,forward_q")
# Will be dynamically set based on PID if not provided
WORKER_NAME = os.getenv("WORKER_NAME")
WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "4"))


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
    "stt": "STT_ID",
    "tts": "TTS_ID"
}

APP_NAME = "APP_NAME"
APP_DESCRIPTION = "APP_DESCRIPTION"
ICON_TYPE = "ICON_TYPE"
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


# Telemetry and Monitoring Configuration
ENABLE_TELEMETRY = os.getenv("ENABLE_TELEMETRY", "false").lower() == "true"
SERVICE_NAME = os.getenv("SERVICE_NAME", "nexent-backend")
JAEGER_ENDPOINT = os.getenv(
    "JAEGER_ENDPOINT", "http://localhost:14268/api/traces")
PROMETHEUS_PORT = int(os.getenv("PROMETHEUS_PORT", "8000"))
TELEMETRY_SAMPLE_RATE = float(os.getenv("TELEMETRY_SAMPLE_RATE", "1.0"))

# Performance monitoring thresholds
LLM_SLOW_REQUEST_THRESHOLD_SECONDS = float(
    os.getenv("LLM_SLOW_REQUEST_THRESHOLD_SECONDS", "5.0"))
LLM_SLOW_TOKEN_RATE_THRESHOLD = float(
    os.getenv("LLM_SLOW_TOKEN_RATE_THRESHOLD", "10.0"))  # tokens per second


DEFAULT_ZH_TITLE = "新对话"
DEFAULT_EN_TITLE = "New Conversation"


# Model Engine Configuration
MODEL_ENGINE_ENABLED = os.getenv("MODEL_ENGINE_ENABLED")

# APP Version
APP_VERSION = "v1.8.0"
