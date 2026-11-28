# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


import logging
from contracts.constants.constants import LANGUAGE
from typing import Optional
from fastapi import Request

# ``get_request_id`` and ``get_client_ip`` are pure HTTP plumbing and the
# shared Web layer needs them to write ``requestId`` into error bodies and to
# resolve audit client addresses, so their definitions live with that layer
# (the shared layer must not import business source). Re-exported here so the
# existing management call sites keep working.
from backend.http.server.request_context import (  # noqa: F401 - re-exported
    REQUEST_ID_HEADER,
    get_client_ip,
    get_request_id,
)


def get_user_language(request: Request = None) -> str:
    """
    Get user language preference from request

    Args:
        request: FastAPI request object, used to get cookie

    Returns:
        str: Language code ('zh' or 'en'), default to 'zh'
    """
    default_language = LANGUAGE["ZH"]

    # Read language setting from cookie
    if request:
        try:
            if hasattr(request, "cookies") and request.cookies:
                cookie_locale = request.cookies.get("NEXT_LOCALE")
                if cookie_locale and cookie_locale in [LANGUAGE["ZH"], LANGUAGE["EN"]]:
                    return cookie_locale
        except (AttributeError, TypeError) as e:
            logging.warning(f"Error reading language from cookies: {e}")

    return default_language
