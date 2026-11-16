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
    TenantGroupInfo, TenantGroupUser, ToolInfo, UserAccount, UserOAuthAccount, UserTenant,
)
from management.db.repository_reviews import REVIEW_MODELS


from management.db.resource_review_model import ResourceReview


class Fixture:
    def __init__(self):
        self.schema = "rsc_verify_" + uuid.uuid4().hex
        self.owner = db_client.engine
        self.original_factory = db_client.session_maker
        with self.owner.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = self.owner.execution_options(schema_translate_map={"nexent": self.schema})
        self.factory = sessionmaker(bind=self.engine)
        db_client.session_maker = self.factory
        for model in (AgentRepository, SkillRepository, McpMarketRecord, McpRecord,
                      SkillInfo, SkillInstance, SkillToolRelation, AgentInfo, ToolInfo,
                      TagBucket, TagBucketResourceType, TagDefinition, TagValue, ResourceTagAssignment,
                      TenantGroupInfo, TenantGroupUser, RolePermission, UserTenant, UserAccount,
                      UserOAuthAccount, Notification, NotificationReceiver, ResourceReview):
            model.__table__.create(self.engine)
        self.tenant = self.schema
        self.other_tenant = self.schema + "_other"
        self.admin, self.mine, self.other, self.denied = [str(uuid.uuid4()) for _ in range(4)]
        self.records = []
        self.review_ids = {}
        with self.factory.begin() as session:
            for user, role in ((self.admin, "ADMIN"), (self.mine, "DEV"), (self.other, "DEV"), (self.denied, "USER")):
                self.add_user(session, user, role)
            for role in ("ADMIN", "DEV", "ASSET_OWNER"):
                session.add(RolePermission(user_role=role, permission_category="VISIBILITY",
                    permission_type="LEFT_NAV_MENU", permission_subtype="/resource-space"))
            for kind, count in (("agent", 13), ("skill", 13), ("mcp", 12)):
                for index in range(count):
                    author = self.mine if index < 3 else self.other
                    self.add(session, kind, index + 1, submitted_user_id=author,
                        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index % 4),
                        status=("pending_review", "shared", "rejected")[index % 3])
                self.add(session, kind, 100, status="not_shared")
                self.add(session, kind, 101, tenant_id=self.other_tenant)
            session.flush()
            for model in (AgentRepository, SkillRepository, McpMarketRecord, McpRecord, SkillInfo, AgentInfo):
                column = list(model.__table__.primary_key)[0]
                if getattr(column.default, "is_sequence", False):
                    maximum = session.scalar(select(func.max(column))) or 1
                    session.execute(select(func.setval(f"{self.schema}.{column.default.name}", maximum, True)))
        from management.api.agent.agent_repository import agent_repository_router
        from management.api.skill.skill_repository import skill_repository_router
        from management.api.mcp.mcp_management import router as mcp_router
        app = FastAPI()
        for route in (agent_repository_router, skill_repository_router, mcp_router, router):
            app.include_router(route)
        self.client = TestClient(app)

    def add_user(self, session, user, role):
        session.add(UserAccount(user_id=user, user_roles=[role], user_email=f"{user}@example.invalid"))
        session.add(UserTenant(user_id=user, tenant_id=self.tenant))

    def add(self, session, kind, identifier, *, status="pending_review", tenant_id=None,
            submitted_user_id=None, submitted_at=None, published=True):
        tenant = tenant_id or self.tenant
        source_id = identifier % 1000000
        model, key, tenant_key, state_key, source_key = REVIEW_MODELS[kind]
        values = {key: identifier, tenant_key: tenant, source_key: source_id,
                  state_key: "shared" if status == "shared" else "not_shared",
                  "description": "Frozen description", "content": "Legacy note",
                  "created_by": self.admin, "updated_by": self.admin}
        if kind == "agent":
            session.add(AgentInfo(agent_id=source_id, tenant_id=tenant, version_no=1,
                name=f"res_agent_{identifier}", created_by=self.admin))
            values.update(publisher_user_id=self.admin, version_no=1, name=f"res_agent_{identifier}",
                agent_info_json={"agent_id": source_id, "agent_info": {str(source_id): {
                    "name": "Frozen agent", "prompt": "Frozen prompt", "tools": []}}})
        elif kind == "skill":
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                archive.writestr("sample/SKILL.md", "---\nname: sample\ndescription: Sample skill\n---\nFrozen skill file")
            session.add(SkillInfo(skill_id=source_id, tenant_id=tenant, skill_name=f"res_skill_{identifier}",
                created_by=self.admin, source="custom"))
            values.update(publisher_user_id=self.admin, name=f"res_skill_{identifier}",
                skill_info_json={"content": "Frozen skill readme"}, skill_zip_base64=base64.b64encode(stream.getvalue()).decode())
        else:
            session.add(McpRecord(mcp_id=source_id, tenant_id=tenant, user_id=self.admin,
                created_by=self.admin, mcp_name=f"source_{identifier}", mcp_server="https://source.invalid/mcp"))
            values.update(user_id=self.admin, mcp_name=f"res_mcp_{identifier}", transport_type="url",
                mcp_server="https://user:secret@example.invalid/mcp?token=secret", config_json={"env": {"API_KEY": "secret"}},
                shared_fields={"authorizationToken": False})
        row = model(**values)
        if published:
            session.add(row)
        if status == "not_shared":
            return row
        timestamp = submitted_at or datetime.now(timezone.utc)
        review = ResourceReview(tenant_id=tenant, resource_type=kind, source_resource_id=source_id,
            version_no=1 if kind == "agent" else None, repository_id=identifier if published else None,
            submitted_user_id=submitted_user_id or self.admin, submitted_at=timestamp,
            resource_snapshot={"schema_version": 1, "payload": {column.name: values.get(column.name) for column in model.__table__.columns}},
            review_status="approved" if status == "shared" else status,
            reviewed_at=timestamp if status != "pending_review" else None,
            created_by=self.admin, updated_by=self.admin)
        session.add(review)
        session.flush()
        self.review_ids[(kind, identifier)] = review.review_id
        if tenant == self.tenant:
            self.records.append({"resource_type": kind, "review_id": str(review.review_id),
                "repository_id": str(identifier) if published else None, "status": review.review_status,
                "submitted_user_id": review.submitted_user_id, "submitted_at": timestamp,
                "name": values.get("name") or values.get("mcp_name")})
        return review

    def headers(self, user=None):
        return {"Authorization": "Bearer " + generate_session_jwt(user or self.admin)}

    def get(self, path="/reviews", *, user=None, params=None):
        return self.client.get(path, headers=self.headers(user), params=params)

    def decision(self, kind, identifier, *, reason=None, decision="approve", user=None):
        review_id = self.review_ids[(kind, identifier)]
        return self.client.post(f"/reviews/{review_id}/decision", headers=self.headers(user),
            json={"decision": decision, "reason": reason})

    def close(self):
        if hasattr(self, "client"):
            self.client.close()
        db_client.session_maker = self.original_factory
        self.engine.dispose()
        with self.owner.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))


