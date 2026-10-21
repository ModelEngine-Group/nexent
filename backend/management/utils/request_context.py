# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


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
