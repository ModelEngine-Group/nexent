# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


import hashlib
import hmac
import time

TIMESTAMP_VALIDITY_WINDOW = 5 * 60


def calculate_hmac_signature(
    secret_key: str, access_key: str, timestamp: str, body: str
) -> str:
    """
    Calculate HMAC-SHA256 signature for AK/SK authentication.

    Returns a lowercase hex digest of length 64.
    """
    message = f"{access_key}\n{timestamp}\n{body}".encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def validate_timestamp(timestamp: str) -> bool:
    """Validate that timestamp is within allowed window."""
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False

    now = int(time.time())
    return abs(now - ts) <= TIMESTAMP_VALIDITY_WINDOW
