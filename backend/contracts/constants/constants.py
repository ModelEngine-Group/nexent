# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import os
from datetime import timedelta

# A2A
DEFAULT_CACHE_TTL_HOURS = 24
PROTOCOL_HTTP_JSON = 'HTTP+JSON'
PROTOCOL_JSONRPC = 'JSONRPC'
PROTOCOL_GRPC = 'GRPC'

# Agent
WORKBENCH_OFFICIAL_SKILL_NAMES = ('docx', 'pdf', 'pptx', 'xlsx', 'canvas-design', 'analyze-image')
SAFE_AGENT_STREAM_ERROR_MESSAGE = 'Agent execution failed. Please try again later.'
SAFE_REASONING_CONFIGURATION_ERROR_MESSAGE = '思考挡位参数配置错误：当前模型或服务商不支持所选挡位，请在模型高级设置中关闭思考挡位开关或选择支持的挡位。'
REASONING_CONFIGURATION_ERROR_CODE = 'MODEL_REASONING_CONFIG_INVALID'
# Listing status: not_shared (未共享), pending_review (待审核),
# rejected (审核驳回), shared (已共享)
STATUS_NOT_SHARED = 'not_shared'
STATUS_PENDING_REVIEW = 'pending_review'
STATUS_REJECTED = 'rejected'
STATUS_SHARED = 'shared'
VALID_REPOSITORY_STATUSES = frozenset({STATUS_NOT_SHARED, STATUS_PENDING_REVIEW, STATUS_REJECTED, STATUS_SHARED})
OWNERSHIP_ALL = 'all'
OWNERSHIP_CREATED = 'created'
OWNERSHIP_OTHERS = 'others'
VALID_OWNERSHIP_FILTERS = frozenset({OWNERSHIP_ALL, OWNERSHIP_CREATED, OWNERSHIP_OTHERS})
SOURCE_TYPE_NORMAL = 'NORMAL'
SOURCE_TYPE_ROLLBACK = 'ROLLBACK'
STATUS_RELEASED = 'RELEASED'
STATUS_DISABLED = 'DISABLED'
STATUS_ARCHIVED = 'ARCHIVED'
# Response flag when system prompts are withheld from non-ASSET_OWNER callers.
AGENT_PROMPTS_HIDDEN_FLAG = 'prompts_hidden'
DEFAULT_LLM_MAX_TOKENS = 4096
# Deep Thinking Constants
THINK_START_PATTERN = '<think>'
THINK_END_PATTERN = '</think>'
# Skill Creation Streaming Configuration
STREAMABLE_CONTENT_TYPES = frozenset(['model_output_thinking', 'model_output_code', 'model_output_deep_thinking', 'tool', 'execution_logs'])
# SSE streaming event type for status messages
STREAM_STATUS_EVENT = 'event: stream_status\n'

# Configuration
ICON_TYPE = 'ICON_TYPE'
ICON_KEY = 'ICON_KEY'
AVATAR_URI = 'AVATAR_URI'
CUSTOM_ICON_URL = 'CUSTOM_ICON_URL'
TENANT_NAME = 'TENANT_NAME'
TENANT_ID = 'TENANT_ID'
DEFAULT_GROUP_ID = 'DEFAULT_GROUP_ID'
DATAMATE_URL = 'DATAMATE_URL'

# Conversation
HISTORY_SUMMARY_UNIT_TYPE = 'history_summary'
CHAT_MODE_VALUES = {'planning', 'execution'}
# Message Role Constants
MESSAGE_ROLE = {'USER': 'user', 'ASSISTANT': 'assistant', 'SYSTEM': 'system'}
DEFAULT_ZH_TITLE = '新对话'
DEFAULT_EN_TITLE = 'New Conversation'

# Data Process
# Task Status Constants
TASK_STATUS = {'WAIT_FOR_PROCESSING': 'WAIT_FOR_PROCESSING', 'WAIT_FOR_FORWARDING': 'WAIT_FOR_FORWARDING', 'PROCESSING': 'PROCESSING', 'FORWARDING': 'FORWARDING', 'COMPLETED': 'COMPLETED', 'PROCESS_FAILED': 'PROCESS_FAILED', 'FORWARD_FAILED': 'FORWARD_FAILED'}

