# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Store tenant cleanup intervals in the existing configuration table."""

from sqlalchemy import func, select, text

# isort: split
from contracts.trajectory import CleanupScheduleRequest
from management.db.client import get_db_session
from management.db.configuration.models import TenantConfig

SCHEDULE_KEY = "trajectory.cleanup_interval_seconds"


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
            value = int(row.config_value)
            return CleanupScheduleRequest(interval_seconds=value).interval_seconds

    def read_all(self):
        with get_db_session() as session:
            session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            rows = session.scalars(self._statement().limit(1001)).all()
            if len(rows) > 1000:
                raise ValueError("Cleanup configuration exceeds the tenant budget")
            values = {}
            for row in rows:
                if row.tenant_id not in values:
                    values[row.tenant_id] = CleanupScheduleRequest(
                        interval_seconds=int(row.config_value),
                    ).interval_seconds
            return values

    def save(self, tenant_id, interval_seconds, actor_id):
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
            row.config_value = str(interval_seconds)
            row.user_id = actor_id
            row.updated_by = actor_id
            row.update_time = func.current_timestamp()
