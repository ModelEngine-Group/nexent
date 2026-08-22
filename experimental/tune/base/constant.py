#!/usr/bin/python3.10
# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved

class TuneConstant:
    """prompt tuning constants"""

    """message roles constant"""
    SYSTEM_ROLE = "system"
    ASSISTANT_ROLE = "assistant"
    USER_ROLE = "user"
    TOOL_ROLE = "tools"

    """message keys constant"""
    MESSAGE_KEY = "messages"
    TOOLS_KEY = "tools"
    MESSAGE_ROLE_KEY = "role"
    MESSAGE_CONTENT_KEY = "content"
    MESSAGE_TOOL_CALLS_KEY = "tool_calls"
    QUESTION_KEY = "question"
    REASON_KEY = "reason"
    LABEL_KEY = "label"
    NAME_KEY = "name"
    VARIABLE_KEY = "variable"
    PREDICT_KEY = "predict"

    """optimizer parameters type constant"""
    ROOT_CASE_INDEX: int = -1
    EVALUATION_METHOD_TEXT = "TEXT"
    EVALUATION_METHOD_LLM = "LLM"
    OPTIMIZATION_METHOD_JOINT = "JOINT"
    RAW_PROMPT_TAG = "<RAW_PROMPT>"

    """optimizer parameters default value constant"""
    DEFAULT_EXAMPLE_NUM: int = 0
    DEFAULT_COT_EXAMPLE_NUM: int = 0
    DEFAULT_ITERATION_NUM: int = 3
    DEFAULT_MAX_SAMPLED_EXAMPLE_NUM: int = 10
    DEFAULT_LLM_PARALLEL_DEGREE: int = 1
    DEFAULT_LLM_CALL_RETRY_NUM: int = 5
    DEFAULT_COT_EXAMPLE_RATIO: float = 0.25
    DEFAULT_MAX_CASE_NUM: int = 300
    DEFAULT_OPTIMIZATION_METHOD = OPTIMIZATION_METHOD_JOINT
    DEFAULT_EVALUATION_METHOD = EVALUATION_METHOD_LLM
    DEFAULT_MAX_RUNNING_TASK_NUM: int = 64

    """optimizer parameters threshold constant"""
    MIN_ITERATION_NUM: int = 1
    MAX_ITERATION_NUM: int = 20
    MIN_LLM_CALL_RETRY_NUM: int = 1
    MAX_LLM_CALL_RETRY_NUM: int = 10
    MIN_LLM_PARALLEL_DEGREE: int = 1
    MAX_LLM_PARALLEL_DEGREE: int = 10
    MIN_EXAMPLE_NUM: int = 0
    MAX_EXAMPLE_NUM: int = 10
    MIN_COT_EXAMPLE_NUM: int = 0
    MAX_COT_EXAMPLE_NUM: int = 5

    DEFAULT_TOOL_CALL_PROMPT_PREFIX: str = """
    API/工具说明:\n{{APIS_DESCRIPTION}}
    """

class TaskStatus:
    """optimizer task status"""
    TASK_STATUS = "status"
    TASK_RUNNING = "running"
    TASK_FINISHED = "finished"
    TASK_FAILED = "failed"
    TASK_STOPPED = "stopped"
    TASK_STOPPING = "stopping"
    TASK_DELETED = "deleted"
    TASK_QUEUED = "queued"