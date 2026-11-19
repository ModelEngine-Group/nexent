# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace

import pytest

from local_auth_http import native_runtime

pytestmark = [pytest.mark.case_id("AUTH-RESOURCE-GROUP-PERMISSIONS-D2-001"), pytest.mark.stage("D2")]


def test_resource_sharing_round_trip(native_runtime, monkeypatch):
    client, _, auth, models = native_runtime
    from management.api.agent import agent as agent_api
    from management.api.knowledge_base import vectordatabase
    from management.db.agent.repository import search_agent_info_by_agent_id
    from management.db.agent.version import insert_agent_snapshot
    from infrastructure.rdb.client import db_client, get_db_session
    from management.db.identity.account import create_account
    from management.db.identity.user_tenant import insert_user_tenant
    from management.db.knowledge_base.repository import get_knowledge_record
    from management.services.agent import service as agent_service
    from management.services.knowledge_base.permission import resolve_knowledge_base_permission

    tenant = "sharing-tenant"
    for table in (models.AgentInfo, models.KnowledgeRecord):
        table.__table__.create(db_client.engine)
    with get_db_session() as session:
        for name in ("owner", "reader", "editor", "outsider"):
            email = f"{name}@example.test"
            create_account(email, user_id=name, db_session=session)
            insert_user_tenant(name, tenant, "DEV", email, db_session=session)
        for group_id, scope in ((1, tenant), (2, tenant), (3, "foreign-tenant")):
            session.add(models.TenantGroupInfo(group_id=group_id, group_name=f"Group {group_id}", tenant_id=scope))
        session.add_all([
            models.TenantGroupUser(group_id=1, user_id="reader"),
            models.TenantGroupUser(group_id=1, user_id="editor"),
            models.TenantGroupUser(group_id=2, user_id="editor"),
            models.KnowledgeRecord(index_name="shared", knowledge_name="Shared", tenant_id=tenant,
                                   created_by="owner", ingroup_permission="EDIT", group_ids="1,2"),
            models.AgentInfo(agent_id=1, version_no=0, name="agent", display_name="Agent",
                             tenant_id=tenant, created_by="owner", ingroup_permission="EDIT", group_ids="1,2"),
        ])
    client.app.include_router(agent_api.agent_config_router, prefix="/api")
    client.app.include_router(vectordatabase.router, prefix="/api")
    monkeypatch.setattr(agent_api, "record_security_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(agent_service, "build_reasoning_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(agent_service, "project_agent_models", lambda *args, **kwargs: SimpleNamespace(
        fields={"model_ids": []}, availability_model_ids=[], deleted_model_ids=[],
    ))
    monkeypatch.setattr(agent_service, "check_agent_availability", lambda **kwargs: (True, []))
    monkeypatch.setattr(agent_service, "enrich_cas_usernames", lambda *args, **kwargs: None)

    headers = {name: {"Authorization": f"Bearer {auth.generate_session_jwt(name)}"}
               for name in ("owner", "reader", "editor", "outsider")}

    def save_agent(user, **fields):
        return client.post("/api/agent/update", headers=headers[user], json={"agent_id": 1, **fields})

    def save_kb(user, **fields):
        return client.patch("/api/indices/shared", headers=headers[user], json=fields)

    rules = [{"group_id": 1, "permission": "READ_ONLY"}, {"group_id": 2, "permission": "EDIT"}]
    for save in (save_agent, save_kb):
        response = save("owner", group_permissions=rules)
        assert response.status_code == 200, response.text
    assert get_knowledge_record({"index_name": "shared"})["group_permissions"] == rules
    assert search_agent_info_by_agent_id(1, tenant)["group_permissions"] == rules

    for user, permission in (("reader", "READ_ONLY"), ("editor", "EDIT")):
        agent = client.post("/api/agent/search_info", headers=headers[user], json={"agent_id": 1, "version_no": 0})
        assert agent.status_code == 200, agent.text
        assert agent.json()["permission"] == permission
        assert agent.json()["group_permissions"] == rules
        assert resolve_knowledge_base_permission("shared", user, tenant) == permission
    assert resolve_knowledge_base_permission("shared", "outsider", tenant) is None
    assert client.post("/api/agent/search_info", headers=headers["outsider"],
                       json={"agent_id": 1, "version_no": 0}).status_code == 403
    assert client.get("/api/agent/1/versions", headers=headers["outsider"]).status_code == 403
    assert client.post("/api/agent/1/publish", headers=headers["reader"],
                       json={"version_name": "Forbidden"}).status_code == 403
    assert save_kb("reader", knowledge_name="Forbidden").status_code == 403
    assert save_agent("reader", description="Forbidden").status_code == 403
    assert save_kb("editor", knowledge_name="Renamed").status_code == 200
    assert save_agent("editor", description="Edited").status_code == 200
    assert save_kb("editor", group_permissions=[]).status_code == 403
    assert save_agent("editor", group_permissions=[]).status_code == 403

    insert_agent_snapshot({"agent_id": 1, "tenant_id": tenant, "version_no": 1,
                           "name": "agent", "created_by": "owner", "ingroup_permission": "EDIT"})
    assert search_agent_info_by_agent_id(1, tenant, 1)["group_permissions"] == rules
    for save in (save_agent, save_kb):
        foreign = save("owner", group_permissions=[{"group_id": 3, "permission": "EDIT"}])
        assert foreign.status_code == 400, foreign.text
        assert save("owner", group_ids=[1], ingroup_permission="EDIT").status_code == 200
    assert search_agent_info_by_agent_id(1, tenant)["group_permissions"] == rules
    assert get_knowledge_record({"index_name": "shared"})["group_permissions"] == rules
    for save in (save_agent, save_kb):
        response = save("owner", group_permissions=[])
        assert response.status_code == 200, response.text
    assert search_agent_info_by_agent_id(1, tenant, 1)["group_permissions"] == []
    assert save_agent("editor", description="Revoked").status_code == 403
    assert save_kb("editor", knowledge_name="Revoked").status_code == 403
