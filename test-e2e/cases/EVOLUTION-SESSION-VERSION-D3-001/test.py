# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import text

from local_auth_http import native_runtime, runtime


@pytest.mark.case_id("EVOLUTION-SESSION-VERSION-D3-001")
@pytest.mark.stage("D3")
def test_session_versions(runtime):
    from contracts.errors.exceptions import ForbiddenError
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.rdb.agent_execution import AgentExecution
    from infrastructure.rdb.conversation_record import ConversationMessage, ConversationRecord
    from management.db.agent.session_versions import (
        ReleaseVersionConflict,
        confirm_chat_version,
        discard_unstarted_binding,
        lock_release_scope,
        select_chat_version,
    )

    _, _, _, models = runtime
    models.TableBase.metadata.create_all(db_client.engine)
    migrations = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    with db_client.engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        for name in (
            "003_conversation_run_admission",
            "006_prepared_conversation_turn",
            "011_trajectory",
            "015_conversation_evolution",
            "018_evolution_replay_cases",
            "019_evolution_experiments",
            "028_evolution_confirmation_suites",
            "029_evolution_confirmation_locks",
            "030_evolution_confirmation_results",
            "031_evolution_session_versions",
            "032_evolution_releases",
        ):
            cursor.execute((migrations / f"v2.9.0_{name}.sql").read_text(encoding="utf-8"))
    tenant, owner, agent = "release-pilot", "chat-user", 901
    with get_db_session() as session:
        for version in range(4):
            session.add(
                models.AgentInfo(
                    agent_id=agent,
                    tenant_id=tenant,
                    version_no=version,
                    name="meeting",
                    current_version_no=1 if version == 0 else None,
                    created_by=owner,
                    delete_flag="N",
                )
            )
            session.flush()
        session.add(
            AgentExecution(
                run_id="a" * 32,
                conversation_id=31,
                tenant_id=tenant,
                created_by=owner,
                status="completed",
                resource_versions={"agent_id": agent, "agent_version_no": 1, "model_revision": "pilot"},
                delete_flag="N",
            )
        )
        session.add(ConversationRecord(conversation_id=41, agent_id=agent, created_by=owner, delete_flag="N"))
        session.add(
            ConversationMessage(
                message_id=41,
                conversation_id=41,
                message_role="user",
                message_index=0,
                message_content="old question",
                created_by=owner,
                delete_flag="N",
            )
        )

    def default(version):
        with get_db_session() as session:
            lock_release_scope(session, tenant, agent, exclusive=True)
            session.execute(
                text("""INSERT INTO nexent.evolution_release_scope_t(tenant_id,agent_id,initial_version)
                VALUES (:tenant,:agent,1) ON CONFLICT DO NOTHING"""),
                dict(tenant=tenant, agent=agent),
            )
            session.execute(
                text("""UPDATE nexent.ag_tenant_agent_t SET current_version_no=:v
                WHERE tenant_id=:tenant AND agent_id=:agent AND version_no=0"""),
                dict(v=version, tenant=tenant, agent=agent),
            )

    def read(cid, hint=1):
        return select_chat_version(tenant, agent, cid, owner, hint)

    def stage(cid, hint, compiled):
        with get_db_session() as session:
            confirm_chat_version(session, tenant, agent, cid, owner, hint, compiled)

    assert read(11) is None
    default(2)
    assert read(11) == read(12) == 2
    stage(11, 1, 2)
    default(3)
    assert read(11) == 2 and read(12) == 3
    with pytest.raises(ReleaseVersionConflict):
        stage(12, 1, 2)
    gate = Barrier(2)

    def first_turn(_):
        gate.wait(timeout=10)
        stage(12, 1, 3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(first_turn, range(2)))
    default(2)
    assert (read(11), read(12), read(13), read(31), read(41, None)) == (2, 3, 2, 1, 1)
    stage(31, 2, 1)
    stage(41, None, 1)
    with get_db_session() as session:
        assert confirm_chat_version(session, tenant, agent, 51, owner, 1, 2)
        discard_unstarted_binding(session, tenant, owner, 51, "c" * 32, agent, 2)
        assert not confirm_chat_version(session, tenant, agent, 31, owner, 2, 1)
        discard_unstarted_binding(session, tenant, owner, 31, "a" * 32, agent, 1)
    assert select_chat_version("other-tenant", agent, 12, owner, 2) is None
    with pytest.raises(ForbiddenError):
        select_chat_version(tenant, agent, 12, "other-user", 2)
    with get_db_session() as session:
        assert session.execute(
            text("""SELECT conversation_id,version_no FROM nexent.evolution_session_version_t
            WHERE tenant_id=:t ORDER BY conversation_id"""),
            {"t": tenant},
        ).all() == [(11, 2), (12, 3), (31, 1)]
