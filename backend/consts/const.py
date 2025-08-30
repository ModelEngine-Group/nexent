import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


# Test voice file path
TEST_VOICE_PATH = os.path.join(os.path.dirname(
    os.path.dirname(__file__)), 'assets', 'test.wav')


# ModelEngine Configuration
MODEL_ENGINE_HOST = os.getenv('MODEL_ENGINE_HOST')
MODEL_ENGINE_APIKEY = os.getenv('MODEL_ENGINE_APIKEY')


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


# Supabase Configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')


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


# Deployment Version Configuration
DEPLOYMENT_VERSION = os.getenv("DEPLOYMENT_VERSION", "speed")
IS_SPEED_MODE = DEPLOYMENT_VERSION == "speed"
DEFAULT_APP_DESCRIPTION_ZH = "Nexent 是一个开源智能体SDK和平台，能够将单一提示词转化为完整的多模态服务 —— 无需编排，无需复杂拖拉拽。基于 MCP 工具生态系统构建，Nexent 提供灵活的模型集成、可扩展的数据处理和强大的知识库管理。我们的目标很简单：将数据、模型和工具整合到一个智能中心中，让任何人都能轻松地将 Nexent 集成到项目中，使日常工作流程更智能、更互联。"
DEFAULT_APP_DESCRIPTION_EN = "Nexent is an open-source agent SDK and platform, which can convert a single prompt into a complete multi-modal service - without orchestration, without complex drag-and-drop. Built on the MCP tool ecosystem, Nexent provides flexible model integration, scalable data processing, and powerful knowledge base management. Our goal is simple: to integrate data, models, and tools into a central intelligence hub, allowing anyone to easily integrate Nexent into their projects, making daily workflows smarter and more interconnected."
DEFAULT_APP_NAME_ZH = "Nexent 智能体"
DEFAULT_APP_NAME_EN = "Nexent Agent"
DEFAULT_APP_ICON_URL = "data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20shape-rendering%3D%22auto%22%20width%3D%2230%22%20height%3D%2230%22%3E%3Cmetadata%20xmlns%3Ardf%3D%22http%3A%2F%2Fwww.w3.org%2F1999%2F02%2F22-rdf-syntax-ns%23%22%20xmlns%3Axsi%3D%22http%3A%2F%2Fwww.w3.org%2F2001%2FXMLSchema-instance%22%20xmlns%3Adc%3D%22http%3A%2F%2Fpurl.org%2Fdc%2Felements%2F1.1%2F%22%20xmlns%3Adcterms%3D%22http%3A%2F%2Fpurl.org%2Fdc%2Fterms%2F%22%3E%3Crdf%3ARDF%3E%3Crdf%3ADescription%3E%3Cdc%3Atitle%3EBootstrap%20Icons%3C%2Fdc%3Atitle%3E%3Cdc%3Acreator%3EThe%20Bootstrap%20Authors%3C%2Fdc%3Acreator%3E%3Cdc%3Asource%20xsi%3Atype%3D%22dcterms%3AURI%22%3Ehttps%3A%2F%2Fgithub.com%2Ftwbs%2Ficons%3C%2Fdc%3Asource%3E%3Cdcterms%3Alicense%20xsi%3Atype%3D%22dcterms%3AURI%22%3Ehttps%3A%2F%2Fgithub.com%2Ftwbs%2Ficons%2Fblob%2Fmain%2FLICENSE%3C%2Fdcterms%3Alicense%3E%3Cdc%3Arights%3E%E2%80%9EBootstrap%20Icons%E2%80%9D%20(https%3A%2F%2Fgithub.com%2Ftwbs%2Ficons)%20by%20%E2%80%9EThe%20Bootstrap%20Authors%E2%80%9D%2C%20licensed%20under%20%E2%80%9EMIT%E2%80%9D%20(https%3A%2F%2Fgithub.com%2Ftwbs%2Ficons%2Fblob%2Fmain%2FLICENSE)%3C%2Fdc%3Arights%3E%3C%2Frdf%3ADescription%3E%3C%2Frdf%3ARDF%3E%3C%2Fmetadata%3E%3Cmask%20id%3D%22viewboxMask%22%3E%3Crect%20width%3D%2224%22%20height%3D%2224%22%20rx%3D%2212%22%20ry%3D%2212%22%20x%3D%220%22%20y%3D%220%22%20fill%3D%22%23fff%22%20%2F%3E%3C%2Fmask%3E%3Cg%20mask%3D%22url(%23viewboxMask)%22%3E%3Crect%20fill%3D%22url(%23backgroundLinear)%22%20width%3D%2224%22%20height%3D%2224%22%20x%3D%220%22%20y%3D%220%22%20%2F%3E%3Cdefs%3E%3ClinearGradient%20id%3D%22backgroundLinear%22%20gradientTransform%3D%22rotate(196%200.5%200.5)%22%3E%3Cstop%20stop-color%3D%22%232689cb%22%2F%3E%3Cstop%20offset%3D%221%22%20stop-color%3D%22%234226cb%22%2F%3E%3C%2FlinearGradient%3E%3C%2Fdefs%3E%3Cg%20transform%3D%22translate(2.4000000000000004%202.4000000000000004)%20scale(0.8)%22%3E%3Cg%20transform%3D%22translate(4%204)%22%3E%3Cpath%20d%3D%22M11.742%2010.344a6.5%206.5%200%201%200-1.397%201.398h-.001c.03.04.062.078.098.115l3.85%203.85a1%201%200%200%200%201.415-1.414l-3.85-3.85a1.012%201.012%200%200%200-.115-.1v.001ZM12%206.5a5.5%205.5%200%201%201-11%200%205.5%205.5%200%200%201%2011%200Z%22%20fill%3D%22%23fff%22%2F%3E%3C%2Fg%3E%3C%2Fg%3E%3C%2Fg%3E%3C%2Fsvg%3E"


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


# Ray Configuration
RAY_ACTOR_NUM_CPUS = int(os.getenv("RAY_ACTOR_NUM_CPUS", "2"))
RAY_DASHBOARD_PORT = int(os.getenv("RAY_DASHBOARD_PORT", "8265"))
RAY_DASHBOARD_HOST = os.getenv("RAY_DASHBOARD_HOST", "0.0.0.0")
RAY_NUM_CPUS = os.getenv("RAY_NUM_CPUS")
RAY_PLASMA_DIRECTORY = os.getenv("RAY_PLASMA_DIRECTORY", "/tmp")
RAY_OBJECT_STORE_MEMORY_GB = float(
    os.getenv("RAY_OBJECT_STORE_MEMORY_GB", "2.0"))
RAY_TEMP_DIR = os.getenv("RAY_TEMP_DIR", "/tmp/ray")
RAY_LOG_LEVEL = os.getenv("RAY_LOG_LEVEL", "INFO").upper()


# Service Control Flags
DISABLE_RAY_DASHBOARD = os.getenv(
    "DISABLE_RAY_DASHBOARD", "false").lower() == "true"
DISABLE_CELERY_FLOWER = os.getenv(
    "DISABLE_CELERY_FLOWER", "false").lower() == "true"
DOCKER_ENVIRONMENT = os.getenv("DOCKER_ENVIRONMENT", "false").lower() == "true"


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


# MCP Server
LOCAL_MCP_SERVER = os.getenv("NEXENT_MCP_SERVER", "http://localhost:5011")


# Invite code
INVITE_CODE = os.getenv("INVITE_CODE")
