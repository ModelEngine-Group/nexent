"""
Scheduler frequency constants
Centralized definition for auto-summary frequency options
"""
from datetime import timedelta

# Core frequency config: includes value, timedelta, and label; this is the single source of truth
SUMMARY_FREQUENCY_CONFIG = [
    {"value": "1h", "timedelta": timedelta(hours=1), "label": "1h"},
    {"value": "3h", "timedelta": timedelta(hours=3), "label": "3h"},
    {"value": "6h", "timedelta": timedelta(hours=6), "label": "6h"},
    {"value": "1d", "timedelta": timedelta(days=1), "label": "1d"},
    {"value": "1w", "timedelta": timedelta(weeks=1), "label": "1w"},
]

# Generate valid frequency list from config (for validation)
VALID_SUMMARY_FREQUENCIES = [item["value"] for item in SUMMARY_FREQUENCY_CONFIG] + [None]

# Generate frequency to timedelta mapping from config (direct value, no loop conversion needed)
FREQUENCY_MAP = {item["value"]: item["timedelta"] for item in SUMMARY_FREQUENCY_CONFIG}

# Generate API options from config (for frontend)
SUMMARY_FREQUENCY_OPTIONS_FOR_API = [
    {"value": "disabled", "label": "Disabled"},
] + [{"value": item["value"], "label": item["value"]} for item in SUMMARY_FREQUENCY_CONFIG]

# Scheduler check interval (seconds)
SCHEDULER_CHECK_INTERVAL_SECONDS = 30 * 60
