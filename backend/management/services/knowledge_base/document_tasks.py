# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Process-local document deletion tasks shared by file and index cleanup."""

import asyncio
from typing import Dict

_document_delete_tasks: Dict[str, asyncio.Task] = {}
