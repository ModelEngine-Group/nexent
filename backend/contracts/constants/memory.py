# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


USER_DREAMING_SCOPE = "__user__"


# Memory Feature
MEMORY_SWITCH_KEY = "MEMORY_SWITCH"
DREAMING_SWITCH_KEY = "DREAMING_SWITCH"
MEMORY_AGENT_SHARE_KEY = "MEMORY_AGENT_SHARE"
DISABLE_AGENT_ID_KEY = "DISABLE_AGENT_ID"
DISABLE_USERAGENT_ID_KEY = "DISABLE_USERAGENT_ID"
EXTERNAL_PROVIDER_TOP_K_KEY = "EXTERNAL_PROVIDER_TOP_K"
DEFAULT_MEMORY_SWITCH_KEY = "Y"
DEFAULT_DREAMING_SWITCH_KEY = "Y"
DEFAULT_MEMORY_AGENT_SHARE_KEY = "always"
DEFAULT_EXTERNAL_PROVIDER_TOP_K = 20
# Boolean value representations for configuration parsing
BOOLEAN_TRUE_VALUES = {"true", "1", "y", "yes", "on"}

# External provider protocol defaults. Provider records control whether each
# configured integration participates in search and ingest.
EXTERNAL_MEMORY_DEFAULT_ALLOWED_UNIT_TYPES = (
    "agent",
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

# Memory Search Status Messages (for i18n placeholders)
MEMORY_SEARCH_START_MSG = "<MEM_START>"
MEMORY_SEARCH_DONE_MSG = "<MEM_DONE>"
MEMORY_SEARCH_FAIL_MSG = "<MEM_FAILED>"
