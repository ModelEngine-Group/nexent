"""Controlled HTTP assets route set (mounted at /assets).

Serves deterministic resources with configurable HTTP semantics so the
product's resource-facing paths (file preview, image proxy, download proxies)
can be exercised without any real external host:

  - Range behaviour: RFC 7233 single-range support (206 + Content-Range,
    416 for unsatisfiable ranges) or plain 200-full when unsupported —
    exercising both branches of the frontend preview drawer and the
    /file/preview proxy contract.
  - Content-Type (including non-image/* for the ind-AIDP content-type check)
    and Content-Disposition filenames (including non-ASCII).
  - Arbitrary status codes, redirects, per-asset latency, generated sizes.

Asset specs come from seeds/assets.json and can be (re)declared at runtime
via POST /_mock/assets; ``POST /_reset`` restores the seeded set.
"""
import asyncio
import base64
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import RedirectResponse, Response

from mock_common import StateStore, content_disposition

_PATTERN = b"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _asset_bytes(spec: Dict[str, Any]) -> bytes:
    """Deterministic content: embedded base64 payload or a repeating pattern."""
    encoded = spec.get("content_b64")
    if encoded:
        return base64.b64decode(encoded)
    size = int(spec.get("size") or 1024)
    repetitions = -(-size // len(_PATTERN))
    return (_PATTERN * repetitions)[:size]


def _parse_range(range_header: str, total_size: int) -> Optional[tuple]:
    """Parse a single-range ``bytes=`` header; None when unsatisfiable.

    Mirrors the product's file_management_app._parse_range_header semantics
    (start-end / start- / -suffix, end clamped to the last byte).
    """
    if total_size <= 0 or not range_header.startswith("bytes="):
        return None
    range_spec = range_header[len("bytes="):].strip()
    if "-" not in range_spec:
        return None
    start_str, end_str = range_spec.split("-", 1)
    start_str, end_str = start_str.strip(), end_str.strip()
    try:
        if start_str == "":
            suffix = int(end_str)
            start, end = max(0, total_size - suffix), total_size - 1
        elif end_str == "":
            start, end = int(start_str), total_size - 1
        else:
            start, end = int(start_str), int(end_str)
    except ValueError:
        return None
    end = min(end, total_size - 1)
    if start < 0 or start >= total_size or end < start:
        return None
    return start, end


class AssetRegistry:
    """Runtime (re)declaration of assets on top of the seeded set."""

    def __init__(self, state: StateStore):
        self.state = state

    def register(self, specs: List[Dict[str, Any]]) -> List[str]:
        assets: Dict[str, Dict[str, Any]] = self.state.data.setdefault("assets", {})
        registered = []
        for spec in specs:
            name = str(spec.get("name") or "").strip("/")
            if not name:
                raise HTTPException(status_code=400, detail="asset spec requires a name")
            assets[name] = spec
            registered.append(name)
        self.state.save()
        return registered


def create_router(state: StateStore) -> APIRouter:
    router = APIRouter(prefix="/assets")

    @router.get("/{asset_name:path}")
    async def get_asset(
        asset_name: str,
        range_header: Optional[str] = Header(default=None, alias="range"),
    ) -> Response:
        assets: Dict[str, Dict[str, Any]] = state.data.get("assets", {})
        spec = assets.get(asset_name)
        if spec is None:
            raise HTTPException(status_code=404, detail=f"Asset {asset_name!r} not found")

        if spec.get("redirect_to"):
            return RedirectResponse(url=str(spec["redirect_to"]), status_code=302)

        latency_ms = float(spec.get("latency_ms") or 0)
        if latency_ms > 0:
            await asyncio.sleep(latency_ms / 1000.0)

        status_code = int(spec.get("status") or 200)
        if status_code != 200:
            return Response(
                content=b"mock asset configured status",
                status_code=status_code,
                media_type=spec.get("content_type") or "text/plain",
            )

        content = _asset_bytes(spec)
        headers: Dict[str, str] = {}
        if spec.get("filename"):
            headers["Content-Disposition"] = content_disposition(str(spec["filename"]))
        supports_ranges = bool(spec.get("support_ranges", True))

        if supports_ranges:
            headers["Accept-Ranges"] = "bytes"
            if range_header:
                parsed = _parse_range(range_header, len(content))
                if parsed is None:
                    return Response(
                        status_code=416,
                        headers={"Content-Range": f"bytes */{len(content)}"},
                    )
                start, end = parsed
                return Response(
                    content=content[start : end + 1],
                    status_code=206,
                    media_type=spec.get("content_type") or "application/octet-stream",
                    headers={
                        **headers,
                        "Content-Range": f"bytes {start}-{end}/{len(content)}",
                    },
                )
        # No Range header, or the asset explicitly does not support ranges:
        # return the full body with 200 (this branch is what the datamate
        # download proxy and no-range upstreams look like to the product).
        return Response(
            content=content,
            media_type=spec.get("content_type") or "application/octet-stream",
            headers=headers,
        )

    return router
