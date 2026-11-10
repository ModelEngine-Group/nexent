# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real PostgreSQL races, rollback and post-commit notification fault windows."""

from concurrent.futures import ThreadPoolExecutor
import logging
import subprocess
import sys
from threading import Barrier, Event
from unittest.mock import patch

from sqlalchemy import event, func, select

from management.db.models import McpRecord, Notification
from management.db.repository_reviews import REVIEW_MODELS
from management.services.repository import reviews


def reliability_contract(fixture):
    for kind, (model, _, _, status_field, _) in REVIEW_MODELS.items():
        for offset, decisions in enumerate((("approve", "approve"), ("approve", "reject"))):
            identifier = 900 + offset
            with fixture.factory.begin() as session:
                fixture.add(session, kind, identifier, submitted_user_id=fixture.mine)
                before = session.scalar(select(func.count()).select_from(Notification))
            barrier = Barrier(2)
            def decide(value):
                barrier.wait(timeout=10)
                return fixture.decision(kind, identifier, decision=value)
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(decide, decisions))
            assert sorted(response.status_code for response in responses) == [200, 409]
            winner = next(response for response in responses if response.status_code == 200).json()
            with fixture.factory() as session:
                assert getattr(session.get(model, identifier), status_field) == winner["status"]
                assert session.scalar(select(func.count()).select_from(Notification)) == before + 1

        identifier = 950
        with fixture.factory.begin() as session:
            fixture.add(session, kind, identifier, submitted_user_id=fixture.mine)
        started, release = Event(), Event()
        original_lock = reviews.lock_repository_source
        def pause_review(*args):
            started.set()
            assert release.wait(timeout=20)
            return original_lock(*args)
        with patch.object(reviews, "lock_repository_source", side_effect=pause_review), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fixture.decision, kind, identifier)
            try:
                assert started.wait(timeout=10)
                if kind == "mcp":
                    replaced = fixture.client.put(f"/mcp-tools/community/{identifier}", headers=fixture.headers(),
                        json={"description":"Replacement snapshot", "content":"Replacement submission"})
                else:
                    replaced = fixture.client.patch(f"/repository/{kind}/{identifier}/status", headers=fixture.headers(),
                        json={"status":"pending_review", "content":"Replacement submission"})
                assert replaced.status_code == 200, replaced.text
            finally:
                release.set()
            assert future.result(timeout=20).status_code == 409
        current = fixture.get(f"/reviews/{kind}/{identifier}").json()
        assert current["revision"] == 1 and current["status"] == "pending_review"
        assert current["submit_description"] == "Replacement submission" and current["review_comment"] is None

    identifier = 960
    with fixture.factory.begin() as session:
        fixture.add(session, "mcp", identifier, submitted_user_id=fixture.mine)
        before = session.scalar(select(func.count()).select_from(Notification))
    def fail_flush(session, *_):
        if any(isinstance(row, REVIEW_MODELS["mcp"][0]) and row.market_id == identifier for row in session.dirty):
            raise RuntimeError("Controlled source-link failure")
    event.listen(fixture.factory.class_, "after_flush", fail_flush)
    try:
        try:
            fixture.decision("mcp", identifier)
        except RuntimeError as error:
            assert "Controlled source-link failure" in str(error)
        else:
            raise AssertionError("Injected source-link failure was swallowed")
    finally:
        event.remove(fixture.factory.class_, "after_flush", fail_flush)
    with fixture.factory() as session:
        assert session.get(McpRecord, identifier).market_id is None
        record = session.get(REVIEW_MODELS["mcp"][0], identifier)
        assert record.review_status == "pending_review" and record.published_at is None
        assert session.scalar(select(func.count()).select_from(Notification)) == before
    assert fixture.decision("mcp", identifier).status_code == 200

    logs = []
    class Capture(logging.Handler):
        def emit(self, record):
            logs.append(record.getMessage())
    handler = Capture()
    reviews.logger.addHandler(handler)
    try:
        with fixture.factory.begin() as session:
            fixture.add(session, "agent", 970, submitted_user_id=fixture.mine)
        with patch.object(reviews, "create_repository_review_notification", side_effect=RuntimeError("Controlled transport failure")) as delivery:
            # Deliberately discard the successful response, then retry the old revision.
            fixture.decision("agent", 970)
            assert fixture.get("/reviews/agent/970").json()["status"] == "shared"
            assert fixture.decision("agent", 970).status_code == 409
            assert delivery.call_count == 1
        assert any("notification delivery failed" in value for value in logs)
    finally:
        reviews.logger.removeHandler(handler)

    with fixture.factory.begin() as session:
        fixture.add(session, "agent", 980, submitted_user_id=fixture.mine)
        before = session.scalar(select(func.count()).select_from(Notification))
    child = """
import os, sys
from sqlalchemy.orm import sessionmaker
from management.db.client import db_client
from management.services.repository import reviews
from contracts.review import ReviewDecisionRequest
engine = db_client.engine.execution_options(schema_translate_map={'nexent':sys.argv[1]})
db_client.session_maker = sessionmaker(bind=engine)
reviews.create_repository_review_notification = lambda **kwargs: os._exit(37)
reviews.decide_repository_review('agent',980,sys.argv[3],sys.argv[2],'ADMIN',ReviewDecisionRequest(decision='approve',expected_revision=0))
raise SystemExit(99)
"""
    result = subprocess.run([sys.executable, "-c", child, fixture.schema, fixture.tenant, fixture.admin],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 37, result.stderr[-3000:]
    assert fixture.get("/reviews/agent/980").json()["status"] == "shared"
    assert fixture.decision("agent", 980).status_code == 409
    with fixture.factory() as session:
        assert session.scalar(select(func.count()).select_from(Notification)) == before
