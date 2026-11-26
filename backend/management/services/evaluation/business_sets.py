# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scope business evaluation sets to Agent editors and select exact replay tasks."""

from contracts.evolution_sources import task_digest
from infrastructure.rdb.client import get_db_session
from management.db.evaluation import business_sets as sets
from management.db.evaluation.replay_cases import save_replay_case
from management.services.evaluation.evolution_access import published_business_agent, require_business_agent_edit


def list_business_sets(tenant, user, agent):
    require_business_agent_edit(agent, tenant, user)
    return sets.list_sets(tenant, agent)


def business_case_choices(tenant, user, agent):
    require_business_agent_edit(agent, tenant, user)
    return sets.list_case_choices(tenant, agent)


def create_business_set(tenant, user, agent, name):
    require_business_agent_edit(agent, tenant, user)
    with get_db_session() as session:
        return sets.create_set(session, tenant, agent, user, name)


def read_business_set(tenant, user, agent, set_id):
    require_business_agent_edit(agent, tenant, user)
    with get_db_session() as session:
        return sets.read_set(session, tenant, agent, set_id)


def add_business_set_cases(tenant, user, agent, set_id, ids):
    require_business_agent_edit(agent, tenant, user)
    with get_db_session() as session:
        return sets.add_cases(session, tenant, agent, user, set_id, ids)


def remove_business_set_case(tenant, user, agent, set_id, case_id):
    require_business_agent_edit(agent, tenant, user)
    with get_db_session() as session:
        return sets.remove_case(session, tenant, agent, user, set_id, case_id)


def select_business_set(tenant, user, agent, version, set_id):
    require_business_agent_edit(agent, tenant, user)
    published_business_agent(tenant, agent, version)
    with get_db_session() as session:
        group = sets.read_set(session, tenant, agent, set_id, include_tasks=True)
        selected = []
        for member in group["cases"]:
            task = member.pop("task")
            if task_digest(task) != member["digest"]:
                raise ValueError("Replay task integrity check failed")
            if member["version_no"] != version:
                copy = save_replay_case(tenant, agent, version, user, task, transaction=session)
                member = {**member, "case_id": copy["case_id"], "version_no": version}
            if "expected_skill_names" in task:
                member["expected_skill_names"] = task["expected_skill_names"]
            selected.append(member)
        return selected
