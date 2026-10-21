# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


import logging
from contracts.localization import LANGUAGE
from typing import Optional
from fastapi import Request

def get_client_ip(request: Optional[Request]) -> str:
    """Resolve the client IP: first hop of X-Forwarded-For, then X-Real-IP, then peer.

    X-Forwarded-For is attacker-controllable, so the result is a lead for
    investigation, not proof of origin.
    """
    if request is None:
        return ""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        first_hop = forwarded_for.split(",")[0].strip()
        if first_hop:
            return first_hop
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else ""


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
