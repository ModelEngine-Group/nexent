# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from datetime import datetime

from sqlalchemy import TIMESTAMP, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from management.db.base import SCHEMA, TableBase


class ExecutionReservation(TableBase):
    """Persist coordination facts without storing a Runtime worker or payload."""

    __tablename__ = "execution_reservation_t"
    __table_args__ = {"schema": SCHEMA}

    execution_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str | None] = mapped_column(String(100))
    user_id: Mapped[str | None] = mapped_column(String(100))
    execution_kind: Mapped[str] = mapped_column(String(30))
    service_role: Mapped[str] = mapped_column(String(30))
    execution_key: Mapped[str] = mapped_column(String(64))
    agent_scope: Mapped[str | None] = mapped_column(String(100))
    owner_instance_id: Mapped[str] = mapped_column(String(100))
    maintenance_epoch: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=False))
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=False))
    error_code: Mapped[str | None] = mapped_column(String(100))
