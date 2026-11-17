# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Store tenant cleanup policies in the existing configuration table."""

import json

from sqlalchemy import func, select, text

# isort: split
from contracts.trajectory import CleanupPolicy
from management.db.client import get_db_session
from management.db.configuration.models import TenantConfig

SCHEDULE_KEY = "trajectory.cleanup_schedule"


class CleanupScheduleRepository:
    @staticmethod
    def _statement(tenant_id=None):
        statement = (
            select(TenantConfig)
            .where(
                TenantConfig.config_key == SCHEDULE_KEY,
                TenantConfig.delete_flag == "N",
            )
            .order_by(TenantConfig.tenant_config_id.desc())
        )
        return (
            statement.where(TenantConfig.tenant_id == tenant_id)
            if tenant_id is not None
            else statement
        )

    def read(self, tenant_id):
        with get_db_session() as session:
            session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            row = session.scalars(self._statement(tenant_id).limit(1)).first()
            if row is None:
                return None
            return CleanupPolicy.model_validate_json(row.config_value).model_dump()

    def read_all(self):
        with get_db_session() as session:
            session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            rows = session.scalars(self._statement().limit(1001)).all()
            if len(rows) > 1000:
                raise ValueError("Cleanup configuration exceeds the tenant budget")
            values = {}
            for row in rows:
                if row.tenant_id not in values:
                    values[row.tenant_id] = CleanupPolicy.model_validate_json(row.config_value).model_dump()
            return values

    def save(self, tenant_id, policy, actor_id):
        value = CleanupPolicy.model_validate(policy).model_dump()
        with get_db_session() as session:
            session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"{SCHEDULE_KEY}:{tenant_id}"},
            )
            row = session.scalars(self._statement(tenant_id).limit(1)).first()
            if row is None:
                row = TenantConfig(
                    tenant_id=tenant_id,
                    config_key=SCHEDULE_KEY,
                    value_type="single",
                    created_by=actor_id,
                    delete_flag="N",
                )
                session.add(row)
            row.config_value = json.dumps(value, separators=(",", ":"))
            row.user_id = actor_id
            row.updated_by = actor_id
            row.update_time = func.current_timestamp()

    def save_many(self, tenant_ids, policy, actor_id):
        """Apply one policy atomically, sharing the locks used by tenant saves."""
        targets = sorted(set(tenant_ids))
        if not targets or len(targets) > 1000 or any(not target.strip() for target in targets):
            raise ValueError("Invalid cleanup tenant scope")
        value = json.dumps(CleanupPolicy.model_validate(policy).model_dump(), separators=(",", ":"))
        with get_db_session() as session:
            session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            session.execute(
                text(
                    "SELECT pg_advisory_xact_lock(hashtext(key)) FROM "
                    "(SELECT unnest(CAST(:keys AS text[])) AS key ORDER BY key) AS ordered_keys"
                ),
                {"keys": [f"{SCHEDULE_KEY}:{tenant}" for tenant in targets]},
            )
            rows = session.scalars(self._statement().where(TenantConfig.tenant_id.in_(targets))).all()
            latest = {}
            for row in rows:
                latest.setdefault(row.tenant_id, row)
            for tenant in targets:
                row = latest.get(tenant)
                if row is None:
                    row = TenantConfig(
                        tenant_id=tenant, config_key=SCHEDULE_KEY, value_type="single",
                        created_by=actor_id, delete_flag="N",
                    )
                    session.add(row)
                row.config_value = value
                row.user_id = actor_id
                row.updated_by = actor_id
                row.update_time = func.current_timestamp()