# Evaluation
# Concurrent tasks
MAX_CONCURRENT_RUNS = 5
MAX_TOTAL_RUNS = 500
# Per-run
MAX_EVALUATORS_PER_RUN = 5
# Scoring
DEFAULT_PASS_THRESHOLD = 0.5
SCORE_RANGE_MIN_DEFAULT = 0.0
SCORE_RANGE_MAX_DEFAULT = 1.0
SCORE_ABSOLUTE_MAX = 100.0
# Evaluator
EVALUATOR_NAME_MIN_LEN = 1
EVALUATOR_NAME_MAX_LEN = 50
EVALUATOR_DESC_MAX_LEN = 200
EVALUATOR_PROMPT_MAX_LEN = 5000
EVALUATOR_CODE_MAX_LEN = 20000
# Retention
RUN_RETENTION_DAYS = 30
# Evaluation sets
MAX_EVALUATION_SETS = 50
MAX_CASES_PER_SET = 2000
MAX_TURNS_PER_SESSION = 10
SET_NAME_MIN_LEN = 2
SET_NAME_MAX_LEN = 64
# Case content
CASE_QUERY_MAX_LEN = 2000
CASE_ANSWER_MAX_LEN = 5000
# Annotation
MAX_ANNOTATIONS_PER_CASE = 5
MAX_ANNOTATION_SCHEMAS = 500
ANNOTATION_CLASSIFICATION_MAX_OPTIONS = 20
ANNOTATION_OPTION_MAX_LEN = 50
ANNOTATION_NUMBER_MIN = -999999
ANNOTATION_NUMBER_MAX = 999999
ANNOTATION_TEXT_MAX_LEN = 200
# PDF report labels in Chinese and English.
_REPORT_LABELS = {'zh': {'TITLE': 'Agent 评测报告', 'SUBTITLE': '智能体: {agent} | 报告 #{id} | 生成时间 {time}', 'SECTION_OVERVIEW': '一、概述', 'SECTION_CONFIG': '二、评测配置', 'SECTION_ANALYSIS': '三、评估结果分析', 'SECTION_DETAILS': '四、用例详情', 'STATUS_COMPLETED': '已完成', 'STATUS_RUNNING': '运行中', 'STATUS_PENDING': '等待中', 'STATUS_FAILED': '失败', 'SCORE_EXCELLENT': '表现优秀', 'SCORE_GOOD': '表现良好', 'SCORE_NEEDS_IMPROVEMENT': '需要改进', 'SCORE_NA': '未指定', 'METRIC_SCORE': '综合得分 (0-1)', 'METRIC_PASS_RATE': '通过率', 'METRIC_TOTAL': '用例总数', 'META_TARGET': '评测对象', 'META_SET': '评测集', 'META_NO_SET': ' [无评测集]', 'META_MODEL': 'Judge 模型', 'META_VERSION': '版本', 'META_CREATED': '创建时间', 'META_COMPLETED': '完成时间', 'META_EVALUATORS': '评估器数量', 'META_PROGRESS': '进度', 'CHART_SCORES': '各评估器得分', 'CHART_DISTRIBUTION': '得分分布', 'ANALYSIS_TEMPLATE': '在 {n} 个评估维度中，<b>「{best}」</b>得分最高（{best_score:.2f}），<b>「{worst}」</b>得分最低（{worst_score:.2f}）。', 'SUMMARY_TEMPLATE': '本次评测对智能体 {agent} 进行了 {total} 个测试用例的评估，状态为{status}，综合得分 {overall}（{level}）。共使用了 {evaluator_count} 个评估器（{evaluator_names}），其中 {pass_count} 个用例通过（通过率 {pass_rate}），{fail_count} 个用例未通过。', 'SUMMARY_EXTRA': ' 该智能体在 {top}/{total} 个用例中得分 ≥0.8，整体质量{quality}。', 'QUALITY_HIGH': '较高', 'QUALITY_MEDIUM': '中等', 'QUALITY_LOW': '偏低', 'COL_HEADER_INDEX': '#', 'COL_HEADER_QUERY': '评测问题', 'COL_HEADER_SCORE': '评估得分', 'COL_HEADER_RESULT': '结果', 'PASS_LABEL': '通过', 'FAIL_LABEL': '失败', 'FOOTER': 'Nexent Agent 评测报告 | 生成时间 {time}', 'SECTION_ANNOTATIONS': '标注统计', 'ANNOTATION_COVERAGE': '已标注 {coverage}', 'ANNOTATION_NO_DATA': '暂无标注数据'}, 'en': {'TITLE': 'Agent Evaluation Report', 'SUBTITLE': 'Agent: {agent} | Report #{id} | Generated {time}', 'SECTION_OVERVIEW': '1. Overview', 'SECTION_CONFIG': '2. Configuration', 'SECTION_ANALYSIS': '3. Results Analysis', 'SECTION_DETAILS': '4. Case Details', 'STATUS_COMPLETED': 'Completed', 'STATUS_RUNNING': 'Running', 'STATUS_PENDING': 'Pending', 'STATUS_FAILED': 'Failed', 'SCORE_EXCELLENT': 'Excellent', 'SCORE_GOOD': 'Good', 'SCORE_NEEDS_IMPROVEMENT': 'Needs Improvement', 'SCORE_NA': 'N/A', 'METRIC_SCORE': 'Overall Score (0-1)', 'METRIC_PASS_RATE': 'Pass Rate', 'METRIC_TOTAL': 'Total Cases', 'META_TARGET': 'Target', 'META_SET': 'Evaluation Set', 'META_NO_SET': ' [No Set]', 'META_MODEL': 'Judge Model', 'META_VERSION': 'Version', 'META_CREATED': 'Created', 'META_COMPLETED': 'Completed', 'META_EVALUATORS': 'Evaluators', 'META_PROGRESS': 'Progress', 'CHART_SCORES': 'Per-Evaluator Scores', 'CHART_DISTRIBUTION': 'Score Distribution', 'ANALYSIS_TEMPLATE': 'Among {n} evaluators, <b>"{best}"</b> scored highest ({best_score:.2f}), <b>"{worst}"</b> scored lowest ({worst_score:.2f}).', 'SUMMARY_TEMPLATE': 'Evaluated Agent {agent} across {total} test cases, status: {status}, overall score {overall} ({level}). Used {evaluator_count} evaluators ({evaluator_names}), {pass_count} passed (pass rate {pass_rate}), {fail_count} failed.', 'SUMMARY_EXTRA': ' {top}/{total} cases scored 0.8, overall quality {quality}.', 'QUALITY_HIGH': 'high', 'QUALITY_MEDIUM': 'medium', 'QUALITY_LOW': 'low', 'COL_HEADER_INDEX': '#', 'COL_HEADER_QUERY': 'Question', 'COL_HEADER_SCORE': 'Score', 'COL_HEADER_RESULT': 'Result', 'PASS_LABEL': 'Pass', 'FAIL_LABEL': 'Fail', 'FOOTER': 'Nexent Agent Evaluation Report | Generated {time}', 'SECTION_ANNOTATIONS': 'Annotations', 'ANNOTATION_COVERAGE': 'Annotated {coverage}', 'ANNOTATION_NO_DATA': 'No annotation data'}}
# Used in generate_analysis_report_impl
MAX_FAILURE_EXAMPLES = 200
_AUTH_REQUIRED_MSG = 'Authentication required'
_UNKNOWN_ID = '<unknown>'
_UNAUTHORIZED_MESSAGE = 'Authentication required'

# File
# Upload Configuration
MAX_FILE_SIZE = 100 * 1024 * 1024
MAX_CONCURRENT_UPLOADS = 5
# Preview Configuration
FILE_PREVIEW_SIZE_LIMIT = 100 * 1024 * 1024
# Limit concurrent Office-to-PDF conversions
MAX_CONCURRENT_CONVERSIONS = 5
# Supported Office file MIME types
OFFICE_MIME_TYPES = ['application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation']

