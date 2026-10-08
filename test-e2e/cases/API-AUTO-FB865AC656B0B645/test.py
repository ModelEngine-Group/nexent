"""D2 API integration test: SUPER_ADMIN project-config asset persistence.

Case: API-AUTO-FB865AC656B0B645
Feature: F-179 前端与全局UI / 项目配置资产
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
import pytest
from shared.deployment_paths import project_config_dir, mutate_project_config
from shared.factories.project_config import journal_project_config, restore_project_config_file
from shared.config import load_yaml

CASE_ID = "API-AUTO-FB865AC656B0B645"
_base_url = (os.environ.get("NEXENT_FRONTEND_URL") or os.environ.get("NEXENT_BASE_URL")
             or load_yaml('environment.yaml').get('base_url') or '').strip()
_parsed_url = urlsplit(_base_url)
FRONTEND_URL = urlunsplit((_parsed_url.scheme, _parsed_url.netloc, '', '', ''))
ACCESS_TOKEN_COOKIE = "nexent_access_token"

_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _project_config_dir() -> Path:
    return project_config_dir()


def _snapshot_files(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D2")
@pytest.mark.asyncio
async def test_super_admin_project_config_asset_persistence(super_admin) -> None:
    config_dir = _project_config_dir()
    logo_bytes = _ONE_PIXEL_PNG
    marker = f"asset-{uuid.uuid4().hex}"
    config_zh = json.dumps({"pageSubtitle": f"自动化测试副标题 {marker}"}, ensure_ascii=False)
    config_en = json.dumps({"pageSubtitle": f"automation subtitle {marker}"}, ensure_ascii=False)

    zh_path = config_dir / "locales" / "zh" / "custom.json"
    en_path = config_dir / "locales" / "en" / "custom.json"

    created = [
        config_dir / "modelengine-logo.png",
        config_dir / "modelengine-logo2.png",
        zh_path,
        en_path,
    ]
    original = {path: path.read_bytes() if path.is_file() else None for path in created}
    for path in created:
        journal_project_config(
            path.relative_to(config_dir).as_posix(), case_id=CASE_ID,
            marker=marker, expected_logo=logo_bytes,
        )
    backup = Path(os.environ['RESULT_DIR']) / 'runtime' / 'project-config-backup'
    backup.mkdir(parents=True, exist_ok=True)
    (backup / 'original.json').write_text(json.dumps({
        str(path.relative_to(config_dir)): base64.b64encode(data).decode() if data is not None else None
        for path, data in original.items()
    }), encoding='utf-8')

    try:
        async with httpx.AsyncClient(base_url=FRONTEND_URL, timeout=30.0) as api:
            upload = await api.post(
                "/api/config/project-config",
                data={"configZh": config_zh, "configEn": config_en},
                files={
                    "logo": ("logo.png", logo_bytes, "image/png"),
                    "logo2": ("logo2.png", logo_bytes, "image/png"),
                },
                cookies={ACCESS_TOKEN_COOKIE: super_admin.access_token},
            )
            assert upload.status_code == 200, upload.text
            assert upload.json() == {"message": "success update"}

            assert (config_dir / "modelengine-logo.png").is_file()
            assert (config_dir / "modelengine-logo2.png").is_file()
            assert zh_path.is_file()
            assert en_path.is_file()

            before_unauthorized = _snapshot_files(config_dir)
            unauthorized = await api.post(
                "/api/config/project-config",
                data={"configZh": config_zh, "configEn": config_en},
                files={"logo": ("logo.png", logo_bytes, "image/png")},
            )
            assert unauthorized.status_code == 403, unauthorized.text
            assert unauthorized.json() == {"message": "Super admin access required"}
            assert _snapshot_files(config_dir) == before_unauthorized

            logo2 = await api.get("/modelengine-logo2.png")
            assert logo2.status_code == 200
            assert logo2.headers.get("content-type") == "image/png"
            assert logo2.headers.get("cache-control") == "no-store"
            assert logo2.content == logo_bytes

            logo = await api.get("/modelengine-logo.png")
            assert logo.status_code == 200
            assert logo.headers.get("content-type") == "image/png"
            assert logo.headers.get("cache-control") == "no-store"
            assert logo.content == logo_bytes

            zh = await api.get("/locales/zh/custom.json")
            assert zh.status_code == 200
            assert zh.headers.get("content-type") == "application/json; charset=utf-8"
            assert zh.headers.get("cache-control") == "no-store"
            zh_payload = zh.json()
            assert zh_payload["pageSubtitle"] == f"自动化测试副标题 {marker}"
            assert zh_payload["productName"] == "Nexent"

            en = await api.get("/locales/en/custom.json")
            assert en.status_code == 200
            assert en.headers.get("content-type") == "application/json; charset=utf-8"
            assert en.headers.get("cache-control") == "no-store"
            en_payload = en.json()
            assert en_payload["pageSubtitle"] == f"automation subtitle {marker}"
            assert en_payload["productName"] == "Nexent"

            head = await api.head("/modelengine-logo.png")
            assert head.status_code == 200
            assert head.headers.get("cache-control") == "no-store"
            assert head.content == b""

            mutate_project_config(zh_path, None)
            fallback = await api.get("/locales/zh/custom.json")
            assert fallback.status_code == 200
            assert fallback.headers.get("cache-control") == "no-store"
            fallback_payload = fallback.json()
            assert fallback_payload["productName"] == "Nexent"
            assert fallback_payload["pageSubtitle"] == "一个提示词，无限种可能"

            mutate_project_config(zh_path, f"{{ not valid json {marker}".encode())
            recover = await api.post(
                "/api/config/project-config",
                data={
                    "configZh": json.dumps({"pageSubtitle": f"恢复副标题 {marker}"}, ensure_ascii=False),
                    "configEn": config_en,
                },
                files={"logo": ("logo.png", logo_bytes, "image/png")},
                cookies={ACCESS_TOKEN_COOKIE: super_admin.access_token},
            )
            assert recover.status_code == 200, recover.text
            recovered_zh = await api.get("/locales/zh/custom.json")
            assert recovered_zh.status_code == 200
            # The declared malformed-file contract is safe empty fallback,
            # not reconstruction of keys that no longer exist in the old data.
            assert recovered_zh.json() == {}

            for response in (upload, unauthorized, zh, en, fallback, recover):
                assert super_admin.access_token not in response.text
    finally:
        for path in created:
            restore_project_config_file({
                "relative": path.relative_to(config_dir).as_posix(),
                "original_b64": base64.b64encode(original[path]).decode("ascii") if original[path] is not None else None,
                "marker": marker,
                "logo_sha256": hashlib.sha256(logo_bytes).hexdigest(),
            })
