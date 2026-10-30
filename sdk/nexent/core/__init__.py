# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from .utils.observer import MessageObserver, ProcessType

__all__ = ["MessageObserver", "ProcessType"]

# Lazy imports to avoid circular dependencies
def get_core_agent():
    from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
    return CoreAgent

def get_openai_model():
    from .models import OpenAIModel
    return OpenAIModel
