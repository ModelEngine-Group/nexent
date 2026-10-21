# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""OpenAPI response contracts for controlled tag conflicts."""

from contracts.models import TagHTTPConflictResponse


TAG_CONFLICT_RESPONSES = {409: {"model": TagHTTPConflictResponse}}
