# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compatibility import for the proxy-only Gateway application."""

from gateway.edge import app as northbound_app

__all__ = ["northbound_app"]
