# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Executable Gateway launcher with service-local configuration and console logs."""

import logging

import uvicorn

from gateway.application import create_gateway_app
from gateway.configuration import load_settings


def main():
    settings = load_settings()
    if settings.auth_enabled:
        settings.signing_key()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("gateway").info("Starting Gateway on %s:%s", settings.host, settings.port)
    uvicorn.run(create_gateway_app(settings=settings), host=settings.host, port=settings.port,
                log_level="info", proxy_headers=False)


if __name__ == "__main__":
    main()
