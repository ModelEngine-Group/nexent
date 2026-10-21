# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

COMMITTED_STATUS = "COMMITTED"


DELETED_STATUS = "DELETED"


class StorageObjectConflictError(ValueError):
    """Raised when an object identity is already bound to different accounting data."""
