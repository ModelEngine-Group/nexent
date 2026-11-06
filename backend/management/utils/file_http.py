# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
import re
from http import HTTPStatus
from typing import Optional
from urllib.parse import quote, urlparse, urlunparse

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def build_storage_proxy_url(presigned_url: str, storage_endpoint: Optional[str]) -> httpx.URL:
    """Pin the request authority to configured storage without rewriting its signature."""
    try:
        origin = httpx.URL(storage_endpoint or "")
        if (
            origin.scheme not in ("http", "https") or not origin.host
            or origin.userinfo or origin.fragment or origin.query or origin.path != "/"
        ):
            raise ValueError("Invalid storage endpoint")
    except (httpx.InvalidURL, ValueError):
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail="Storage endpoint is not configured correctly"
        ) from None

    try:
        if not presigned_url or "\\" in presigned_url or any(ord(char) <= 32 or ord(char) == 127 for char in presigned_url):
            raise ValueError("Invalid URL characters")
        parsed = urlparse(presigned_url)
        target = httpx.URL(presigned_url)
        if (
            parsed.username is not None or "#" in presigned_url
            or target.scheme != origin.scheme or target.host != origin.host or target.port != origin.port
        ):
            raise ValueError("URL must use configured storage origin")
    except (httpx.InvalidURL, ValueError):
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="presigned_url must use the configured storage endpoint"
        ) from None

    # Copy only the object path and signed query; the authority always comes from server configuration.
    return origin.copy_with(raw_path=target.raw_path)


def build_content_disposition_header(filename: Optional[str], inline: bool = False) -> str:
    """
    Build a Content-Disposition header that keeps the original filename.

    Args:
        filename: Original filename to include in header
        inline: If True, use 'inline' disposition (for preview); otherwise 'attachment' (for download)

    - ASCII filenames are returned directly.
    - Non-ASCII filenames include both an ASCII fallback and RFC 5987 encoded value
      so modern browsers keep the original name.
    """
    disposition = "inline" if inline else "attachment"
    safe_name = (filename or "download").strip() or "download"

    def _sanitize_ascii(value: str) -> str:
        # Replace problematic characters that break HTTP headers
        # Remove control characters (newlines, carriage returns, tabs, etc.)
        # Remove control characters (0x00-0x1F and 0x7F)
        sanitized = re.sub(r"[\x00-\x1F\x7F]", "", value)
        # Replace problematic characters that break HTTP headers
        sanitized = sanitized.replace("\\", "_").replace('"', "_")
        # Remove leading/trailing spaces and dots (Windows filename restrictions)
        sanitized = sanitized.strip(" .")
        return sanitized if sanitized else "download"

    try:
        safe_name.encode("ascii")
        return f'{disposition}; filename="{_sanitize_ascii(safe_name)}"'
    except UnicodeEncodeError:
        try:
            encoded = quote(safe_name, safe="")
        except Exception:
            # quote failure, fallback to sanitized ASCII only
            logger.warning("Failed to encode filename '%s', using fallback", safe_name)
            return f'{disposition}; filename="{_sanitize_ascii(safe_name)}"'

        fallback = _sanitize_ascii(safe_name.encode("ascii", "ignore").decode("ascii") or "download")
        return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Failed to encode filename '%s': %s. Using fallback.",
            safe_name,
            exc,
        )
        return f'{disposition}; filename="download"'


def _build_object_etag(object_name: str) -> str:
    """Build a latin-1-safe ETag from a MinIO object name."""
    return f'"{quote(object_name, safe="/")}"'


def _ensure_http_scheme(raw_url: str) -> str:
    """
    Ensure the provided Datamate URL has an explicit HTTP or HTTPS scheme.
    """
    candidate = (raw_url or "").strip()
    if not candidate:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="URL cannot be empty")

    parsed = urlparse(candidate)
    if parsed.scheme:
        if parsed.scheme not in ("http", "https"):
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="URL must start with http:// or https://")
        return candidate

    if candidate.startswith("//"):
        return f"http:{candidate}"

    return f"http://{candidate}"


def _normalize_datamate_download_url(raw_url: str) -> str:
    """
    Normalize Datamate download URL to ensure it follows /data-management/datasets/{datasetId}/files/{fileId}/download
    """
    normalized_source = _ensure_http_scheme(raw_url)
    parsed_url = urlparse(normalized_source)
    path_segments = [segment for segment in parsed_url.path.split("/") if segment]

    if "data-management" not in path_segments:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Invalid Datamate URL: missing 'data-management' segment"
        )

    try:
        dm_index = path_segments.index("data-management")
        datasets_index = path_segments.index("datasets", dm_index)
        dataset_id = path_segments[datasets_index + 1]
        files_index = path_segments.index("files", datasets_index)
        file_id = path_segments[files_index + 1]
    except (ValueError, IndexError):
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Invalid Datamate URL: unable to parse dataset_id or file_id"
        )

    prefix_segments = path_segments[:dm_index]
    prefix_path = "/" + "/".join(prefix_segments) if prefix_segments else ""
    normalized_path = f"{prefix_path}/data-management/datasets/{dataset_id}/files/{file_id}/download"

    normalized_url = urlunparse((parsed_url.scheme, parsed_url.netloc, normalized_path, "", "", ""))

    return normalized_url


def _build_datamate_url_from_parts(base_url: str, dataset_id: str, file_id: str) -> str:
    """
    Build Datamate download URL from individual parts
    """
    if not base_url:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="base_url is required when dataset_id and file_id are provided"
        )

    base_with_scheme = _ensure_http_scheme(base_url)
    parsed_base = urlparse(base_with_scheme)
    base_prefix = parsed_base.path.rstrip("/")

    if base_prefix and not base_prefix.endswith("/api"):
        if base_prefix.endswith("/"):
            base_prefix = f"{base_prefix}api"
        else:
            base_prefix = f"{base_prefix}/api"
    elif not base_prefix:
        base_prefix = "/api"

    normalized_path = f"{base_prefix}/data-management/datasets/{dataset_id}/files/{file_id}/download"

    return urlunparse((parsed_base.scheme, parsed_base.netloc, normalized_path, "", "", ""))


def _parse_range_header(range_header: str, total_size: int) -> Optional[tuple]:
    """
    Parse an HTTP Range header and return (start, end) byte offsets (both inclusive).

    Supports:
      - bytes=start-end
      - bytes=start-      (to end of file)
      - bytes=-suffix     (last N bytes)

    Returns None if the range is malformed or not satisfiable.
    """
    try:
        if total_size <= 0:
            return None
        if not range_header.startswith("bytes="):
            return None
        range_spec = range_header[6:].strip()
        if "-" not in range_spec:
            return None
        start_str, end_str = range_spec.split("-", 1)
        start_str = start_str.strip()
        end_str = end_str.strip()

        if start_str == "":
            # Suffix range: bytes=-N
            if not end_str:
                return None
            suffix = int(end_str)
            start = max(0, total_size - suffix)
            end = total_size - 1
        elif end_str == "":
            # Open-ended range: bytes=N-
            start = int(start_str)
            end = total_size - 1
        else:
            start = int(start_str)
            end = int(end_str)

        # Clamp end to last byte (RFC 7233 §2.1 allows end to exceed file size)
        end = min(end, total_size - 1)

        # Validate bounds
        if start < 0 or start >= total_size or end < start:
            return None

        return start, end
    except (ValueError, AttributeError):
        return None
