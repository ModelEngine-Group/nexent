# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Disposable PostgreSQL storage with real product queries and configuration."""

import sys
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy.orm import Session
from sqlalchemy import event
from sqlalchemy.schema import CreateSchema, DropSchema

from management.services.model import run_bindings
from contracts.constants.constants import MODEL_CONFIG_MAPPING
from management.db import client as client
from management.db import models as db_models
from model_controls.api import CAPABILITY, BUDGET


@contextmanager
def database_fixture(monkeypatch, provider):
    schema = "model_controls_test_" + uuid4().hex
    tenant = "model-controls-" + uuid4().hex
    owner = "model-control-owner-" + uuid4().hex
    engine = client.db_client.engine.execution_options(schema_translate_map={"nexent": schema})
    def rewrite_schema(connection, cursor, statement, parameters, context, executemany):
        # Product text queries need the same isolation as ORM-compiled queries.
        return statement.replace('"nexent".', f'"{schema}".').replace("nexent.", schema + "."), parameters

    def search_path(connection):
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}", public')

    event.listen(engine, "before_cursor_execute", rewrite_schema, retval=True)
    event.listen(engine, "begin", search_path)
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        with engine.begin() as connection:
            db_models.ModelRecord.metadata.create_all(connection)
            if db_models.RolePermission.metadata is not db_models.ModelRecord.metadata:
                db_models.RolePermission.metadata.create_all(connection)
    except BaseException:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        raise

    @contextmanager
    def sessions(existing=None):
        if existing is not None:
            yield existing
            return
        with Session(engine) as session, session.begin():
            yield session

    original_session = client.get_db_session
    # Conversation DAC resolves this table lazily; load it before session routing.
    import importlib
    for module_name in ("management.db.identity.user_tenant", "management.db.model.outlets", "management.db.conversation.model_preferences"):
        importlib.import_module(module_name)
    for name, module in list(sys.modules.items()):
        if name.startswith("management.db.") and getattr(module, "get_db_session", None) is original_session:
            monkeypatch.setattr(module, "get_db_session", sessions)
    monkeypatch.setattr(client, "get_db_session", sessions)
    monkeypatch.setattr(run_bindings, "_resolve_reasoning_capability",
                        lambda model_name, **kwargs: BUDGET if "budget" in model_name else CAPABILITY)

    models = {}
    try:
        with sessions() as session:
            session.add(db_models.UserTenant(user_id=owner, tenant_id=tenant, user_role="CREATOR",
                                            user_email="model-controls@fixture.invalid", created_by=owner, updated_by=owner))
            for label, capacity, effort in [("default-A", 16000, "low"), ("selected-B", 8000, "medium"),
                                            ("budget-B", 10000, "auto"), ("business-C", 12000, "high")]:
                record = db_models.ModelRecord(
                    model_repo="", model_name="fixture-" + label, display_name=label,
                    tenant_id=tenant, model_type="llm", model_factory="OpenAI", base_url=provider.url + "/" + label,
                    api_key="fixture-key", connect_status="available", temperature=0.43, top_p=0.78,
                    context_window_tokens=capacity, max_input_tokens=capacity - 1000, max_output_tokens=1000,
                    default_output_reserve_tokens=1000, capacity_source="operator",
                    extra_params={"enable_thinking": True, "reasoning_effort": effort,
                                  **({"reasoning_budget_tokens": 2048} if "budget" in label else {}),
                                  "__custom__": {"fixture_custom": "retained"}},
                    created_by=owner, updated_by=owner,
                )
                session.add(record)
                session.flush()
                from model_controls.profiles import frozen_fixture_profile
                from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
                from nexent.core.model_service.registry import model_service_references
                row = {column.name: getattr(record, column.name) for column in record.__table__.columns}
                profile = frozen_fixture_profile(row, BUDGET if "budget" in label else CAPABILITY)
                for key, value in encode_resolved_model_profile(profile, registered_references=model_service_references()).items():
                    setattr(record, key, value)
                models[label] = record.model_id
            session.add(db_models.TenantConfig(
                tenant_id=tenant, user_id=owner, config_key=MODEL_CONFIG_MAPPING["llm"],
                config_value=str(models["default-A"]), created_by=owner, updated_by=owner,
            ))
            actor = db_models.AgentInfo(
                version_no=0, name="model_control_fixture_assistant", display_name="Model control fixture",
                description="Original fixture draft", model_ids=list(models.values())[:3], max_steps=3,
                tenant_id=tenant, enabled=True, provide_run_summary=False, is_main_agent=True,
                group_ids="[]", ingroup_permission="PRIVATE", created_by=owner, updated_by=owner,
                prompt="Complete the fixture task.", allow_chat_metadata=False, requested_output_tokens=99,
                example_questions=[], greeting_message="",
                model_params_override={str(value): {"context_window_tokens": 256, "parameter_values": {"max_output_tokens": 99, **({"temperature": 0.56} if key == "selected-B" else {})}}
                                       for key, value in list(models.items())[:3]},
            )
            session.add(actor)
            session.flush()
            agent_id = actor.agent_id
            actor.business_logic_model_id = models["business-C"]
            child = db_models.AgentInfo(
                version_no=0, name="fixture_child", display_name="Fixture child", description="Independent child",
                tenant_id=tenant, model_ids=[models["business-C"]], max_steps=1, enabled=True,
                is_main_agent=False, provide_run_summary=False, group_ids="[]", ingroup_permission="PRIVATE",
                created_by=owner, updated_by=owner, prompt="Return the fixture result.",
                example_questions=[], greeting_message="",
            )
            session.add(child)
            session.flush()
            session.add(db_models.AgentRelation(parent_agent_id=agent_id, selected_agent_id=child.agent_id,
                                                selected_agent_version_no=0, version_no=0, tenant_id=tenant,
                                                created_by=owner, updated_by=owner))
            from management.services.agent.system import system_agent_provider
            for version in (0, 1):
                session.add(db_models.AgentInfo(
                    agent_id=agent_id + 1000, version_no=version, current_version_no=1,
                    agent_origin="SYSTEM", system_key=system_agent_provider.system_key,
                    system_revision="fixture", name="workbench_main", display_name="Fixture Workbench",
                    model_ids=[models["default-A"]], max_steps=3, enabled=True, tenant_id=tenant,
                    is_main_agent=True, provide_run_summary=False, group_ids="[]", ingroup_permission="READ_ONLY",
                    created_by=owner, updated_by=owner, prompt="Complete fixture tasks.",
                    example_questions=[], greeting_message="",
                ))
                session.flush()
            for typ, sub in [("agent", "create"), ("skill", "create"), ("agent", "read"), ("agent", "use")]:
                session.add(db_models.RolePermission(user_role="CREATOR", permission_category="RESOURCE",
                                                    permission_type=typ, permission_subtype=sub))
            for kind in ("embedding", "stt", "tts"):
                session.add(db_models.ModelRecord(model_repo="", model_name="fixture-" + kind,
                                                 display_name="Independent " + kind, tenant_id=tenant,
                                                 model_type=kind, model_factory="OpenAI", base_url=provider.url + "/" + kind,
                                                 api_key="fixture-key", connect_status="available",
                                                 created_by=owner, updated_by=owner))
        yield {"schema": schema, "tenant": tenant, "owner": owner, "models": models,
               "agent_id": agent_id, "sessions": sessions, "engine": engine}
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        event.remove(engine, "before_cursor_execute", rewrite_schema)
        event.remove(engine, "begin", search_path)
