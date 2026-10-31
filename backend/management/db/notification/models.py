# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Index,
    Sequence,
    String,
)


from sqlalchemy.dialects.postgresql import JSONB


from management.db.base import SCHEMA, TableBase, _TENANT_ID_DOC


class Notification(TableBase):
    """
    In-app notification message table. One row per message; actual per-user
    delivery and read state live in notification_receiver_t (fan-out).
    """
    __tablename__ = "notification_t"

    notification_id = Column(
        BigInteger,
        Sequence("notification_t_notification_id_seq", schema=SCHEMA),
        primary_key=True, nullable=False,
        doc="Notification ID, unique primary key")
    event_type = Column(String(50), nullable=False,
                        doc="Event type, e.g. repository_review_approved / repository_review_rejected")
    resource_type = Column(String(50), nullable=False,
                           doc="Resource type, e.g. agent_repository / skill_repository / mcp_repository")
    unique_id = Column(BigInteger,
                       doc="Related resource primary key (e.g. agent_repository_id)")
    details = Column(JSONB, doc="i18n interpolation details for the event template")
    scope = Column(String(20), nullable=False,
                          doc="Audience scope: SU / TENANT / TENANT_ADMIN / USER")
    tenant_id = Column(String(100),
                              doc="tenant for TENANT / TENANT_ADMIN scope; NULL for SU")
    is_active = Column(Boolean, nullable=False, default=True,
                       doc="Whether this notification is still active/valid")

    __table_args__ = (
        Index(
            "ix_notification_event_resource_unique_active",
            "event_type", "resource_type", "unique_id", "is_active",
        ),
        {"schema": SCHEMA},
    )


class NotificationReceiver(TableBase):
    """
    Per-user notification delivery and read status (fan-out from notification_t).
    """
    __tablename__ = "notification_receiver_t"

    receiver_id = Column(
        BigInteger,
        Sequence("notification_receiver_t_receiver_id_seq", schema=SCHEMA),
        primary_key=True, nullable=False,
        doc="Receiver row ID, unique primary key")
    notification_id = Column(BigInteger, nullable=False,
                             doc="FK to notification_t.notification_id")
    receiver_user_id = Column(String(100), nullable=False,
                               doc="Receiver user ID")
    tenant_id = Column(String(100), doc=_TENANT_ID_DOC)
    is_read = Column(Boolean, default=False,
                     doc="Whether this receiver has read the notification")

    __table_args__ = (
        Index("ix_notification_receiver_user_read", "receiver_user_id", "is_read"),
        Index("ix_notification_receiver_notification_id", "notification_id"),
        {"schema": SCHEMA},
    )
