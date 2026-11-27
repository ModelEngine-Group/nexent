# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

LOCAL_SESSION_PREFIX = "local:"


def is_local_session_id(session_id: object) -> bool:
    """Identify a local account session by its signed JWT session identifier."""
    return isinstance(session_id, str) and session_id.startswith(LOCAL_SESSION_PREFIX)
