# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

MODEL_CREATE_PERMISSION = "model:create"


MODEL_READ_PERMISSION = "model:read"


MODEL_UPDATE_PERMISSION = "model:update"


MODEL_DELETE_PERMISSION = "model:delete"


_MANAGE_ALLOWED_ROLES = ("SU", "ADMIN")


_AUDIT_SAFE_MODEL_KEYS = (
    "model_name",
    "display_name",
    "model_repo",
    "model_type",
    "model_factory",
    "base_url",
    "provider",
    "type",
)


_CATALOG_UNAVAILABLE_MESSAGE = "catalog unavailable"