# Identity
OAUTH_PENDING_EXPIRE_SECONDS = 10 * 60
OAUTH_PENDING_PURPOSE = 'oauth_account_completion'
CAS_SESSION_ACTIVE = 'active'
CAS_SESSION_REVOKED = 'revoked'
SYSTEM_TENANT_ID = 'system'
SYSTEM_USER_ID = 'system'
# Default User and Tenant IDs
DEFAULT_USER_ID = 'user_id'
DEFAULT_TENANT_ID = 'tenant_id'
# Invitation code type for asset administrator registration
ASSET_OWNER_INVITE_CODE_TYPE = 'ASSET_OWNER_INVITE'
# User role identifier for asset administrators
ASSET_OWNER_ROLE = 'ASSET_OWNER'
# Tenant ID for asset administrators (virtual tenant, not a real tenant)
ASSET_OWNER_TENANT_ID = 'asset_owner_tenant_id'
# MinIO prefix for ASSET_OWNER-scoped attachment uploads (attachments/asset_owner/{user_id}/...)
ASSET_OWNER_ATTACHMENTS_PREFIX = 'attachments/asset_owner'
# HTTP detail key: asset owner must register via OAuth, not email/password signup.
ASSET_OWNER_SIGNUP_USE_OAUTH_DETAIL = 'ASSET_OWNER_USE_OAUTH'
# Roles that can edit all resources within a tenant (permission = EDIT).
# Keep this centralized to avoid drifting role logic across modules.
CAN_EDIT_ALL_USER_ROLES = {'SU', 'ADMIN', 'SPEED', 'ASSET_OWNER'}
# Permission constants used by list endpoints (e.g., /agent/list, /mcp/list).
PERMISSION_READ = 'READ_ONLY'
PERMISSION_EDIT = 'EDIT'
PERMISSION_PRIVATE = 'PRIVATE'
# Mock User Management Configuration (for speed mode)
MOCK_USER = {'id': DEFAULT_USER_ID, 'email': 'mock@example.com', 'role': 'admin'}
# expires_at is set dynamically; expires_in_seconds covers ten years.
MOCK_SESSION = {'access_token': 'mock_access_token', 'refresh_token': 'mock_refresh_token', 'expires_at': None, 'expires_in_seconds': 315360000}
# Fixed test secret used by generate_test_jwt and unit tests.
MOCK_JWT_SECRET_KEY = 'nexent-mock-jwt-secret'

# Knowledge
# Auto-summary frequency options shared by validation, scheduling and the API.
SUMMARY_FREQUENCY_CONFIG = [{'value': '1h', 'timedelta': timedelta(hours=1), 'label': '1h'}, {'value': '3h', 'timedelta': timedelta(hours=3), 'label': '3h'}, {'value': '6h', 'timedelta': timedelta(hours=6), 'label': '6h'}, {'value': '1d', 'timedelta': timedelta(days=1), 'label': '1d'}, {'value': '1w', 'timedelta': timedelta(weeks=1), 'label': '1w'}]
# Generate valid frequency list from config (for validation)
VALID_SUMMARY_FREQUENCIES = [item['value'] for item in SUMMARY_FREQUENCY_CONFIG] + [None]
# Generate frequency to timedelta mapping from config (direct value, no loop conversion needed)
FREQUENCY_MAP = {item['value']: item['timedelta'] for item in SUMMARY_FREQUENCY_CONFIG}
# Generate API options from config (for frontend)
SUMMARY_FREQUENCY_OPTIONS_FOR_API = [{'value': 'disabled', 'label': 'Disabled'}] + [{'value': item['value'], 'label': item['value']} for item in SUMMARY_FREQUENCY_CONFIG]
# Scheduler check interval (seconds)
SCHEDULER_CHECK_INTERVAL_SECONDS = 30 * 60
RATE_LIMIT_EXCEEDED_DETAIL = 'Too Many Requests: rate limit exceeded'
QUOTA_PAYLOAD_DESCRIPTION = 'Quota payload'
PERSONAL_KB_CAPACITY_READ_PERMISSION = 'kb.capacity:read'
PERSONAL_KB_CAPACITY_MANAGE_PERMISSION = 'kb.capacity:manage'
TARGET_TENANT_ID_DESCRIPTION = 'Target tenant ID (SU/SPEED only)'
INTERNAL_INDEX_NAME_DESC = 'Internal index_name from knowledge_record_t'
ACTIVE_STATUSES = ('UPLOADING', 'UPLOADED', 'PROCESSING', 'FORWARDING', 'FAILED', 'COMPLETED')
HIDDEN_STATUSES = ('DELETE_REQUESTED', 'DELETED')
COMMITTED_STATUS = 'COMMITTED'
DELETED_STATUS = 'DELETED'
ES_USERNAME = 'elastic'
S3_URL_PREFIX = 's3://'
# Embedding Model Chunk Size Defaults
DEFAULT_EXPECTED_CHUNK_SIZE = 1024
DEFAULT_MAXIMUM_CHUNK_SIZE = 1536
# Knowledge summary max token limits
KNOWLEDGE_SUMMARY_MAX_TOKENS_ZH = 300
KNOWLEDGE_SUMMARY_MAX_TOKENS_EN = 120

# Localization
LANGUAGE = {'ZH': 'zh', 'EN': 'en'}

