# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Stable AIDP tool identities shared by SDK and backend callers."""

AIDP_SEARCH_TOOL_NAME = "aidp_search"
INDEPENDENT_AIDP_SEARCH_TOOL_NAME = "ind_aidp_search"
AIDP_SEARCH_TOOL_NAMES = frozenset({AIDP_SEARCH_TOOL_NAME, INDEPENDENT_AIDP_SEARCH_TOOL_NAME})
AIDP_SEARCH_TOOL_CLASS = "AidpSearchTool"
INDEPENDENT_AIDP_SEARCH_TOOL_CLASS = "IndependentAidpSearchTool"
AIDP_SEARCH_TOOL_CLASSES = frozenset({AIDP_SEARCH_TOOL_CLASS, INDEPENDENT_AIDP_SEARCH_TOOL_CLASS})
