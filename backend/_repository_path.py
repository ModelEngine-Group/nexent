# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Locate shared packages when a service is started as a script."""

import sys
from pathlib import Path


def add_repository_root() -> None:
    repository_root = str(Path(__file__).resolve().parents[1])
    if repository_root not in sys.path:
        sys.path.insert(0, repository_root)
