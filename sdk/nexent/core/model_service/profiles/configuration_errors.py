# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Value-free errors for immutable model outlet configuration."""

class ModelOutletConflictError(ValueError):
    """An absent, stale or unavailable outlet cannot be overwritten."""

    def __init__(self):
        super().__init__("MODEL_OUTLET_VERSION_CONFLICT")

class ModelOutletValidationError(ValueError):
    """Invalid storage input without parameter or credential details."""

    def __init__(self, category="MODEL_OUTLET_INVALID", path=""):
        super().__init__("MODEL_OUTLET_INVALID")
        self.category = category
        self.path = path
