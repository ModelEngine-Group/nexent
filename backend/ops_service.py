# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Launch the independent operations backend using the shared backend image."""

import uvicorn

from contracts.constants.environment import OPS_PORT
from ops.api.application import app
from ops.logging import build_logging_config


def main() -> None:
    """Run operations with shared console and rotating file logging."""
    uvicorn.run(app, host='0.0.0.0', port=OPS_PORT, log_config=build_logging_config())


if __name__ == '__main__':
    main()
