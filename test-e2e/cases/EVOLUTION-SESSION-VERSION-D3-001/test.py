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
            "033_evolution_release_tools",
            "035_evolution_release_guides",
            "036_evolution_skill_catalog_entry",
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


    from management.db.agent.release_tools import excluded_for_version, publish_tool_selection
    from management.db.agent.repository import search_agent_info_by_agent_id

    with get_db_session() as session:
        publish_tool_selection(session, tenant, agent, 1, 2, ["analyze_text_file"])
        publish_tool_selection(session, tenant, agent, 2, 3, ["create_file"])
        assert excluded_for_version(session, "other-tenant", agent, 3) == []
        assert excluded_for_version(session, tenant, agent+1, 3) == []
    assert "released_tool_exclusions" not in search_agent_info_by_agent_id(agent, tenant, 0)
    assert "released_tool_exclusions" not in search_agent_info_by_agent_id(agent, tenant, 1)
    assert search_agent_info_by_agent_id(agent, tenant, 2)["released_tool_exclusions"] == ["analyze_text_file"]
    assert search_agent_info_by_agent_id(agent, tenant, 3)["released_tool_exclusions"] == ["analyze_text_file","create_file"]

    from infrastructure.rdb.released_skill_guides import guides_for_version, publish_guides

    first_guide = {"candidate_id": 5, "name": "intake", "digest": "a"*64}
    with get_db_session() as session:
        publish_guides(session, tenant, agent, 1, 2, first_guide)
        publish_guides(session, tenant, agent, 2, 3, None)
        assert not guides_for_version(session, "other-tenant", agent, 3)
        assert not guides_for_version(session, tenant, agent+1, 3)
        with pytest.raises(ValueError, match="already has this name"):
            publish_guides(session, tenant, agent, 3, 4, first_guide)
        assert not guides_for_version(session, tenant, agent, 4)
    assert "released_skill_guides" not in search_agent_info_by_agent_id(agent, tenant, 0)
    assert "released_skill_guides" not in search_agent_info_by_agent_id(agent, tenant, 1)
    for version in (2,3):
        assert search_agent_info_by_agent_id(agent, tenant, version)["released_skill_guides"] == [first_guide]

    from infrastructure.rdb.skill_execution_records import SkillInfo, SkillInstance, read_bound_skills
    from management.db.evaluation.releases import _pin
    from management.services.skill.service import SkillService

    with get_db_session() as session:
        shared = SkillInfo(tenant_id=tenant, skill_name="meeting-notes", skill_description="old", source="custom")
        session.add(shared)
        session.flush()
        skill_id = shared.skill_id
        for owner_agent, instance, versions in ((agent, 710, [1, 2]), (agent+1, 711, [2])):
            for version in versions:
                session.add(SkillInstance(tenant_id=tenant, agent_id=owner_agent, version_no=version,
                                          skill_id=skill_id, skill_instance_id=instance, enabled=True))
        session.flush()
        source = {"instance_id": 710, "name": "meeting-notes", "description": "old", "config": {}}
        package = ("d"*64, {"SKILL.md": b"same steps"})
        pin = {"skill_id": skill_id, "row": source, "base": package, "result": package, "result_description": "new"}
        _pin(session, tenant, agent, 1, pin, "base")
        _pin(session, tenant, agent, 2, pin, "result")
        shared.skill_description = "later catalog edit"
    for owner_agent, version, expected in ((agent, 1, "old"), (agent, 2, "new"), (agent+1, 2, "later catalog edit")):
        runtime_row, = read_bound_skills(owner_agent, version, tenant)
        template_entry, = SkillService().get_enabled_skills_for_agent(owner_agent, tenant, version)
        assert template_entry["description"] == runtime_row["description"] == expected
    assert not read_bound_skills(agent, 2, "other-tenant")
