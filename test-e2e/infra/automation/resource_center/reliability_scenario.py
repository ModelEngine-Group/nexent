# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real transaction, immutable submission and post-commit delivery proofs."""

import logging
import subprocess
import sys
from unittest.mock import patch

from sqlalchemy import event, func, select

from contracts.errors.exceptions import ReviewConflictError
from management.db.models import McpRecord, Notification
from management.db.resource_review_model import ResourceReview
from management.services.repository import reviews, review_notifications
from management.db import repository_transactions


def reliability_contract(fixture):
    for kind in ("agent", "skill", "mcp"):
        with fixture.factory.begin() as session:
            record = fixture.add(session, kind, 900, submitted_user_id=fixture.mine)
            review_id = record.review_id
            frozen = record.resource_snapshot["payload"]
        try:
            reviews.save_submission(kind, 900, fixture.tenant, fixture.mine, ("DEV",),
                {**frozen, "content": "Replacement"}, version_no=1 if kind == "agent" else None,
                repository_id=900)
        except ReviewConflictError as exc:
            assert str(exc) == "PENDING_REVIEW_EXISTS"
        else:
            raise AssertionError("Pending snapshot was replaced")
        assert fixture.get(f"/reviews/{review_id}").json()["status"] == "pending_review"
        assert fixture.decision(kind, 900).status_code == 200
        assert fixture.decision(kind, 900, decision="reject").status_code == 409

    with fixture.factory.begin() as session:
        pending = fixture.add(session, "mcp", 960, submitted_user_id=fixture.mine, published=False)
        pending_id = pending.review_id
        before = session.scalar(select(func.count()).select_from(Notification))
    def fail_link(session, *_):
        if any(isinstance(row, ResourceReview) and row.review_id == pending_id
               and row.review_status == "approved" for row in session.dirty):
            raise RuntimeError("Controlled source-link failure")
    event.listen(fixture.factory.class_, "before_flush", fail_link)
    try:
        try:
            fixture.decision("mcp", 960)
        except RuntimeError as exc:
            assert str(exc) == "Controlled source-link failure"
        else:
            raise AssertionError("Injected publication failure was swallowed")
    finally:
        event.remove(fixture.factory.class_, "before_flush", fail_link)
    with fixture.factory() as session:
        assert session.get(McpRecord, 960).market_id is None
        assert session.get(ResourceReview, pending_id).review_status == "pending_review"
        assert session.scalar(select(func.count()).select_from(Notification)) == before
    assert fixture.decision("mcp", 960).status_code == 200

    logs = []
    class Capture(logging.Handler):
        def emit(self, record):
            logs.append(record.getMessage())
    handler = Capture()
    repository_transactions.logger.addHandler(handler)
    try:
        with fixture.factory.begin() as session:
            fixture.add(session, "agent", 970, submitted_user_id=fixture.mine)
        with patch.object(review_notifications, "create_notification", side_effect=RuntimeError("Controlled delivery failure")) as delivery:
            assert fixture.decision("agent", 970).status_code == 200
            assert fixture.get(f"/reviews/{fixture.review_ids[('agent', 970)]}").json()["status"] == "approved"
            assert fixture.decision("agent", 970).status_code == 409
            assert delivery.call_count == 1
        assert any("notification failed" in value for value in logs)
    finally:
        repository_transactions.logger.removeHandler(handler)

    with fixture.factory.begin() as session:
        pending = fixture.add(session, "agent", 980, submitted_user_id=fixture.mine)
        pending_id = pending.review_id
        before = session.scalar(select(func.count()).select_from(Notification))
    child = """
import os, sys
from sqlalchemy.orm import sessionmaker
from management.db.client import db_client
from management.services.repository import reviews, review_notifications
from management.db import repository_transactions
from contracts.review import ReviewDecisionRequest
engine = db_client.engine.execution_options(schema_translate_map={'nexent':sys.argv[1]})
db_client.session_maker = sessionmaker(bind=engine)
review_notifications.create_notification = lambda **kwargs: os._exit(37)
reviews.decide_repository_review(int(sys.argv[4]),sys.argv[3],sys.argv[2],('ADMIN',),ReviewDecisionRequest(decision='approve'))
raise SystemExit(99)
"""
    result = subprocess.run([sys.executable, "-c", child, fixture.schema, fixture.tenant, fixture.admin, str(pending_id)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 37, result.stderr[-3000:]
    assert fixture.get(f"/reviews/{pending_id}").json()["status"] == "approved"
    assert fixture.decision("agent", 980).status_code == 409
    with fixture.factory() as session:
        assert session.scalar(select(func.count()).select_from(Notification)) == before
