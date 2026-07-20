import base64
import ipaddress
import logging
import os
import socket
from http import HTTPStatus
from typing import Optional
from urllib.parse import urlparse, urlunparse

import aiohttp

from consts.const import DATA_PROCESS_SERVICE
from consts.const import MODEL_CONFIG_MAPPING
from database.model_management_db import get_model_by_model_id
from utils.config_utils import tenant_config_manager, get_model_name_from_config

from nexent import MessageObserver
from nexent.core.models import OpenAIVLModel

logger = logging.getLogger("image_service")


# ---------------------------------------------------------------------------
# AIDP image proxying
# ---------------------------------------------------------------------------
# AIDP serves images behind GET endpoints that require ``Authorization:
# Bearer <AIDP_API_KEY>``. The chunk-level URLs built by AidpSearchTool
# look like ``{AIDP_SERVER_URL}/KnowledgeBase/Tenants/aidp/KnowledgeBases/...``.
# When the image proxy sees such a URL, we short-circuit the generic
# data-processing proxy (which would not know how to authenticate) and
# fetch the image ourselves with the env-supplied api key.
#
# Environment variables reused here match those in
# ``sdk/nexent/core/tools/aidp_search_tool.py`` so a single deployment
# config drives both the search tool and the image proxy.
_AIDP_KB_PATH_PREFIX = "/KnowledgeBase/Tenants/"


def _is_aidp_url(decoded_url: str) -> bool:
    """Return True when ``decoded_url`` points at the configured AIDP host
    and lives under the knowledge-base image path.

    Both scheme://host AND the ``/KnowledgeBase/Tenants/`` path prefix must
    match; otherwise we fall through to the generic proxy so an accidental
    base_url typo never leaks the AIDP api key to an unrelated host.
    """
    aidp_base = os.environ.get("AIDP_SERVER_URL", "").rstrip("/")
    if not aidp_base:
        return False
    try:
        parsed = urlparse(decoded_url)
        base_parsed = urlparse(aidp_base)
    except Exception:
        return False
    if (parsed.scheme, parsed.netloc) != (base_parsed.scheme, base_parsed.netloc):
        return False
    return _AIDP_KB_PATH_PREFIX in parsed.path


def _get_aidp_api_key() -> str:
    return os.environ.get("AIDP_API_KEY", "")


async def _fetch_aidp_image(url: str):
    """Fetch an AIDP image using the env-supplied Bearer token.

    Mirrors :func:`_fetch_image_directly` in shape but (a) adds the
    ``Authorization`` header and (b) disables redirects to prevent the
    Bearer token from leaking if AIDP responds with a 30x to another
    host. ``trust_env`` is off so proxy environment variables do not
    re-route the internal request.
    """
    api_key = _get_aidp_api_key()
    if not api_key:
        logger.error("AIDP_API_KEY is not configured; cannot fetch AIDP image")
        return {"success": False, "error": "AIDP API key not configured"}

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
        async with session.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            allow_redirects=False,
        ) as response:
            if response.status != HTTPStatus.OK:
                error_text = await response.text()
                logger.error(
                    "Failed to fetch AIDP image (status=%s): %s",
                    response.status,
                    error_text[:200],
                )
                return {"success": False, "error": "Failed to fetch AIDP image"}

            content = await response.read()
            content_type = response.headers.get("Content-Type", "image/jpeg")
            return {
                "success": True,
                "base64": base64.b64encode(content).decode("utf-8"),
                "content_type": content_type,
            }


def _validate_loopback_url(decoded_url: str) -> str | None:
    """Validate that ``decoded_url`` is a genuine loopback URL and return a
    rewritten URL whose host is a literal IPv4 loopback address, or ``None``
    when the input is not safe to fetch directly.

    This is a defense-in-depth check for the fast-path that bypasses the
    data-processing service. The fast-path is only intended for loopback
    images (e.g. served by an in-process component), so we must verify:

    * The scheme is ``http`` or ``https``.
    * The hostname resolves to one or more IPv4 addresses, and **every**
      resolved address falls inside the standard IPv4 loopback range
      ``127.0.0.0/8``. Mixed results are rejected to prevent an attacker
      from racing DNS to a private address.
    * The URL is rewritten so the host portion is a literal loopback IP.
      This both (a) removes the user-controlled hostname from the final
      request URL that ``aiohttp`` issues, and (b) blocks DNS rebinding
      attacks where the hostname is re-resolved to a private address
      between validation and the actual ``GET``.
    """
    try:
        parsed = urlparse(decoded_url)
    except Exception:
        return None

    if parsed.scheme not in {"http", "https"}:
        return None

    hostname = parsed.hostname
    if not hostname:
        return None

    try:
        resolved_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return None

    if not resolved_infos:
        return None

    safe_addresses: list[str] = []
    for info in resolved_infos:
        sockaddr = info[4]
        candidate = sockaddr[0]
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            return None
        if ip.version != 4 or not ip.is_loopback:
            return None
        safe_addresses.append(candidate)

    # Prefer the literal 127.0.0.1 to keep the rewritten URL stable when
    # the hostname resolves to multiple loopback aliases.
    chosen_ip = (
        "127.0.0.1" if "127.0.0.1" in safe_addresses else safe_addresses[0]
    )

    port = parsed.port
    netloc = f"{chosen_ip}:{port}" if port is not None else chosen_ip

    return urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


