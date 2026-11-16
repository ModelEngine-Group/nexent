# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Launch the independent operations backend using the shared backend image."""

import uvicorn

from contracts.constants.environment import OPS_PORT
from infrastructure.logging import get_uvicorn_logging_config
from ops.api.application import app


def main() -> None:
    """Run operations with shared console and rotating file logging."""
    uvicorn.run(app, host='0.0.0.0', port=OPS_PORT, log_config=get_uvicorn_logging_config(categories=['ops']))


if __name__ == '__main__':
    main()
