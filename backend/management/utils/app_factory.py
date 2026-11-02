# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Legacy imports for the canonical shared Web application factory."""

from infrastructure.web.application import create_app, register_exception_handlers

__all__ = ["create_app", "register_exception_handlers"]
