"""
Scheduler frequency constants
Centralized definition for auto-summary frequency options
"""
from datetime import timedelta

# 核心频率配置：包含值、时间间隔、显示标签；这是唯一的数据源，所有其他格式都从这里生成
SUMMARY_FREQUENCY_CONFIG = [
    {"value": "1h", "timedelta": timedelta(hours=1), "label": "1h"},
    {"value": "3h", "timedelta": timedelta(hours=3), "label": "3h"},
    {"value": "6h", "timedelta": timedelta(hours=6), "label": "6h"},
    {"value": "1d", "timedelta": timedelta(days=1), "label": "1d"},
    {"value": "1w", "timedelta": timedelta(weeks=1), "label": "1w"},
]

# 从配置生成有效频率列表（用于验证）
VALID_SUMMARY_FREQUENCIES = [item["value"] for item in SUMMARY_FREQUENCY_CONFIG] + [None]

# 从配置生成频率到timedelta的映射（直接取值，无需循环转换）
FREQUENCY_MAP = {item["value"]: item["timedelta"] for item in SUMMARY_FREQUENCY_CONFIG}

# 从配置生成API返回的选项（用于前端）
SUMMARY_FREQUENCY_OPTIONS_FOR_API = [
    {"value": "disabled", "label": "关闭"},
] + [{"value": item["value"], "label": item["value"]} for item in SUMMARY_FREQUENCY_CONFIG]

# Scheduler检查间隔（秒）
SCHEDULER_CHECK_INTERVAL_SECONDS = 30 * 60
