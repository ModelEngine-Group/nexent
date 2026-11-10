# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real router/service/PostgreSQL proofs in a disposable translated schema.

This script runs in the configured backend Python environment. It does not
change the running application's session factory or use existing user data.
"""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import io
import sys
import uuid
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text, update
from sqlalchemy.orm import sessionmaker

from contracts.review import ReviewDecisionRequest
from gateway.authentication.auth import generate_session_jwt
from management.api.repository.reviews import router
from management.db.client import db_client
from management.db.models import (
    AgentInfo, AgentRepository, McpMarketRecord, McpRecord, Notification, NotificationReceiver,
    ResourceTagAssignment, TagBucket, TagBucketResourceType, TagDefinition, TagValue,
    RolePermission, SkillInfo, SkillInstance, SkillRepository, SkillToolRelation,
    TenantGroupInfo, TenantGroupUser, ToolInfo, UserOAuthAccount, UserTenant,
)
from management.db.repository_reviews import REVIEW_MODELS


class Fixture:
    def __init__(self):
        self.schema = "rsc_verify_" + uuid.uuid4().hex
        self.owner = db_client.engine
        with self.owner.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = self.owner.execution_options(schema_translate_map={"nexent": self.schema})
        self.factory = sessionmaker(bind=self.engine)
        db_client.session_maker = self.factory
        for model in (AgentRepository, SkillRepository, McpMarketRecord, McpRecord,
                      SkillInfo, SkillInstance, SkillToolRelation, AgentInfo, ToolInfo,
                      TagBucket, TagBucketResourceType, TagDefinition, TagValue, ResourceTagAssignment,
                      TenantGroupInfo, TenantGroupUser, RolePermission, UserTenant, UserOAuthAccount,
                      Notification, NotificationReceiver):
            model.__table__.create(self.engine)
        self.tenant = self.schema
        self.other_tenant = self.schema + "_other"
        self.admin, self.mine, self.other, self.denied = [str(uuid.uuid4()) for _ in range(4)]
        self.records = []
        with self.factory.begin() as session:
            for user_id, role in [(self.admin, "ADMIN"), (self.mine, "DEV"), (self.other, "DEV"), (self.denied, "USER")]:
                session.add(UserTenant(user_id=user_id, tenant_id=self.tenant, user_role=role,
                    user_email=f"{user_id}@example.invalid", created_by=user_id, updated_by=user_id))
            for role in ("ADMIN", "DEV", "SPEED", "ASSET_OWNER"):
                session.add(RolePermission(user_role=role, permission_category="VISIBILITY",
                    permission_type="LEFT_NAV_MENU", permission_subtype="/resource-space"))
            for kind, count in [("agent", 13), ("skill", 13), ("mcp", 12)]:
                for index in range(count):
                    author = self.mine if index < 3 else self.admin if index == 3 else None if kind == "mcp" and index >= count - 2 else self.other
                    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index % 4) if index < count - 2 else None
                    self.add(session, kind, index + 1, submitted_user_id=author, submitted_at=timestamp,
                             status=["pending_review", "shared", "rejected"][index % 3])
                self.add(session, kind, 100, status="not_shared")
                self.add(session, kind, 101, tenant_id=self.other_tenant, status="pending_review")
        from management.api.agent.agent_repository import agent_repository_router
        from management.api.skill.skill_repository import skill_repository_router
        from management.api.mcp.mcp_management import router as mcp_router
        app = FastAPI()
        app.include_router(agent_repository_router)
        app.include_router(skill_repository_router)
        app.include_router(mcp_router)
        app.include_router(router)
        self.client = TestClient(app)

    def add(self, session, kind, identifier, *, status="pending_review", tenant_id=None,
            submitted_user_id=None, submitted_at=None, revision=0):
        model, id_field, tenant_field, status_field, _ = REVIEW_MODELS[kind]
        values = {id_field: identifier, tenant_field: tenant_id or self.tenant, status_field: status,
            "submitted_user_id": submitted_user_id, "submitted_at": submitted_at,
            "submission_revision": revision, "description": "Frozen description", "content": "Legacy note",
            "created_by": self.admin, "updated_by": self.admin}
        if kind == "agent":
            values.update(agent_id=identifier % 1000000, publisher_user_id=self.admin,
                version_no=1, name=f"res_{kind}_{identifier}", agent_info_json={"agent_info": {
                    "root": {"name": "Frozen agent", "system_prompt": "Frozen prompt", "tools": []}}})
        elif kind == "skill":
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                archive.writestr("sample/SKILL.md", "---\nname: sample\ndescription: Sample skill\n---\nFrozen skill file")
            values.update(skill_id=identifier % 1000000, publisher_user_id=self.admin,
                name=f"res_{kind}_{identifier}", skill_info_json={"content": "Frozen skill readme"},
                skill_zip_base64=base64.b64encode(stream.getvalue()).decode())
        else:
            session.add(McpRecord(mcp_id=identifier, tenant_id=tenant_id or self.tenant,
                user_id=self.admin, mcp_name=f"source_{identifier}", mcp_server="https://source.invalid/mcp"))
            values.update(user_id=self.admin, mcp_name=f"res_{kind}_{identifier}", transport_type="url",
                mcp_server="https://user:secret@example.invalid/mcp?token=secret", config_json={"env": {"API_KEY": "secret"}},
                shared_fields={"authorizationToken": False}, source_mcp_id=identifier)
        row = model(**values)
        session.add(row)
        if (tenant_id or self.tenant) == self.tenant and status != "not_shared":
            self.records.append({"resource_type": kind, "repository_id": str(identifier), "status": status,
                                 "submitted_user_id": submitted_user_id, "submitted_at": submitted_at,
                                 "name": values.get("name") or values.get("mcp_name")})
        return row

    def headers(self, user=None):
        return {"Authorization": "Bearer " + generate_session_jwt(user or self.admin)}

    def get(self, path="/reviews", *, user=None, params=None):
        return self.client.get(path, headers=self.headers(user), params=params)

    def decision(self, kind, identifier, *, reason=None, revision=0, decision="approve", user=None):
        return self.client.post(f"/reviews/{kind}/{identifier}/decision", headers=self.headers(user),
            json={"decision": decision, "reason": reason, "expected_revision": revision})

    def close(self):
        if hasattr(self, "client"):
            self.client.close()
        self.engine.dispose()
        with self.owner.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))


def list_contract(fixture):
    result = fixture.get().json()
    assert result["pagination"] == {"page": 1, "page_size": 10, "total": 38, "total_pages": 4}
    ordered = sorted(fixture.records, key=lambda row: (-row["submitted_at"].timestamp() if row["submitted_at"] else float("inf"),
        row["resource_type"], -int(row["repository_id"])))
    actual = []
    for page in range(1, 5):
        response = fixture.get(params={"page": page})
        assert response.status_code == 200
        actual.extend(response.json()["items"])
    assert [(row["resource_type"], row["repository_id"]) for row in actual] == [(row["resource_type"], row["repository_id"]) for row in ordered]
    assert len({(row["resource_type"], row["repository_id"]) for row in actual}) == 38
    assert actual[-1]["submitted_at"] is None
    assert {row["status"] for row in actual} == {"pending_review", "shared", "rejected"}
    for kind in ("all", "agent", "skill", "mcp"):
        for state in ("all", "pending_review", "shared", "rejected"):
            expected = [row for row in ordered if (kind == "all" or row["resource_type"] == kind) and (state == "all" or row["status"] == state)]
            response = fixture.get(params={"type": kind, "status": state, "page_size": 100}).json()
            assert response["pagination"]["total"] == len(expected)
            assert [(row["resource_type"], row["repository_id"]) for row in response["items"]] == [(row["resource_type"], row["repository_id"]) for row in expected]
            own = fixture.get(user=fixture.mine, params={"type": kind, "status": state, "page_size": 100}).json()
            assert own["pagination"]["total"] == len([row for row in expected if row["submitted_user_id"] == fixture.mine])
            assert all(row["submitted_user_id"] == fixture.mine for row in own["items"])
    assert fixture.get(user=fixture.mine).json()["pagination"]["total"] == 9
    for user in (fixture.admin, fixture.mine):
        response = fixture.get(user=user, params={"search": "  res_agent_1  ", "page_size": 100}).json()
        assert response["items"] and all("res_agent_1" in row["name"] for row in response["items"])
    empty = fixture.get(params={"search": "absent-" + uuid.uuid4().hex}).json()
    assert empty["items"] == [] and empty["pagination"]["total_pages"] == 0
    out = fixture.get(params={"page": 99}).json()
    assert out["items"] == [] and out["pagination"]["total"] == 38
    for params in ({"page": 0}, {"page_size": 0}, {"page_size": 101}, {"type": "unknown"}, {"status": "unknown"}, {"scope": "all_authorized"}):
        assert fixture.get(params=params).status_code == 400
    assert fixture.get(user=fixture.denied).status_code == 403
    with fixture.factory.begin() as session:
        fixture.add(session, "agent", 200, submitted_user_id=fixture.mine, submitted_at=datetime.now(timezone.utc), revision=1)
    changed = fixture.get().json()
    assert changed["pagination"]["total"] == 39
    assert changed["items"][0]["repository_id"] == "200"
    assert fixture.get(params={"page": 2}).json()["pagination"]["total"] == 39

    inserted = False
    def insert_between_count_and_page(connection, cursor, statement, parameters, context, many):
        nonlocal inserted
        if inserted or "count(" not in statement.lower() or "union all" not in statement.lower():
            return
        inserted = True
        with fixture.factory.begin() as writer:
            fixture.add(writer, "agent", 201, submitted_user_id=fixture.mine,
                        submitted_at=datetime.now(timezone.utc), revision=1)
    event.listen(fixture.engine, "after_cursor_execute", insert_between_count_and_page)
    try:
        snapshot = fixture.get(params={"page_size": 100}).json()
    finally:
        event.remove(fixture.engine, "after_cursor_execute", insert_between_count_and_page)
    assert inserted
    assert snapshot["pagination"]["total"] == len(snapshot["items"]) == 39
    assert "201" not in {row["repository_id"] for row in snapshot["items"]}
    assert fixture.get().json()["pagination"]["total"] == 40


def detail_contract(fixture):
    for kind in ("agent", "skill", "mcp"):
        response = fixture.get(f"/reviews/{kind}/1")
        assert response.status_code == 200
        data = response.json()
        assert data["resource_type"] == kind and data["repository_id"] == "1"
        assert data["allowed_actions"] == ["approve", "reject"]
        assert "resource_detail" in data and "skill_zip_base64" not in data
        assert "secret" not in str(data["resource_detail"])
        if kind == "mcp":
            with fixture.factory.begin() as session:
                session.execute(update(McpRecord).where(McpRecord.mcp_id == 1,
                    McpRecord.tenant_id == fixture.tenant).values(mcp_name="Edited source", mcp_server="https://edited.invalid"))
            assert fixture.get(f"/reviews/{kind}/1").json()["resource_detail"] == data["resource_detail"]
            assert data["resource_detail"]["server_url"] == "https://example.invalid/mcp"
            assert all(field["masked"] for field in data["resource_detail"]["sensitive_fields"])
        elif kind == "agent":
            assert data["resource_detail"]["agents"][0]["prompt"] == "Frozen prompt"
        else:
            assert data["resource_detail"]["readme"] == "Frozen skill readme"
            assert data["resource_detail"]["file_manifest"][0]["path"] == "sample/SKILL.md"
        assert fixture.get(f"/reviews/{kind}/2").json()["allowed_actions"] == []
        mine = fixture.get(f"/reviews/{kind}/1", user=fixture.mine)
        assert mine.status_code == 200 and mine.json()["allowed_actions"] == []
        assert fixture.get(f"/reviews/{kind}/4", user=fixture.mine).status_code == 404
        assert fixture.get(f"/reviews/{kind}/4").json()["allowed_actions"] == ["approve", "reject"]
        assert fixture.get(f"/reviews/{kind}/101").status_code == 404
        assert fixture.decision(kind, 1, user=fixture.mine).status_code == 403
    for prefix in ("/repository/agent", "/repository/skill"):
        assert fixture.client.patch(f"{prefix}/1/status", headers=fixture.headers(), json={}).status_code == 422
        assert fixture.client.patch(f"{prefix}/1/status", headers=fixture.headers(), json={"status": "unknown"}).status_code == 400
    assert fixture.client.get("/reviews").status_code == 401
    assert fixture.get("/reviews/unknown/1").status_code == 400
    assert fixture.get("/reviews/agent/999999").status_code == 404
    for kind, identifier, reason, decision in [("agent", 1, "  ", "approve"), ("skill", 1, "中" * 1000, "reject"), ("mcp", 1, "😀" * 1000, "approve")]:
        result = fixture.decision(kind, identifier, reason=reason, decision=decision)
        assert result.status_code == 200, result.text
        assert result.json()["review_comment"] == (reason.strip() or None)
        assert result.json()["revision"] == 0
        assert fixture.decision(kind, identifier, reason=reason, decision=decision).status_code == 409
    for body in ({"decision": "approve", "reason": "中" * 1001, "expected_revision": 0},
                 {"decision": "approve", "reason": "😀" * 1001, "expected_revision": 0},
                 {"decision": "other", "expected_revision": 0}, {"decision": "approve"}):
        assert fixture.client.post("/reviews/agent/4/decision", headers=fixture.headers(), json=body).status_code == 400
    assert fixture.decision("agent", 4, revision=99).status_code == 409
    for identifier in (9007199254740992, 9007199254740993):
        with fixture.factory.begin() as session:
            fixture.add(session, "agent", identifier, submitted_user_id=fixture.mine, revision=1)
        response = fixture.get(f"/reviews/agent/{identifier}")
        assert response.status_code == 200 and response.json()["repository_id"] == str(identifier)
        assert fixture.decision("agent", identifier, revision=1).status_code == 200

    for kind in ("agent", "skill", "mcp"):
        for offset, (decision, reason) in enumerate((decision, reason) for decision in ("approve", "reject")
                for reason in (None, "  ", " " + "中" * 1000 + " ", "😀" * 1000, "中" * 1001, "😀" * 1001)):
            identifier = 300 + offset
            with fixture.factory.begin() as session:
                fixture.add(session, kind, identifier, submitted_user_id=fixture.mine, revision=1)
            body = {"decision": decision, "expected_revision": 1}
            if reason is not None:
                body["reason"] = reason
            response = fixture.client.post(f"/reviews/{kind}/{identifier}/decision", headers=fixture.headers(), json=body)
            expected = (reason or "").strip()
            assert response.status_code == (400 if len(expected) > 1000 else 200), response.text
            if response.status_code == 200:
                assert response.json()["review_comment"] == (expected or None)
                assert response.json()["status"] == ("shared" if decision == "approve" else "rejected")
                assert fixture.get(f"/reviews/{kind}/{identifier}", user=fixture.mine).json()["allowed_actions"] == []
    identifiers = {row["repository_id"] for row in fixture.get(params={"page_size": 100}).json()["items"]}
    assert {"9007199254740992", "9007199254740993"}.issubset(identifiers)


def lifecycle_contract(fixture):
    from management.db.agent.catalog import increment_agent_repository_downloads
    from management.db.mcp.market import increment_mcp_market_download_count
    from management.db.skill.catalog import increment_skill_repository_downloads

    for kind in ("agent", "skill", "mcp"):
        model, id_field, _, status_field, _ = REVIEW_MODELS[kind]
        with fixture.factory() as session:
            creation = session.get(model, 1).create_time
        def legacy(status, content=None):
            if kind == "mcp":
                return fixture.client.patch("/mcp-tools/community/1/status", headers=fixture.headers(),
                                            json={"status": status, "content": content})
            return fixture.client.patch(f"/repository/{kind}/1/status", headers=fixture.headers(),
                                        json={"status": status, "content": content})
        assert legacy("rejected", "Old opinion").status_code == 200
        assert legacy("pending_review", "New submission").status_code == 200
        current = fixture.get(f"/reviews/{kind}/1").json()
        assert current["revision"] == 1 and current["submitted_user_id"] == fixture.admin
        assert current["submitted_at"] and current["review_comment"] is None
        assert current["submit_description"] == "New submission" and current["published_at"] is None
        assert legacy("shared", "Approved").status_code == 200
        approved = fixture.get(f"/reviews/{kind}/1").json()
        assert approved["review_comment"] == "Approved"
        assert approved["submit_description"] == "New submission"
        assert approved["published_at"] and approved["submitted_at"] == current["submitted_at"]
        if kind == "agent":
            increment_agent_repository_downloads(1)
        elif kind == "skill":
            increment_skill_repository_downloads(repository_id=1, user_id=fixture.admin)
        else:
            increment_mcp_market_download_count(1)
        assert fixture.get(f"/reviews/{kind}/1").json()["published_at"] == approved["published_at"]
        assert legacy("not_shared").status_code == 200
        assert fixture.get(f"/reviews/{kind}/1").status_code == 404
        assert legacy("pending_review").status_code == 200
        pending = fixture.get(f"/reviews/{kind}/1").json()
        assert pending["revision"] == 2 and pending["review_comment"] is None
        assert pending["published_at"] == approved["published_at"]
        assert fixture.decision(kind, 1, revision=1).status_code == 409
        assert fixture.decision(kind, 1, revision=2, decision="reject").status_code == 200
        with fixture.factory() as session:
            row = session.get(model, 1)
            assert row.create_time == creation and row.submitted_user_id == fixture.admin
            assert row.review_comment is None and getattr(row, status_field) == "rejected"
    before = fixture.get("/reviews/mcp/4").json()["resource_detail"]
    with fixture.factory.begin() as session:
        session.execute(update(McpRecord).where(McpRecord.mcp_id == 4).values(
            mcp_server="https://changed.invalid/live", config_json={"token": "new-live-secret"}))
    assert fixture.get("/reviews/mcp/4").json()["resource_detail"] == before


def concurrency_contract(fixture):
    for kind in ("agent", "skill", "mcp"):
        with fixture.factory() as session:
            before = session.scalar(select(func.count()).select_from(Notification))
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda decision: fixture.decision(kind, 1, decision=decision), ["approve", "reject"]))
        assert sorted(result.status_code for result in results) == [200, 409]
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(Notification)) == before + 1
        assert fixture.decision(kind, 1).status_code == 409

    def fail_flush(session, *_):
        if any(isinstance(row, AgentRepository) for row in session.dirty):
            raise RuntimeError("Controlled flush failure")
    before = fixture.get("/reviews/agent/4").json()
    with fixture.factory() as session:
        count = session.scalar(select(func.count()).select_from(Notification))
    event.listen(fixture.factory.class_, "before_flush", fail_flush)
    try:
        try:
            fixture.decision("agent", 4)
        except RuntimeError as error:
            assert "Controlled flush failure" in str(error)
        else:
            raise AssertionError("Injected transaction failure did not reach the caller")
    finally:
        event.remove(fixture.factory.class_, "before_flush", fail_flush)
    after = fixture.get("/reviews/agent/4").json()
    assert (after["status"], after["revision"], after["review_comment"], after["published_at"]) == (
        before["status"], before["revision"], before["review_comment"], before["published_at"])
    with fixture.factory() as session:
        assert session.scalar(select(func.count()).select_from(Notification)) == count


def installation_contract(fixture):
    from tempfile import TemporaryDirectory
    from types import SimpleNamespace
    from unittest.mock import patch

    from contracts.errors.exceptions import ForbiddenError
    from management.services.repository.skill_installations import get_installation_states, uninstall_repository_copy
    from management.services.skill.service import SkillService
    from services import skill_repository_service

    # Only object/file storage is controlled; parsing, permissions, ORM and counters are real.
    with TemporaryDirectory() as directory:
        storage = SimpleNamespace(resolve_tenant_dir=lambda **_: directory, save_skill=lambda *_, **__: None)
        service = SkillService(skill_manager=storage, tenant_id=fixture.tenant)
        service._resolve_local_skills_dir_for_overlay = lambda: None
        service._upload_zip_files = lambda *_, **__: None
        service._enrich_configs_from_yaml = lambda result: result
        service._delete_local_skill_files = lambda *_, **__: None
        with patch.object(skill_repository_service, "SkillService", return_value=service):
            first = skill_repository_service.install_skill_from_repository_impl(
                skill_repository_id=2, tenant_id=fixture.tenant, user_id=fixture.mine, target_name="copy-one")
            second = skill_repository_service.install_skill_from_repository_impl(
                skill_repository_id=2, tenant_id=fixture.tenant, user_id=fixture.mine, target_name="copy-two")
        with fixture.factory() as session:
            assert session.get(SkillInfo, first["skill_id"]).source_repository_id == 2
            assert session.get(SkillInfo, second["skill_id"]).source_repository_id == 2
            assert session.get(SkillRepository, 2).downloads == 2
        with fixture.factory.begin() as session:
            session.add(TenantGroupInfo(group_id=1, tenant_id=fixture.tenant, group_name="Read group"))
            session.add(TenantGroupUser(group_id=1, user_id=fixture.other))
            session.execute(update(SkillInfo).where(SkillInfo.skill_id == first["skill_id"]).values(group_ids="1"))
            session.add(SkillInfo(skill_name="res_skill_3", tenant_id=fixture.tenant, source="custom", created_by=fixture.mine))
        readonly = get_installation_states([2], fixture.tenant, fixture.other, "DEV")["2"]
        assert readonly["installation_state"] == "installed"
        assert len(readonly["installed_copies"]) == 1 and not readonly["installed_copies"][0]["can_uninstall"]
        states = get_installation_states([2, 3], fixture.tenant, fixture.mine, "DEV")
        assert states["2"]["installation_state"] == "installed"
        assert {copy["skill_id"] for copy in states["2"]["installed_copies"]} == {first["skill_id"], second["skill_id"]}
        assert states["3"]["installation_state"] == "not_installed"
        with fixture.factory.begin() as session:
            session.add(SkillInfo(skill_name="legacy", tenant_id=fixture.tenant, source="repository",
                created_by=fixture.mine, ingroup_permission="PRIVATE"))
            session.add(SkillInstance(skill_id=first["skill_id"], agent_id=999, tenant_id=fixture.tenant,
                user_id=fixture.mine, version_no=0, enabled=True))
        assert get_installation_states([3], fixture.tenant, fixture.mine, "DEV")["3"]["installation_state"] == "unknown"
        assert get_installation_states([3], fixture.tenant, fixture.other, "DEV")["3"]["installation_state"] == "not_installed"
        try:
            uninstall_repository_copy(2, first["skill_id"], fixture.tenant, fixture.mine)
        except ValueError as error:
            assert "referenced" in str(error)
        else:
            raise AssertionError("Referenced Skill was removed")
        try:
            uninstall_repository_copy(2, second["skill_id"], fixture.tenant, fixture.other)
        except ForbiddenError:
            pass
        else:
            raise AssertionError("Another user removed an uneditable Skill")
        with patch("management.services.skill.service.get_skill_manager", return_value=storage), patch(
            "management.services.skill.service._resolve_local_skill_path", side_effect=lambda root, name: root + "/" + name):
            uninstall_repository_copy(2, second["skill_id"], fixture.tenant, fixture.mine)
        with fixture.factory() as session:
            assert session.get(SkillInfo, second["skill_id"]).delete_flag == "Y"
            assert session.get(SkillInfo, first["skill_id"]).delete_flag == "N"
            assert session.get(SkillRepository, 2).downloads == 2
        cleanups = []
        service._delete_local_skill_files = lambda name, **_: cleanups.append(name)
        with patch.object(skill_repository_service, "SkillService", return_value=service), patch(
            "management.db.skill.catalog.increment_skill_repository_downloads", side_effect=RuntimeError("Controlled counter failure")):
            try:
                skill_repository_service.install_skill_from_repository_impl(
                    skill_repository_id=2, tenant_id=fixture.tenant, user_id=fixture.mine, target_name="failed-copy")
            except RuntimeError as error:
                assert "Controlled counter failure" in str(error)
            else:
                raise AssertionError("Injected installation failure did not fail")
        assert cleanups == ["failed-copy"]
        with patch.object(service, "_upload_zip_files", side_effect=RuntimeError("Controlled upload failure")), patch.object(
            skill_repository_service, "SkillService", return_value=service):
            try:
                skill_repository_service.install_skill_from_repository_impl(
                    skill_repository_id=2, tenant_id=fixture.tenant, user_id=fixture.mine, target_name="failed-upload")
            except RuntimeError as error:
                assert "Controlled upload failure" in str(error)
            else:
                raise AssertionError("Injected upload failure did not fail")
        assert cleanups == ["failed-copy", "failed-upload"]
        with fixture.factory() as session:
            assert session.scalar(select(SkillInfo).where(SkillInfo.skill_name == "failed-copy")) is None
            assert session.get(SkillRepository, 2).downloads == 2


def main():
    from access_scenario import access_contract
    from reliability_scenario import reliability_contract
    fixture = Fixture.__new__(Fixture)
    try:
        fixture.__init__()
        {"list": list_contract, "detail": detail_contract, "lifecycle": lifecycle_contract,
         "concurrency": concurrency_contract, "installation": installation_contract, "access": access_contract, "reliability": reliability_contract}[sys.argv[1]](fixture)
        print("Isolated repository scenario passed:", sys.argv[1])
    finally:
        if hasattr(fixture, "owner"):
            fixture.close()


if __name__ == "__main__":
    main()
