# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging

from contracts.error_message import ErrorMessage

logger = logging.getLogger("tool_configuration_service")

TOOL_PARAM_CONSTRAINT_ERROR_MESSAGES = ErrorMessage.get_param_constraint_messages()

_ALWAYS_HIDDEN_KNOWLEDGE_TOOLS = frozenset({"knowledge_base_search", "aidp_search"})
