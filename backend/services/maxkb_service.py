"""MaxKB admin integration helpers.

This module wraps the third-party MaxKB admin ``force_logout`` endpoint so the
application can terminate the corresponding MaxKB session when a Nexent user
logs out. The call is best-effort: any failure is logged as a warning and
swallowed by callers so the local logout flow stays idempotent.
"""

import json
import logging
import ssl
import urllib.error
import urllib.request

from consts.const import (
    MAXKB_LOGOUT_TIMEOUT_S,
    MAXKB_LOGOUT_URL,
    MAXKB_SYSTEM_API_KEY,
    OAUTH_CA_BUNDLE,
    OAUTH_SSL_VERIFY,
)

logger = logging.getLogger(__name__)


def _build_ssl_context() -> ssl.SSLContext | None:
    """Build the SSL context for the MaxKB request based on OAuth settings.

    Reuses the same trust/verification settings as OAuth so an operator who
    needs to talk to MaxKB over a private CA can point ``OAUTH_CA_BUNDLE`` at
    the bundle without configuring MaxKB separately.
    """
    if not OAUTH_SSL_VERIFY:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if OAUTH_CA_BUNDLE:
        return ssl.create_default_context(cafile=OAUTH_CA_BUNDLE)
    return None


def is_maxkb_logout_configured() -> bool:
    """Return True when both the URL and system API key are configured."""
    return bool(MAXKB_LOGOUT_URL) and bool(MAXKB_SYSTEM_API_KEY)


def force_logout_maxkb_user(username: str) -> bool:
    """Invoke MaxKB's admin force-logout endpoint for ``username``.

    Args:
        username: The user identifier MaxKB expects in the ``username`` field.
            For MaxKB this is typically the user's email address.

    Returns:
        True when the request succeeds (HTTP 2xx). False when the integration
        is not configured, the input is empty, or the upstream call fails.
        All failures are logged at warning level so callers can treat the
        call as best-effort.
    """
    if not username:
        logger.info("MaxKB force-logout skipped: empty username")
        return False

    if not is_maxkb_logout_configured():
        logger.info(
            "MaxKB force-logout skipped: MAXKB_LOGOUT_URL or MAXKB_SYSTEM_API_KEY not set"
        )
        return False

    payload = json.dumps({"username": username}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {MAXKB_SYSTEM_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    req = urllib.request.Request(
        MAXKB_LOGOUT_URL, data=payload, headers=headers, method="POST"
    )

    try:
        with urllib.request.urlopen(
            req, timeout=MAXKB_LOGOUT_TIMEOUT_S, context=_build_ssl_context()
        ) as resp:
            status_code = getattr(resp, "status", None) or resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")
            if 200 <= int(status_code) < 300:
                logger.info(
                    "MaxKB force-logout succeeded for username=%s status=%s body=%s",
                    username,
                    status_code,
                    body,
                )
                return True
            logger.warning(
                "MaxKB force-logout returned non-2xx for username=%s status=%s body=%s",
                username,
                status_code,
                body,
            )
            return False
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        logger.warning(
            "MaxKB force-logout HTTPError username=%s status=%s body=%s",
            username,
            getattr(exc, "code", "?"),
            body,
        )
        return False
    except Exception as exc:
        logger.warning(
            "MaxKB force-logout failed for username=%s: %s", username, exc
        )
        return False