"""Regression protection for tenant ownership on relation creation/restoration."""

import pytest

from test.backend.database import test_a2a_agent_db as legacy


@pytest.mark.parametrize("target", ["parent", "external"])
@pytest.mark.parametrize("invalid", ["missing", "foreign", "deleted"])
@pytest.mark.parametrize("restore", [False, True])
def test_invalid_reference_never_writes_or_restores(mocker, target, invalid, restore):
    parent = legacy.db_models_mock.AgentInfo(
        agent_id=100, tenant_id="tenant-1", version_no=0, delete_flag="N")
    external = legacy.factory_external_agent(id=1)
    record = parent if target == "parent" else external
    if invalid == "foreign":
        record.tenant_id = "tenant-2"
    if invalid == "deleted":
        record.delete_flag = "Y"
    relation = legacy.factory_external_relation(delete_flag="Y", is_enabled=False)
    session = legacy.MockSession({
        legacy.db_models_mock.AgentInfo: [] if target == "parent" and invalid == "missing" else [parent],
        legacy.db_models_mock.A2AExternalAgent: [] if target == "external" and invalid == "missing" else [external],
        legacy.db_models_mock.A2AExternalAgentRelation: [relation] if restore else [],
    })
    add = mocker.patch.object(session, "add", wraps=session.add)
    mocker.patch.object(legacy.a2a_db, "_get_db_session", return_value=session)
    with pytest.raises(legacy.AgentNotFoundError):
        legacy.a2a_db.add_external_agent_relation(100, 1, "tenant-1", "user-1")
    add.assert_not_called()
    assert not session.flushed
    assert relation.delete_flag == "Y"
    assert relation.is_enabled is False


@pytest.mark.parametrize("reader", ["query_external_sub_agents", "list_external_relations_by_local_agent"])
def test_read_filters_both_relation_and_external_tenants(mocker, reader):
    session = legacy.MockSession()
    query = session.query(legacy.db_models_mock.A2AExternalAgentRelation, legacy.db_models_mock.A2AExternalAgent)
    filters = mocker.patch.object(query, "filter", wraps=query.filter)
    mocker.patch.object(session, "query", return_value=query)
    mocker.patch.object(legacy.a2a_db, "_get_db_session", return_value=session)
    assert getattr(legacy.a2a_db, reader)(100, "tenant-1") == []
    tenant_checks = [arg for arg in filters.call_args.args if arg._name == "tenant_id"]
    assert len(tenant_checks) == 2
    assert all(arg._val == "tenant-1" for arg in tenant_checks)
