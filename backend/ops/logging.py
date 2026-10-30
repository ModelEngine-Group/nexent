# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Configure operations console and persistent logs with shared rotation rules."""

from infrastructure.logging import get_uvicorn_logging_config


def build_logging_config() -> dict:
    """Route application, server and access records to the same ops log file."""
    config = get_uvicorn_logging_config(categories=['ops'])
    config['loggers'] = {
        name: {
            'handlers': ['console', 'file_ops'],
            'level': config['root']['level'],
            'propagate': False,
        }
        for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access')
    }
    return config
