# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Launch the independent operations backend using the shared backend image."""

import logging

import uvicorn

from contracts.constants.environment import LOG_LEVEL, OPS_PORT
from ops.api.application import app


def main() -> None:
    """Run only the operations application with console logging."""
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    uvicorn.run(app, host='0.0.0.0', port=OPS_PORT, log_level=level)


if __name__ == '__main__':
    main()
