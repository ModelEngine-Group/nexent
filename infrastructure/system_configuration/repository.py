# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared persistence for validated system configuration snapshots."""

from collections import Counter

from infrastructure.system_configuration.catalog import (
    DEFAULT_CATALOG,
    ConfigurationValidationError,
    ConfigInput,
    SystemConfigurationSnapshot,
)
from infrastructure.system_configuration.models import SystemConfiguration
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

CONFIGURATION_LOCK_NAME = "nexent_system_configuration"
CONFIGURATION_READER_ROLE = "nexent_configuration_reader"


class SystemConfigurationRepository:
    """Hide ORM rows and transaction details from services and consumers."""

    def load_snapshot(
        self,
        session: Session,
        *,
        read_only: bool = False,
    ) -> SystemConfigurationSnapshot:
        if read_only:
            session.execute(text(f"SET LOCAL ROLE {CONFIGURATION_READER_ROLE}"))
        rows = session.scalars(
            select(SystemConfiguration).where(SystemConfiguration.delete_flag == "N")
        ).all()
        counts = Counter(row.configuration_key for row in rows)
        duplicates = sorted(key for key, count in counts.items() if count > 1)
        if duplicates:
            raise ConfigurationValidationError(
                f"Duplicate active configuration keys: {', '.join(duplicates)}"
            )
        values = {row.configuration_key: row.configuration_value for row in rows}
        return DEFAULT_CATALOG.build_snapshot(values)

    def save_changes(
        self,
        session: Session,
        changes: dict[str, ConfigInput],
        *,
        actor: str,
    ) -> SystemConfigurationSnapshot:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"),
            {"lock_name": CONFIGURATION_LOCK_NAME},
        )
        current = self.load_snapshot(session)
        snapshot = DEFAULT_CATALOG.validate_changes(current.values, changes)
        for key in changes:
            value = snapshot.get(key)
            if current.get(key) == value:
                continue
            session.execute(
                update(SystemConfiguration)
                .where(
                    SystemConfiguration.configuration_key == key,
                    SystemConfiguration.delete_flag == "N",
                )
                .values(
                    configuration_value=list(value) if isinstance(value, tuple) else value,
                    updated_by=actor[:100] or "unknown",
                    update_time=func.now(),
                )
            )
        return snapshot