async def _fetch_image_directly(safe_url: str):
    """Fetch an image from a previously validated loopback URL.

    ``safe_url`` MUST be the output of :func:`_validate_loopback_url` so that
    it contains a literal loopback IPv4 address and is no longer
    user-controlled. Redirects are disabled and ``trust_env`` is off to
    ensure the request never leaks to a private/external host through
    proxy variables or HTTP 30x responses.
    """
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(
        timeout=timeout, trust_env=False
    ) as session:
        async with session.get(safe_url, allow_redirects=False) as response:
            if response.status != HTTPStatus.OK:
                error_text = await response.text()
                logger.error(
                    "Failed to fetch loopback image directly: %s", error_text
                )
                return {"success": False, "error": "Failed to fetch image"}

            content = await response.read()
            content_type = response.headers.get("Content-Type", "image/jpeg")
            return {
                "success": True,
                "base64": base64.b64encode(content).decode("utf-8"),
                "content_type": content_type,
            }


async def proxy_image_impl(decoded_url: str):
    # Fast path #1: AIDP image URLs need a Bearer token. Short-circuit here
    # before the loopback check because the AIDP host may happen to resolve
    # to a loopback address in dev, and we'd skip the auth header if that
    # branch matched first.
    if _is_aidp_url(decoded_url):
        return await _fetch_aidp_image(decoded_url)

    # Fast path #2: loopback URLs (in-process / local dev), fetch directly.
    # This avoids an extra hop through the data-processing service for
    # local images. For any other URL (including all external / knowledge-
    # base images such as AIDP from a different deployment), fall back to
    # the data-processing service proxy, which is the existing safe path
    # that CodeQL does not flag.
    safe_url = _validate_loopback_url(decoded_url)
    if safe_url is not None:
        return await _fetch_image_directly(safe_url)

    # Create session to call the data processing service
    async with aiohttp.ClientSession() as session:
        # Call the data processing service to load the image
        data_process_url = f"{DATA_PROCESS_SERVICE}/tasks/load_image?url={decoded_url}"

        async with session.get(data_process_url) as response:
            if response.status != HTTPStatus.OK:
                error_text = await response.text()
                logger.error(
                    f"Failed to fetch image from data process service: {error_text}")
                return {"success": False, "error": "Failed to fetch image or image format not supported"}

            result = await response.json()
            return result


def _get_model_config_by_id(tenant_id, model_id, expected_model_type):
    if not model_id:
        return None

    model_config = get_model_by_model_id(int(model_id), tenant_id)
    if not model_config:
        raise ValueError(f"Model not found: {model_id}")
    if model_config.get("model_type") != expected_model_type:
        raise ValueError(f"Selected model {model_id} is not a {expected_model_type} model")
    return model_config


def _build_vlm_model(vlm_model_config):
    if not vlm_model_config:
        return None
    return OpenAIVLModel(
        observer=MessageObserver(),
        model_id=get_model_name_from_config(
            vlm_model_config) if vlm_model_config else "",
        api_base=vlm_model_config.get("base_url", ""),
        api_key=vlm_model_config.get("api_key", ""),
        temperature=0.7,
        top_p=0.7,
        frequency_penalty=0.5,
        max_tokens=512,
        ssl_verify=vlm_model_config.get("ssl_verify", True),
        model_factory=vlm_model_config.get("model_factory"),
        display_name=vlm_model_config.get("display_name"),
    )


def get_vlm_model(tenant_id: str, model_id: Optional[int] = None):
    """Return the configured image understanding model for AnalyzeImageTool.

    The first multimodal model slot is still stored under MODEL_CONFIG_MAPPING["vlm"]
    for compatibility, but it is the user-facing image understanding configuration.
    """
    if model_id:
        vlm_model_config = _get_model_config_by_id(tenant_id, model_id, "vlm")
    else:
        vlm_model_config = tenant_config_manager.get_model_config(
            key=MODEL_CONFIG_MAPPING["vlm"], tenant_id=tenant_id)
    return _build_vlm_model(vlm_model_config)


def get_image_understanding_model(tenant_id: str):
    return get_vlm_model(tenant_id=tenant_id)


def get_video_understanding_model(tenant_id: str, model_id: Optional[int] = None):
    """Return the configured video understanding model for multimodal tools."""
    if model_id:
        vlm_model_config = _get_model_config_by_id(tenant_id, model_id, "vlm3")
    else:
        vlm_model_config = tenant_config_manager.get_model_config(
            key=MODEL_CONFIG_MAPPING["vlm3"], tenant_id=tenant_id)
    return _build_vlm_model(vlm_model_config)