# Memory
USER_DREAMING_SCOPE = '__user__'
# Memory Feature
MEMORY_SWITCH_KEY = 'MEMORY_SWITCH'
DREAMING_SWITCH_KEY = 'DREAMING_SWITCH'
MEMORY_AGENT_SHARE_KEY = 'MEMORY_AGENT_SHARE'
DISABLE_AGENT_ID_KEY = 'DISABLE_AGENT_ID'
DISABLE_USERAGENT_ID_KEY = 'DISABLE_USERAGENT_ID'
EXTERNAL_PROVIDER_TOP_K_KEY = 'EXTERNAL_PROVIDER_TOP_K'
DEFAULT_MEMORY_SWITCH_KEY = 'Y'
DEFAULT_DREAMING_SWITCH_KEY = 'Y'
DEFAULT_MEMORY_AGENT_SHARE_KEY = 'always'
DEFAULT_EXTERNAL_PROVIDER_TOP_K = 20
# Boolean value representations for configuration parsing
BOOLEAN_TRUE_VALUES = {'true', '1', 'y', 'yes', 'on'}
# External provider protocol defaults. Provider records control whether each
# configured integration participates in search and ingest.
EXTERNAL_MEMORY_DEFAULT_ALLOWED_UNIT_TYPES = ('agent', 'model_output', 'model_output_thinking', 'model_output_deep_thinking', 'model_output_code', 'final_answer', 'error', 'search_content', 'tool', 'parse', 'execution_logs', 'picture_web', 'memory_search', 'verification', 'max_steps_reached')
# Memory Search Status Messages (for i18n placeholders)
MEMORY_SEARCH_START_MSG = '<MEM_START>'
MEMORY_SEARCH_DONE_MSG = '<MEM_DONE>'
MEMORY_SEARCH_FAIL_MSG = '<MEM_FAILED>'

