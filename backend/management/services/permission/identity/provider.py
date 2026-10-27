# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging

import httpx
from contracts.constants.environment import SERVICE_ROLE_KEY, SUPABASE_KEY, SUPABASE_URL
from supabase import create_client
from supabase.lib.client_options import SyncClientOptions

logger = logging.getLogger(__name__)


def _build_supabase_options() -> SyncClientOptions:
    """Build ClientOptions for the server-side Supabase client.

    Two things matter here:

    1. ``httpx.Client`` is built with ``trust_env=False`` and ``proxy=None``
       so Supabase always talks to ``SUPABASE_URL`` directly and does not
       pick up the Windows system proxy (e.g. Clash on 127.0.0.1:7897),
       which would otherwise hang local GoTrue calls until timeout.

    2. ``auto_refresh_token=False`` and ``persist_session=False`` disable
       the supabase-py background refresh tick. The refresh tick calls
       ``/auth/v1/token?grant_type=refresh_token`` whenever the in-memory
       session is close to expiry, which is *not* what we want on the
       backend: the new ``refresh_token`` is rotated server-side but the
       caller (frontend / BFF) never learns about it. The next frontend
       refresh attempt then sends the now-consumed ``refresh_token`` and
       Supabase rejects it with ``refresh_token_already_used``. Keeping
       the client passive means every refresh must flow through the
       explicit ``/api/user/refresh_token`` endpoint, which has full
       ownership of the rotated tokens and updates the cookies atomically.
    """
    http_client = httpx.Client(
        trust_env=False,
        proxy=None,
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    )
    return SyncClientOptions(
        httpx_client=http_client,
        auto_refresh_token=False,
        persist_session=False,
    )


def get_supabase_client():
    """Get Supabase client instance with regular key (user-context operations)."""
    try:
        return create_client(
            SUPABASE_URL, SUPABASE_KEY, options=_build_supabase_options()
        )
    except Exception as e:
        logging.error(f"Failed to create Supabase client: {str(e)}")
        return None


def get_supabase_admin_client():
    """Get Supabase client instance with service role key for admin operations."""
    try:
        return create_client(
            SUPABASE_URL, SERVICE_ROLE_KEY, options=_build_supabase_options()
        )
    except Exception as e:
        logging.error(f"Failed to create Supabase admin client: {str(e)}")
        return None


def delete_supabase_user(user_id: str) -> bool:
    """Delete an auth user during rollback of a failed local registration."""
    if not user_id:
        return False

    try:
        admin_client = get_supabase_admin_client()
        if not admin_client or not hasattr(admin_client.auth, "admin"):
            logger.warning(
                "Supabase admin client unavailable while rolling back user %s", user_id
            )
            return False
        admin_client.auth.admin.delete_user(user_id)
        logger.info("Rolled back Supabase user %s after failed registration", user_id)
        return True
    except Exception as exc:
        logger.error("Failed to roll back Supabase user %s: %s", user_id, exc)
        return False
