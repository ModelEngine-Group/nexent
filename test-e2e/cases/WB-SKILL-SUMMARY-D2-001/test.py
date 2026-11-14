# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Self-contained loopback HTTP proof for the real Skill router and service."""

from copy import deepcopy
from pathlib import Path
import socket
import sys
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, HTTPException

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO / "backend"), str(REPO / "sdk")]

from management.api.skill import skill as skill_api
from management.services.skill import service as skill_service


@pytest.mark.case_id("WB-SKILL-SUMMARY-D2-001")
@pytest.mark.stage("D2")
def test_skill_mount_summary_http_contract(monkeypatch):
    rows = [dict(
        skill_id=index, name=f"Fixture skill {index}", source="local", description="Summary",
        tenant_id="tenant-a", created_by="viewer" if index == 1 else "other",
        group_ids=[], ingroup_permission="PRIVATE", tags=["fixture"],
        config_schemas=[{"name": "region", "required": True, "type": "string"}],
        config_values={"region": "west"}, content="instructions " * 10000, tool_ids=[9],
    ) for index in (1, 2)]
    calls = {"full": 0, "mount": 0}

    def authorize(value):
        if value != "Bearer fixture-session":
            raise HTTPException(status_code=401, detail="Unauthorized")
        return "viewer", "tenant-a"

    def full_list(tenant_id):
        assert tenant_id == "tenant-a"
        calls["full"] += 1
        return deepcopy(rows)

    def mount_list(tenant_id):
        assert tenant_id == "tenant-a"
        calls["mount"] += 1
        return [{key: deepcopy(value) for key, value in row.items() if key not in {"content", "tool_ids"}} for row in rows]

    monkeypatch.setattr(skill_api, "get_current_user_id", authorize)
    monkeypatch.setattr(skill_api, "resource_read_tenant", lambda request, shared: None)
    monkeypatch.setattr(skill_service.skill_db, "list_skills", full_list)
    monkeypatch.setattr(skill_service.skill_db, "list_skill_mount_summaries", mount_list)
    monkeypatch.setattr(skill_service, "_get_user_role", lambda user_id: "USER")
    monkeypatch.setattr(skill_service, "query_group_ids_by_user", lambda user_id: [])
    monkeypatch.setattr(skill_service, "get_skill_manager", lambda: object())
    monkeypatch.setattr(skill_service.SkillService, "_resolve_local_skills_dir_for_overlay", lambda self: None)

    app = FastAPI()
    app.include_router(skill_api.router)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
            headers = {"Authorization": "Bearer fixture-session"}
            full = client.get("/skills", headers=headers)
            summary = client.get("/skills", params={"view": "mount"}, headers=headers)
            assert full.status_code == summary.status_code == 200
            assert calls == {"full": 1, "mount": 1}
            full_rows, mount_rows = full.json()["skills"], summary.json()["skills"]
            assert [row["skill_id"] for row in mount_rows] == [1]
            assert mount_rows == [{key: value for key, value in row.items() if key not in {"content", "tool_ids"}} for row in full_rows]
            assert mount_rows[0]["config_values"] == {"region": "west"}
            assert mount_rows[0]["permission"] == "EDIT"
            assert len(summary.content) < len(full.content) / 10
            assert client.get("/skills", params={"view": "mount"}).status_code == 401
            assert client.get("/skills", params={"view": "invalid"}, headers=headers).status_code == 422
            rows.clear()
            empty = client.get("/skills", params={"view": "mount"}, headers=headers)
            assert empty.status_code == 200 and empty.json() == {"skills": []}
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
        assert not worker.is_alive(), "Owned HTTP server must stop"