def list_contract(fixture):
    ordered = sorted(fixture.records, key=lambda row: (row["submitted_at"], int(row["review_id"])), reverse=True)
    actual = []
    for page in range(1, 5):
        response = fixture.get(params={"page": page})
        assert response.status_code == 200, response.text
        assert response.json()["pagination"]["total"] == 38
        actual.extend(response.json()["items"])
    assert [row["review_id"] for row in actual] == [row["review_id"] for row in ordered]
    assert len({row["review_id"] for row in actual}) == 38
    for kind in ("all", "agent", "skill", "mcp"):
        for state in ("all", "pending_review", "approved", "rejected"):
            expected = [row for row in ordered if (kind == "all" or row["resource_type"] == kind)
                        and (state == "all" or row["status"] == state)]
            result = fixture.get(params={"type": kind, "status": state, "page_size": 100}).json()
            assert [row["review_id"] for row in result["items"]] == [row["review_id"] for row in expected]
            own = fixture.get(user=fixture.mine, params={"type": kind, "status": state, "page_size": 100}).json()
            assert own["pagination"]["total"] == len([row for row in expected if row["submitted_user_id"] == fixture.mine])
    assert fixture.get(user=fixture.mine).json()["pagination"]["total"] == 9
    assert fixture.get(params={"search": "absent"}).json()["items"] == []
    assert fixture.get(params={"page": 99}).json()["items"] == []
    assert fixture.get(params={"search": "res_agent_1"}).json()["items"]
    for params in ({"page": 0}, {"page_size": 101}, {"type": "unknown"}, {"status": "shared"}, {"scope": "all_authorized"}):
        assert fixture.get(params=params).status_code == 400
    assert fixture.get(user=fixture.denied).status_code == 403


