# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Seed published Agents connected only to the case-owned model service."""

import json
import sys
from uuid import UUID, uuid5

from contracts.constants.constants import MODEL_CONFIG_MAPPING
from contracts.constants.environment import POSTGRES_HOST
from infrastructure.rdb.client import get_db_session
from management.db.agent.models import AgentInfo
from management.db.configuration.models import TenantConfig
from management.db.model.models import ModelRecord
from management.services.model.outlet_migration import build_legacy_outlet_snapshot
from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
from nexent.core.model_service.registry import model_service_references


def seed_model(session, owner, tenant):
    record = ModelRecord(model_repo="", model_name="runtime-scaling-fixture", display_name="Runtime scaling fixture",
                         tenant_id=tenant, model_type="llm", model_factory="OpenAI",
                         base_url="http://nexent-rs-model:8090/v1", api_key="test-only",
                         connect_status="available", context_window_tokens=16000, max_input_tokens=15000,
                         max_output_tokens=1000, default_output_reserve_tokens=1000, timeout_seconds=330,
                         capacity_source="operator", created_by=owner, updated_by=owner)
    session.add(record)
    session.flush()
    row = {column.name: getattr(record, column.name) for column in record.__table__.columns}
    profile = build_legacy_outlet_snapshot(row, legacy_capability={"status": "unsupported"}, migrated_at="fixture")
    for key, value in encode_resolved_model_profile(profile, registered_references=model_service_references()).items():
        setattr(record, key, value)
    session.add(TenantConfig(tenant_id=tenant, user_id=owner, config_key=MODEL_CONFIG_MAPPING["llm"],
                             config_value=str(record.model_id), created_by=owner, updated_by=owner))
    return record


def seed_agent(token, *, other_scope=False, role="owner"):
    owner = str(uuid5(token, f"{role}:user"))
    tenant = str(uuid5(token, f"{role}:tenant"))
    with get_db_session() as session:
        record = seed_model(session, owner, tenant)
        values = dict(name="runtime_scaling_fixture", display_name="Runtime scaling fixture", description="Test-only Agent",
                      current_version_no=1, model_ids=[record.model_id], max_steps=3, tenant_id=tenant, enabled=True,
                      provide_run_summary=False, is_main_agent=True, group_ids="[]", ingroup_permission="PRIVATE",
                      created_by=owner, updated_by=owner, prompt="Run the supplied storage fixture task.",
                      example_questions=[], greeting_message="")
        def publish(name, display_name):
            fields = {**values, "name": name, "display_name": display_name}
            draft = AgentInfo(version_no=0, **fields)
            session.add(draft)
            session.flush()
            session.add(AgentInfo(agent_id=draft.agent_id, version_no=1, **fields))
            return draft.agent_id

        result = {"agent_id": publish(values["name"], values["display_name"]), "model_id": record.model_id}
        if other_scope:
            result["other_agent_id"] = publish("runtime_fixture_other_scope", "Runtime fixture other scope")
        return result


def seed_workbench(token):
    from contracts.agent import WorkbenchSessionConfig
    from management.configuration.runtime import load_system_configuration
    from management.services.conversation.service import create_new_conversation

    load_system_configuration()
    config = WorkbenchSessionConfig(mode="generic_chat").model_dump(mode="json")
    prepared = {}
    for role, labels in (("owner", ("contested", "second", "candidate")), ("foreign", ("isolated",))):
        user = str(uuid5(token, f"{role}:user"))
        tenant = str(uuid5(token, f"{role}:tenant"))
        with get_db_session() as session:
            model_id = seed_model(session, user, tenant).model_id
        prepared[role] = {}
        for label in labels:
            conversation = create_new_conversation(f"Runtime Workbench {token}:{label}", user, workbench_config=config)
            prepared[role][label] = {"model_id": model_id, "conversation_id": conversation["conversation_id"],
                                     "expected_workbench_config_version": conversation["workbench_config_version"]}
    return prepared


def seed_creators(token, kind):
    from contracts.agent import WorkbenchSessionConfig
    from management.configuration.runtime import load_system_configuration
    from management.services.agent.system import system_agent_provider
    from management.services.conversation.creation_history import create_creation_conversation

    if kind not in {"agent", "skill"}:
        raise ValueError("Unknown creator fixture kind")
    load_system_configuration()
    mode = f"{kind}_create"
    config = WorkbenchSessionConfig(mode=mode).model_dump(mode="json")
    prepared = {}
    for role, labels in (("owner", ("contested", "second", "candidate")), ("foreign", ("isolated",))):
        user = str(uuid5(token, f"{role}:user"))
        tenant = str(uuid5(token, f"{role}:tenant"))
        agent = seed_agent(token, role=role)
        model_id = agent["model_id"]
        ref = system_agent_provider.get_creator_ref(tenant, f"nl2{kind}_main")
        target = {"type": "agent", "id": agent["agent_id"]} if kind == "agent" else None
        prepared[role] = {}
        for label in labels:
            conversation = create_creation_conversation(
                mode=mode, query=f"Runtime Creator {token}:{label}", workbench_config=config,
                agent_id=ref.agent_id, user_id=user, target=target, selected_model_id=model_id,
            )
            prepared[role][label] = {"model_id": model_id, "conversation_id": conversation,
                                     **({"target": target} if target else {})}
    return prepared


def main():
    raw_token, *options = sys.argv[1:]
    token = UUID(hex=raw_token)
    if options not in ([], ["other-scope"], ["storage-pair"], ["workbench"], ["creator", "agent"], ["creator", "skill"]) or (
        token.hex != raw_token or POSTGRES_HOST not in {
        "nexent-postgresql", "nexent-postgresql.nexent", "nexent-postgresql.nexent.svc",
        "nexent-postgresql.nexent.svc.cluster.local",
    }):
        raise RuntimeError("Agent preparation requires the case-owned database")
    if options == ["workbench"]:
        print("SCALING_WORKBENCH " + json.dumps(seed_workbench(token)))
    elif options[:1] == ["creator"]:
        print("SCALING_CREATORS " + json.dumps(seed_creators(token, options[1])))
    elif options == ["storage-pair"]:
        print("SCALING_AGENT " + json.dumps({role: seed_agent(token, role=role) for role in ("owner", "foreign")}))
    else:
        print("SCALING_AGENT " + json.dumps(seed_agent(token, other_scope=bool(options))))


if __name__ == "__main__":
    main()
