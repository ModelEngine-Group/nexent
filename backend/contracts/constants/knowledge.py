# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Scheduler frequency constants
Centralized definition for auto-summary frequency options
"""

from datetime import timedelta
from enum import Enum


# Core frequency config: includes value, timedelta, and label; this is the single source of truth
SUMMARY_FREQUENCY_CONFIG = [
    {"value": "1h", "timedelta": timedelta(hours=1), "label": "1h"},
    {"value": "3h", "timedelta": timedelta(hours=3), "label": "3h"},
    {"value": "6h", "timedelta": timedelta(hours=6), "label": "6h"},
    {"value": "1d", "timedelta": timedelta(days=1), "label": "1d"},
    {"value": "1w", "timedelta": timedelta(weeks=1), "label": "1w"},
]

# Generate valid frequency list from config (for validation)
VALID_SUMMARY_FREQUENCIES = [item["value"] for item in SUMMARY_FREQUENCY_CONFIG] + [
    None
]

# Generate frequency to timedelta mapping from config (direct value, no loop conversion needed)
FREQUENCY_MAP = {item["value"]: item["timedelta"] for item in SUMMARY_FREQUENCY_CONFIG}

# Generate API options from config (for frontend)
SUMMARY_FREQUENCY_OPTIONS_FOR_API = [
    {"value": "disabled", "label": "Disabled"},
] + [
    {"value": item["value"], "label": item["value"]}
    for item in SUMMARY_FREQUENCY_CONFIG
]

# Scheduler check interval (seconds)
SCHEDULER_CHECK_INTERVAL_SECONDS = 30 * 60


# Vector database providers
class VectorDatabaseType(str, Enum):
    ELASTICSEARCH = "elasticsearch"
    DATAMATE = "datamate"


RATE_LIMIT_EXCEEDED_DETAIL = "Too Many Requests: rate limit exceeded"

QUOTA_PAYLOAD_DESCRIPTION = "Quota payload"


PERSONAL_KB_CAPACITY_READ_PERMISSION = "kb.capacity:read"


PERSONAL_KB_CAPACITY_MANAGE_PERMISSION = "kb.capacity:manage"


TARGET_TENANT_ID_DESCRIPTION = "Target tenant ID (SU/SPEED only)"

INTERNAL_INDEX_NAME_DESC = "Internal index_name from knowledge_record_t"

ACTIVE_STATUSES = (
    "UPLOADING",
    "UPLOADED",
    "PROCESSING",
    "FORWARDING",
    "FAILED",
    "COMPLETED",
)


HIDDEN_STATUSES = ("DELETE_REQUESTED", "DELETED")

COMMITTED_STATUS = "COMMITTED"


DELETED_STATUS = "DELETED"
ES_USERNAME = "elastic"
S3_URL_PREFIX = "s3://"


# Embedding Model Chunk Size Defaults
DEFAULT_EXPECTED_CHUNK_SIZE = 1024
DEFAULT_MAXIMUM_CHUNK_SIZE = 1536

# Knowledge summary max token limits
KNOWLEDGE_SUMMARY_MAX_TOKENS_ZH = 300
KNOWLEDGE_SUMMARY_MAX_TOKENS_EN = 120
