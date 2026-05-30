# -*- coding: utf-8 -*-
"""
测试工具模块 - 从 test_multi_run.py 抽提的可复用组件

此模块提供了构建 Agent 测试所需的基础功能：
1. Prompt 构建（system prompt, prompt templates）
2. AgentRunInfo 构造
3. 消息流处理和统计
"""
import sys
import io
import json
import os
import re
from datetime import datetime
from typing import AsyncIterator, Callable, Optional

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from jinja2 import Template, StrictUndefined
from smolagents.utils import BASE_BUILTIN_MODULES
from dotenv import load_dotenv
import string

# ============ Environment Setup ============
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
# temp_scripts 在 sdk/nexent/core/agents/ 下，需要向上 4 级到达 sdk 目录
SDK_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS_DIR))))
# sdk 的父目录即为项目根目录
PROJECT_ROOT = os.path.dirname(SDK_DIR)
BACKEND_PATH = os.path.join(PROJECT_ROOT, "backend")

if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if BACKEND_PATH not in sys.path:
    sys.path.insert(0, BACKEND_PATH)

from utils.prompt_template_utils import get_agent_prompt_template
from nexent.core.agents.agent_model import (
    AgentRunInfo, AgentConfig, ModelConfig, AgentHistory, ToolConfig
)



from nexent.core.agents.run_agent import agent_run
from nexent.core.utils.observer import MessageObserver
from nexent.core.agents.agent_context import ContextManagerConfig
import logging
logging.getLogger("smolagents").setLevel(logging.WARNING)
import random 
load_dotenv()