def detail_contract(fixture):
    for kind in REVIEW_MODELS:
        review_id = fixture.review_ids[(kind, 1)]
        result = fixture.get(f"/reviews/{review_id}")
        assert result.status_code == 200, result.text
        data = result.json()
        assert data["review_id"] == str(review_id) and data["repository_id"] == "1"
        assert data["allowed_actions"] == ["approve", "reject"]
        assert "secret" not in str(data["resource_detail"])
        assert fixture.get(f"/reviews/{kind}/1").json()["review_id"] == str(review_id)
        assert fixture.get(f"/reviews/{review_id}", user=fixture.mine).json()["allowed_actions"] == []
        assert fixture.get(f"/reviews/{fixture.review_ids[(kind, 4)]}", user=fixture.mine).status_code == 404
        assert fixture.decision(kind, 1, user=fixture.mine).status_code == 403
        assert fixture.get(f"/reviews/{fixture.review_ids[(kind, 101)]}").status_code == 404
        for suffix in ("0", "-1", "9223372036854775808", "invalid"):
            assert fixture.get(f"/reviews/{suffix}").status_code == 400
        if kind == "mcp":
            with fixture.factory.begin() as session:
                session.execute(update(McpRecord).where(McpRecord.mcp_id == 1).values(mcp_server="https://edited.invalid"))
            assert fixture.get(f"/reviews/{review_id}").json()["resource_detail"] == data["resource_detail"]
    for index, reason in enumerate((None, " ", "x" * 1000, "😀" * 1000, "x" * 1001)):
        with fixture.factory.begin() as session:
            fixture.add(session, "agent", 300 + index, submitted_user_id=fixture.mine)
        response = fixture.decision("agent", 300 + index, reason=reason)
        assert response.status_code == (400 if len((reason or "").strip()) > 1000 else 200), response.text


def lifecycle_contract(fixture):
    from management.services.repository.reviews import save_submission
    for kind in REVIEW_MODELS:
        model, key, _, state_key, _ = REVIEW_MODELS[kind]
        with fixture.factory.begin() as session:
            review = fixture.add(session, kind, 200, submitted_user_id=fixture.mine, published=False)
            review_id = review.review_id
        pending = fixture.get(f"/reviews/{review_id}").json()
        assert pending["repository_id"] is None and pending["status"] == "pending_review"
        with fixture.factory() as session:
            assert session.get(model, 200) is None
        approved = fixture.decision(kind, 200).json()
        assert approved["status"] == "approved" and approved["repository_id"] is not None
        repository_id = int(approved["repository_id"])
        with fixture.factory.begin() as session:
            listing = session.get(model, repository_id)
            creation = listing.create_time
            assert getattr(listing, state_key) == "shared"
            setattr(listing, state_key, "not_shared")
        assert fixture.get(f"/reviews/{review_id}").json()["status"] == "approved"
        with fixture.factory() as session:
            frozen = session.get(ResourceReview, review_id).resource_snapshot["payload"]
        submitted = save_submission(kind, 200, fixture.tenant, fixture.mine, ("DEV",),
            {**frozen, "content": "New submission"}, version_no=1 if kind == "agent" else None,
            repository_id=repository_id)
        assert submitted["review_id"] != str(review_id)
        assert fixture.get(f"/reviews/{review_id}").json()["status"] == "approved"
        response = fixture.client.post(f"/reviews/{submitted['review_id']}/decision", headers=fixture.headers(),
            json={"decision": "reject", "reason": "New opinion"})
        assert response.status_code == 200 and response.json()["status"] == "rejected"
        with fixture.factory() as session:
            listing = session.get(model, repository_id)
            assert listing.create_time == creation and getattr(listing, state_key) == "not_shared"
        assert fixture.decision(kind, 200).status_code == 409


def concurrency_contract(fixture):
    for kind in REVIEW_MODELS:
        with fixture.factory() as session:
            before = session.scalar(select(func.count()).select_from(Notification))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda value: fixture.decision(kind, 1, decision=value), ("approve", "reject")))
        assert sorted(response.status_code for response in results) == [200, 409]
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(Notification)) == before + 1
        assert fixture.decision(kind, 1).status_code == 409
    before = fixture.get(f"/reviews/{fixture.review_ids[('agent', 4)]}").json()
    def fail_flush(session, *_):
        if any(isinstance(row, ResourceReview) for row in session.dirty):
            raise RuntimeError("Controlled flush failure")
    event.listen(fixture.factory.class_, "before_flush", fail_flush)
    try:
        try:
            fixture.decision("agent", 4)
        except RuntimeError as exc:
            assert str(exc) == "Controlled flush failure"
        else:
            raise AssertionError("Transaction failure did not reach caller")
    finally:
        event.remove(fixture.factory.class_, "before_flush", fail_flush)
    assert fixture.get(f"/reviews/{fixture.review_ids[('agent', 4)]}").json() == before


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
            session.execute(update(SkillInfo).where(SkillInfo.skill_id == 3).values(created_by=fixture.mine))
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