# Model
# Changes to entries: bump the per-entry `capability_profile_version` integer
# suffix AND `CATALOG_REVISION` in one PR. Numerical values must be re-verified
# against provider documentation at PR merge time.
CATALOG_REVISION = '2026-06-27.1'
# Capability profile data used by management.services.model.catalog to build the typed catalog.
# Sources cross-checked 2026-06-23:
# https://help.aliyun.com/zh/model-studio/models (Bailian model catalog)
# https://llm-stats.com/models/qwen3.7-max (1.0M input, 65.5K output)
# DeepSeek official platform. Verified 2026-06-23 against
# https://api-docs.deepseek.com/zh-cn/quick_start/pricing
# (context 1M, max output 384K for both v4 models).
# `deepseek-chat` and `deepseek-reasoner` will be deprecated at
# 2026-07-24 23:59 (Beijing). Per DeepSeek docs they alias to
# `deepseek-v4-flash` non-thinking and thinking modes respectively,
# so their capacity profile mirrors `deepseek-v4-flash`. Remove these
# two entries after the deprecation date.
# SiliconFlow hosted models. Capacity specs sourced from SiliconFlow pricing
# page (siliconflow.com/pricing), official model documentation on HuggingFace
# and GitHub, and provider API docs. Re-verify at PR merge time.
# DeepSeek models hosted on SiliconFlow. deepseek-ai/ prefixed names are
# the standard tier; Pro/ prefixed names are the premium tier with the
# same model weights but higher throughput. Specs from DeepSeek API docs
# (api-docs.deepseek.com) and SiliconFlow pricing.
# Catalog key uses "silicon" (hosting provider / DB model_factory), not "deepseek" (model vendor).
MODEL_CAPABILITY_CATALOG_DATA = {('openai', 'gpt-4o'): {'provider': 'openai', 'model_name': 'gpt-4o', 'capability_profile_version': 'openai/gpt-4o@1', 'window_shape': 'combined', 'context_window_tokens': 128000, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'o200k_base'}, ('openai', 'gpt-4.1'): {'provider': 'openai', 'model_name': 'gpt-4.1', 'capability_profile_version': 'openai/gpt-4.1@1', 'window_shape': 'combined', 'context_window_tokens': 1000000, 'max_output_tokens': 32768, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'o200k_base'}, ('dashscope', 'qwen-plus'): {'provider': 'dashscope', 'model_name': 'qwen-plus', 'capability_profile_version': 'dashscope/qwen-plus@1', 'window_shape': 'combined', 'context_window_tokens': 131072, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('dashscope', 'qwen-turbo'): {'provider': 'dashscope', 'model_name': 'qwen-turbo', 'capability_profile_version': 'dashscope/qwen-turbo@1', 'window_shape': 'combined', 'context_window_tokens': 1000000, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('dashscope', 'qwen3.7-max'): {'provider': 'dashscope', 'model_name': 'qwen3.7-max', 'capability_profile_version': 'dashscope/qwen3.7-max@1', 'window_shape': 'combined', 'context_window_tokens': 1000000, 'max_output_tokens': 65536, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'qwen'}, ('dashscope', 'glm-5.1'): {'provider': 'dashscope', 'model_name': 'glm-5.1', 'capability_profile_version': 'dashscope/glm-5.1@1', 'window_shape': 'combined', 'context_window_tokens': 200000, 'max_output_tokens': 131072, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'chatglm'}, ('silicon', 'Qwen/Qwen3.6-27B'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3.6-27B', 'capability_profile_version': 'silicon/qwen3.6-27b@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 65536, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'qwen'}, ('silicon', 'Pro/moonshotai/Kimi-K2.6'): {'provider': 'silicon', 'model_name': 'Pro/moonshotai/Kimi-K2.6', 'capability_profile_version': 'silicon/kimi-k2.6@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 131072, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'moonshot'}, ('deepseek', 'deepseek-chat'): {'provider': 'deepseek', 'model_name': 'deepseek-chat', 'capability_profile_version': 'deepseek/deepseek-chat@2', 'window_shape': 'combined', 'context_window_tokens': 1000000, 'max_output_tokens': 384000, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'deepseek'}, ('deepseek', 'deepseek-reasoner'): {'provider': 'deepseek', 'model_name': 'deepseek-reasoner', 'capability_profile_version': 'deepseek/deepseek-reasoner@2', 'window_shape': 'combined', 'context_window_tokens': 1000000, 'max_output_tokens': 384000, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'deepseek'}, ('deepseek', 'deepseek-v4-flash'): {'provider': 'deepseek', 'model_name': 'deepseek-v4-flash', 'capability_profile_version': 'deepseek/deepseek-v4-flash@1', 'window_shape': 'combined', 'context_window_tokens': 1000000, 'max_output_tokens': 384000, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'deepseek'}, ('deepseek', 'deepseek-v4-pro'): {'provider': 'deepseek', 'model_name': 'deepseek-v4-pro', 'capability_profile_version': 'deepseek/deepseek-v4-pro@1', 'window_shape': 'combined', 'context_window_tokens': 1000000, 'max_output_tokens': 384000, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'deepseek'}, ('silicon', 'deepseek-ai/DeepSeek-V4-Pro'): {'provider': 'silicon', 'model_name': 'deepseek-ai/DeepSeek-V4-Pro', 'capability_profile_version': 'silicon/deepseek-v4-pro-sf@1', 'window_shape': 'combined', 'context_window_tokens': 1048576, 'max_output_tokens': 384000, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'deepseek'}, ('silicon', 'deepseek-ai/DeepSeek-V4-Flash'): {'provider': 'silicon', 'model_name': 'deepseek-ai/DeepSeek-V4-Flash', 'capability_profile_version': 'silicon/deepseek-v4-flash-sf@1', 'window_shape': 'combined', 'context_window_tokens': 1048576, 'max_output_tokens': 384000, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'deepseek'}, ('silicon', 'deepseek-ai/DeepSeek-V3.2'): {'provider': 'silicon', 'model_name': 'deepseek-ai/DeepSeek-V3.2', 'capability_profile_version': 'silicon/deepseek-v3.2@1', 'window_shape': 'combined', 'context_window_tokens': 164000, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'deepseek'}, ('silicon', 'deepseek-ai/DeepSeek-V3.1-Terminus'): {'provider': 'silicon', 'model_name': 'deepseek-ai/DeepSeek-V3.1-Terminus', 'capability_profile_version': 'silicon/deepseek-v3.1-terminus@1', 'window_shape': 'combined', 'context_window_tokens': 164000, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'deepseek'}, ('silicon', 'deepseek-ai/DeepSeek-R1'): {'provider': 'silicon', 'model_name': 'deepseek-ai/DeepSeek-R1', 'capability_profile_version': 'silicon/deepseek-r1@1', 'window_shape': 'combined', 'context_window_tokens': 163840, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'deepseek'}, ('silicon', 'deepseek-ai/DeepSeek-V3'): {'provider': 'silicon', 'model_name': 'deepseek-ai/DeepSeek-V3', 'capability_profile_version': 'silicon/deepseek-v3@1', 'window_shape': 'combined', 'context_window_tokens': 164000, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'deepseek'}, ('silicon', 'deepseek-ai/DeepSeek-R1-0528-Qwen3-8B'): {'provider': 'silicon', 'model_name': 'deepseek-ai/DeepSeek-R1-0528-Qwen3-8B', 'capability_profile_version': 'silicon/deepseek-r1-0528-qwen3-8b@1', 'window_shape': 'combined', 'context_window_tokens': 131072, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'deepseek'}, ('silicon', 'Pro/deepseek-ai/DeepSeek-V3.2'): {'provider': 'silicon', 'model_name': 'Pro/deepseek-ai/DeepSeek-V3.2', 'capability_profile_version': 'silicon/deepseek-v3.2-pro@1', 'window_shape': 'combined', 'context_window_tokens': 164000, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'deepseek'}, ('silicon', 'Pro/deepseek-ai/DeepSeek-V3.1-Terminus'): {'provider': 'silicon', 'model_name': 'Pro/deepseek-ai/DeepSeek-V3.1-Terminus', 'capability_profile_version': 'silicon/deepseek-v3.1-terminus-pro@1', 'window_shape': 'combined', 'context_window_tokens': 164000, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'deepseek'}, ('silicon', 'Pro/deepseek-ai/DeepSeek-R1'): {'provider': 'silicon', 'model_name': 'Pro/deepseek-ai/DeepSeek-R1', 'capability_profile_version': 'silicon/deepseek-r1-pro@1', 'window_shape': 'combined', 'context_window_tokens': 163840, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'deepseek'}, ('silicon', 'Pro/deepseek-ai/DeepSeek-V3'): {'provider': 'silicon', 'model_name': 'Pro/deepseek-ai/DeepSeek-V3', 'capability_profile_version': 'silicon/deepseek-v3-pro@1', 'window_shape': 'combined', 'context_window_tokens': 164000, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'deepseek'}, ('silicon', 'Qwen/Qwen3.6-35B-A3B'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3.6-35B-A3B', 'capability_profile_version': 'silicon/qwen3.6-35b-a3b@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3.5-397B-A17B'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3.5-397B-A17B', 'capability_profile_version': 'silicon/qwen3.5-397b-a17b@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3.5-122B-A10B'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3.5-122B-A10B', 'capability_profile_version': 'silicon/qwen3.5-122b-a10b@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3.5-35B-A3B'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3.5-35B-A3B', 'capability_profile_version': 'silicon/qwen3.5-35b-a3b@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3.5-27B'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3.5-27B', 'capability_profile_version': 'silicon/qwen3.5-27b@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3.5-9B'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3.5-9B', 'capability_profile_version': 'silicon/qwen3.5-9b@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3.5-4B'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3.5-4B', 'capability_profile_version': 'silicon/qwen3.5-4b@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3-VL-32B-Instruct'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3-VL-32B-Instruct', 'capability_profile_version': 'silicon/qwen3-vl-32b-instruct@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3-VL-32B-Thinking'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3-VL-32B-Thinking', 'capability_profile_version': 'silicon/qwen3-vl-32b-thinking@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 32768, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3-VL-8B-Instruct'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3-VL-8B-Instruct', 'capability_profile_version': 'silicon/qwen3-vl-8b-instruct@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3-VL-8B-Thinking'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3-VL-8B-Thinking', 'capability_profile_version': 'silicon/qwen3-vl-8b-thinking@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 32768, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3-VL-30B-A3B-Instruct'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3-VL-30B-A3B-Instruct', 'capability_profile_version': 'silicon/qwen3-vl-30b-a3b-instruct@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3-VL-30B-A3B-Thinking'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3-VL-30B-A3B-Thinking', 'capability_profile_version': 'silicon/qwen3-vl-30b-a3b-thinking@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 32768, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3-Omni-30B-A3B-Instruct'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3-Omni-30B-A3B-Instruct', 'capability_profile_version': 'silicon/qwen3-omni-30b-a3b-instruct@1', 'window_shape': 'combined', 'context_window_tokens': 32768, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3-Omni-30B-A3B-Thinking'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3-Omni-30B-A3B-Thinking', 'capability_profile_version': 'silicon/qwen3-omni-30b-a3b-thinking@1', 'window_shape': 'combined', 'context_window_tokens': 32768, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3-Omni-30B-A3B-Captioner'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3-Omni-30B-A3B-Captioner', 'capability_profile_version': 'silicon/qwen3-omni-30b-a3b-captioner@1', 'window_shape': 'combined', 'context_window_tokens': 32768, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3-Coder-30B-A3B-Instruct'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3-Coder-30B-A3B-Instruct', 'capability_profile_version': 'silicon/qwen3-coder-30b-a3b-instruct@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 65536, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3-30B-A3B-Instruct-2507'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3-30B-A3B-Instruct-2507', 'capability_profile_version': 'silicon/qwen3-30b-a3b-instruct-2507@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3-32B'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3-32B', 'capability_profile_version': 'silicon/qwen3-32b@1', 'window_shape': 'combined', 'context_window_tokens': 131072, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3-14B'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3-14B', 'capability_profile_version': 'silicon/qwen3-14b@1', 'window_shape': 'combined', 'context_window_tokens': 131072, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen3-8B'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen3-8B', 'capability_profile_version': 'silicon/qwen3-8b@1', 'window_shape': 'combined', 'context_window_tokens': 131072, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen2.5-72B-Instruct-128K'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen2.5-72B-Instruct-128K', 'capability_profile_version': 'silicon/qwen2.5-72b-instruct-128k@1', 'window_shape': 'combined', 'context_window_tokens': 131072, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen2.5-72B-Instruct'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen2.5-72B-Instruct', 'capability_profile_version': 'silicon/qwen2.5-72b-instruct@1', 'window_shape': 'combined', 'context_window_tokens': 32768, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen2.5-32B-Instruct'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen2.5-32B-Instruct', 'capability_profile_version': 'silicon/qwen2.5-32b-instruct@1', 'window_shape': 'combined', 'context_window_tokens': 32768, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen2.5-14B-Instruct'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen2.5-14B-Instruct', 'capability_profile_version': 'silicon/qwen2.5-14b-instruct@1', 'window_shape': 'combined', 'context_window_tokens': 32768, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'Qwen/Qwen2.5-7B-Instruct'): {'provider': 'silicon', 'model_name': 'Qwen/Qwen2.5-7B-Instruct', 'capability_profile_version': 'silicon/qwen2.5-7b-instruct@1', 'window_shape': 'combined', 'context_window_tokens': 32768, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'THUDM/GLM-4-32B-0414'): {'provider': 'silicon', 'model_name': 'THUDM/GLM-4-32B-0414', 'capability_profile_version': 'silicon/glm-4-32b-0414@1', 'window_shape': 'combined', 'context_window_tokens': 32768, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'chatglm'}, ('silicon', 'THUDM/GLM-Z1-9B-0414'): {'provider': 'silicon', 'model_name': 'THUDM/GLM-Z1-9B-0414', 'capability_profile_version': 'silicon/glm-z1-9b-0414@1', 'window_shape': 'combined', 'context_window_tokens': 32768, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'chatglm'}, ('silicon', 'THUDM/GLM-4-9B-0414'): {'provider': 'silicon', 'model_name': 'THUDM/GLM-4-9B-0414', 'capability_profile_version': 'silicon/glm-4-9b-0414@1', 'window_shape': 'combined', 'context_window_tokens': 32768, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'chatglm'}, ('silicon', 'zai-org/GLM-5.2'): {'provider': 'silicon', 'model_name': 'zai-org/GLM-5.2', 'capability_profile_version': 'silicon/glm-5.2@1', 'window_shape': 'combined', 'context_window_tokens': 1048576, 'max_output_tokens': 131072, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'chatglm'}, ('silicon', 'zai-org/GLM-4.5V'): {'provider': 'silicon', 'model_name': 'zai-org/GLM-4.5V', 'capability_profile_version': 'silicon/glm-4.5v@1', 'window_shape': 'combined', 'context_window_tokens': 131072, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'chatglm'}, ('silicon', 'zai-org/GLM-4.5-Air'): {'provider': 'silicon', 'model_name': 'zai-org/GLM-4.5-Air', 'capability_profile_version': 'silicon/glm-4.5-air@1', 'window_shape': 'combined', 'context_window_tokens': 131072, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'chatglm'}, ('silicon', 'Pro/zai-org/GLM-5.1'): {'provider': 'silicon', 'model_name': 'Pro/zai-org/GLM-5.1', 'capability_profile_version': 'silicon/glm-5.1-pro@1', 'window_shape': 'combined', 'context_window_tokens': 202752, 'max_output_tokens': 131072, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'chatglm'}, ('silicon', 'ByteDance-Seed/Seed-OSS-36B-Instruct'): {'provider': 'silicon', 'model_name': 'ByteDance-Seed/Seed-OSS-36B-Instruct', 'capability_profile_version': 'silicon/seed-oss-36b-instruct@1', 'window_shape': 'combined', 'context_window_tokens': 524288, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'seed'}, ('silicon', 'inclusionAI/Ling-flash-2.0'): {'provider': 'silicon', 'model_name': 'inclusionAI/Ling-flash-2.0', 'capability_profile_version': 'silicon/ling-flash-2.0@1', 'window_shape': 'combined', 'context_window_tokens': 131072, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'ling'}, ('silicon', 'inclusionAI/Ling-mini-2.0'): {'provider': 'silicon', 'model_name': 'inclusionAI/Ling-mini-2.0', 'capability_profile_version': 'silicon/ling-mini-2.0@1', 'window_shape': 'combined', 'context_window_tokens': 131072, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'ling'}, ('silicon', 'MiniMaxAI/MiniMax-M2.5'): {'provider': 'silicon', 'model_name': 'MiniMaxAI/MiniMax-M2.5', 'capability_profile_version': 'silicon/minimax-m2.5@1', 'window_shape': 'combined', 'context_window_tokens': 204800, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'minimax'}, ('silicon', 'Pro/MiniMaxAI/MiniMax-M2.5'): {'provider': 'silicon', 'model_name': 'Pro/MiniMaxAI/MiniMax-M2.5', 'capability_profile_version': 'silicon/minimax-m2.5-pro@1', 'window_shape': 'combined', 'context_window_tokens': 204800, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'minimax'}, ('silicon', 'moonshotai/Kimi-K2.7-Code'): {'provider': 'silicon', 'model_name': 'moonshotai/Kimi-K2.7-Code', 'capability_profile_version': 'silicon/kimi-k2.7-code@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 32768, 'default_output_reserve_tokens': 8192, 'tokenizer_family': 'moonshot'}, ('silicon', 'nex-agi/Nex-N2-Pro'): {'provider': 'silicon', 'model_name': 'nex-agi/Nex-N2-Pro', 'capability_profile_version': 'silicon/nex-n2-pro@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'qwen'}, ('silicon', 'stepfun-ai/Step-3.5-Flash'): {'provider': 'silicon', 'model_name': 'stepfun-ai/Step-3.5-Flash', 'capability_profile_version': 'silicon/step-3.5-flash@1', 'window_shape': 'combined', 'context_window_tokens': 262144, 'max_output_tokens': 16384, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'step'}, ('silicon', 'tencent/Hunyuan-MT-7B'): {'provider': 'silicon', 'model_name': 'tencent/Hunyuan-MT-7B', 'capability_profile_version': 'silicon/hunyuan-mt-7b@1', 'window_shape': 'combined', 'context_window_tokens': 32768, 'max_output_tokens': 2048, 'default_output_reserve_tokens': 1024, 'tokenizer_family': 'hunyuan'}, ('silicon', 'tencent/Hunyuan-A13B-Instruct'): {'provider': 'silicon', 'model_name': 'tencent/Hunyuan-A13B-Instruct', 'capability_profile_version': 'silicon/hunyuan-a13b-instruct@1', 'window_shape': 'combined', 'context_window_tokens': 131072, 'max_output_tokens': 8192, 'default_output_reserve_tokens': 4096, 'tokenizer_family': 'hunyuan'}}
# Silicon Flow
SILICON_BASE_URL = 'https://api.siliconflow.cn/v1/'
SILICON_GET_URL = 'https://api.siliconflow.cn/v1/models'
# Dashcope
DASHSCOPE_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/'
DASHSCOPE_GET_URL = 'https://dashscope.aliyuncs.com/api/v1/models'
DASHSCOPE_REALTIME_BASE_URL = 'wss://dashscope.aliyuncs.com/api-ws/v1/realtime'
DASHSCOPE_STT_BASE_URL = DASHSCOPE_REALTIME_BASE_URL
# TokenPony
TOKENPONY_BASE_URL = 'https://api.tokenpony.cn/v1/'
TOKENPONY_GET_URL = 'https://api.tokenpony.cn/v1/models'
# ModelEngine
# URL path segment identifying ModelEngine northbound endpoints
# (e.g. https://host:port/open/router/v1). Endpoints behind this marker
# serve self-signed certificates, so their records must keep
# ssl_verify=False on both the create and update paths.
MODEL_ENGINE_URL_MARKER = 'open/router'
MODEL_CREATE_PERMISSION = 'model:create'
MODEL_READ_PERMISSION = 'model:read'
MODEL_UPDATE_PERMISSION = 'model:update'
MODEL_DELETE_PERMISSION = 'model:delete'
_MANAGE_ALLOWED_ROLES = ('SU', 'ADMIN')
_AUDIT_SAFE_MODEL_KEYS = ('model_name', 'display_name', 'model_repo', 'model_type', 'model_factory', 'base_url', 'provider', 'type')
_CATALOG_UNAVAILABLE_MESSAGE = 'catalog unavailable'
MODEL_CONFIG_MAPPING = {'llm': 'LLM_ID', 'embedding': 'EMBEDDING_ID', 'multiEmbedding': 'MULTI_EMBEDDING_ID', 'rerank': 'RERANK_ID', 'vlm': 'VLM_ID', 'vlm2': 'VLM2_ID', 'vlm3': 'VLM3_ID', 'vlm4': 'VLM4_ID', 'stt': 'STT_ID', 'tts': 'TTS_ID'}

# Notification
# Resource types (drive frontend deep-link target)
RESOURCE_TYPE_AGENT_REPOSITORY = 'agent_repository'
RESOURCE_TYPE_SKILL_REPOSITORY = 'skill_repository'
RESOURCE_TYPE_MCP_REPOSITORY = 'mcp_repository'
VALID_RESOURCE_TYPES = frozenset({RESOURCE_TYPE_AGENT_REPOSITORY, RESOURCE_TYPE_SKILL_REPOSITORY, RESOURCE_TYPE_MCP_REPOSITORY})
# Event types (drive title copy / icon)
EVENT_TYPE_REPOSITORY_REVIEW_APPROVED = 'repository_review_approved'
EVENT_TYPE_REPOSITORY_REVIEW_REJECTED = 'repository_review_rejected'
EVENT_TYPE_REPOSITORY_REVIEW_PENDING = 'repository_review_pending'
VALID_EVENT_TYPES = frozenset({EVENT_TYPE_REPOSITORY_REVIEW_APPROVED, EVENT_TYPE_REPOSITORY_REVIEW_REJECTED, EVENT_TYPE_REPOSITORY_REVIEW_PENDING})
# Audience scope for a notification
# all super admins (global, tenant-agnostic)
SCOPE_SU = 'SU'
# all users in a given tenant
SCOPE_TENANT = 'TENANT'
# admins of a given tenant
SCOPE_TENANT_ADMIN = 'TENANT_ADMIN'
# regular users of a given tenant
SCOPE_TENANT_USER = 'TENANT_USER'
# a specific single user
SCOPE_USER = 'USER'
VALID_NOTIFICATION_SCOPES = frozenset({SCOPE_SU, SCOPE_TENANT, SCOPE_TENANT_ADMIN, SCOPE_TENANT_USER, SCOPE_USER})
# Scopes that require a target tenant_id
TENANT_REQUIRED_SCOPES = frozenset({SCOPE_TENANT, SCOPE_TENANT_ADMIN, SCOPE_TENANT_USER})
# Role sets used to resolve receivers (user_tenant_t.user_role values)
SU_ROLES = frozenset({'SU', 'SUPER_ADMIN'})
TENANT_ADMIN_ROLES = frozenset({'ADMIN'})
TENANT_USER_ROLES = frozenset({'USER'})

# Runtime
MAX_RUNTIME_METADATA_BYTES = 64 * 1024
MAX_RUNTIME_METADATA_DEPTH = 10
MAX_RUNTIME_METADATA_KEYS = 200
MAX_RUNTIME_METADATA_ARRAY_ITEMS = 1000
MAX_RUNTIME_METADATA_KEY_LENGTH = 256
# Stable service identifiers used by startup task recovery.
CONFIG_SERVICE_NAME = 'nexent-config'
NORTHBOUND_SERVICE_NAME = 'nexent-northbound'
# Host Configuration Constants
LOCALHOST_IP = '127.0.0.1'
LOCALHOST_NAME = 'localhost'
DOCKER_INTERNAL_HOST = 'host.docker.internal'

# Skill
ASSET_OWNER_SKILL_VIEW_DENIED = {'content': '您无权限查看'}
_NOT_FOUND_TEXT = 'not found'
SKILL_DESCRIPTION_MAX_LENGTH = 1000

# Tag
DEFAULT_RESOURCE_LIBRARY_CODE = 'default_resource'
ACTIVE_DELETE_FLAG = 'N'
SYNCED_STATUS = 'synced'
KNOWLEDGE_DOCUMENT_TYPE = 'knowledge_document'
SYSTEM_BUCKET_KEYS = ('default_resource', 'knowledge_content')
DELETED_DELETE_FLAG = 'Y'
ACTIVE_STATUS = 'active'
RESOURCE_ASSIGNMENT_LIMIT = 100
NO_VALUE_TAG_NORMALIZED_VALUE = '__no_value__'
DOCUMENT_TAG_BATCH_SIZE = 500
PUBLIC_DOCUMENT_ASSIGNMENT_FIELDS = ('definition_id', 'definition_key', 'definition_name', 'selection_mode', 'value_id', 'display_value', 'value_status')

# Tool
# Listing status: not_shared (未共享), pending_review (待审核),
# rejected (审核驳回), shared (已共享)
VALID_MARKET_STATUSES = frozenset({STATUS_NOT_SHARED, STATUS_PENDING_REVIEW, STATUS_REJECTED, STATUS_SHARED})
# tool_name → [label, ...]
# Built-in labels applied by update_tool_table_from_scan_tool_list when tools are created.
# Keep in sync with: deploy/sql/migrations/v2.3_merged_migrations.sql
_category_database = {'mysql_database': ['database'], 'postgres_database': ['database'], 'mssql_database': ['database']}
_category_file = {'read_file': ['file'], 'create_file': ['file'], 'delete_file': ['file'], 'download_from_s3': ['file'], 'upload_to_s3': ['file'], 'create_directory': ['file'], 'delete_directory': ['file'], 'list_directory': ['file'], 'move_item': ['file']}
_category_search = {'deepseek_search': ['search'], 'tavily_search': ['search'], 'exa_search': ['search'], 'linkup_search': ['search'], 'search_memory': ['search'], 'knowledge_base_search': ['search']}
_category_kb = {'dify_search': ['knowledge-base'], 'datamate_search': ['knowledge-base'], 'idata_search': ['knowledge-base'], 'haotian_search': ['knowledge-base'], 'ragflow_search': ['knowledge-base'], 'aidp_search': ['knowledge-base']}
_category_multimodal = {'analyze_image': ['multimodal'], 'analyze_audio': ['multimodal'], 'analyze_video': ['multimodal'], 'analyze_text_file': ['multimodal']}
_category_email = {'get_email': ['email'], 'send_email': ['email']}
_category_memory = {'store_memory': ['memory']}
_category_terminal = {'terminal': ['terminal']}
PARALLEL_EXECUTOR_TOOL_NAME = 'parallel_executor'
SYSTEM_MANAGED_TOOL_NAMES = frozenset({'store_memory', 'search_memory', 'download_from_s3', 'upload_to_s3', PARALLEL_EXECUTOR_TOOL_NAME})
# Centralized definitions for tool parameter constraints.
# These constants are shared by tool configuration validation
# (``management.services.tool.configuration``) and the error message
# module (``contracts.errors.messages``).
# Constraint keys persisted in the DB ``ag_tool_info_t.params`` column.
# ``_extract_field_constraints`` reads these same names from Pydantic ``Field``.
TOOL_PARAM_CONSTRAINT_KEYS = ('ge', 'gt', 'le', 'lt', 'min_length', 'max_length')
# Per-constraint violation checks: (key, check_fn(value, constraint)).
# A check returns True when the value violates the constraint.
TOOL_PARAM_CONSTRAINT_RULES = (('ge', lambda v, c: v < c), ('gt', lambda v, c: v <= c), ('le', lambda v, c: v > c), ('lt', lambda v, c: v >= c), ('min_length', lambda v, c: v < c), ('max_length', lambda v, c: v > c))
# Tool Type Mapping (for display normalization)
TOOL_TYPE_MAPPING = {'mcp': 'MCP', 'langchain': 'LangChain', 'local': 'Local'}
BUILTIN_LABEL_MAP: dict[str, list[str]] = {**_category_database, **_category_file, **_category_search, **_category_kb, **_category_multimodal, **_category_email, **_category_memory, **_category_terminal}

# Voice
# Test voice file path (WAV format for volcengine STT)
TEST_VOICE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'assets', 'test.wav')
# Test PCM file path (raw PCM format for Ali STT)
TEST_PCM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'assets', 'test_voice.pcm')
