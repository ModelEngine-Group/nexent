# D1 BE-UT: skill description over 1000 chars is truncated to 1000 and DB write has no error.

from __future__ import annotations

import logging
from contextlib import contextmanager

import pytest

from database import skill_db


CASE_ID = "UT-BE-AUTO-BCADEBF043C5DE3C"
MAX_LENGTH = skill_db.SKILL_DESCRIPTION_MAX_LENGTH

pytestmark = [
    pytest.mark.stage("D1"),
    pytest.mark.case_id(CASE_ID),
]


class _FakeQuery:
    def __init__(self, store, model):
        self._store = store
        self._model = model

    def filter(self, *args):
        return self

    def all(self):
        return [obj for obj in self._store if isinstance(obj, self._model)]

    def first(self):
        return next((obj for obj in self._store if isinstance(obj, self._model)), None)


class _FakeSession:
    # Minimal in-memory persistence seam for the skill_db write path.
    def __init__(self, store):
        self._store = store
        self._next_skill_id = 1

    def add(self, obj):
        self._store.append(obj)

    def flush(self):
        for obj in self._store:
            if getattr(obj, "skill_id", None) is None:
                obj.skill_id = self._next_skill_id
                self._next_skill_id += 1

    def commit(self):
        pass

    def query(self, model):
        return _FakeQuery(self._store, model)


def _patch_get_db_session(monkeypatch, store):
    @contextmanager
    def fake_get_db_session():
        yield _FakeSession(store)

    monkeypatch.setattr(skill_db, "get_db_session", fake_get_db_session)


def test_skill_description_truncated_to_1000_and_write_ok(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)

    assert skill_db.SKILL_DESCRIPTION_MAX_LENGTH == 1000

    assert skill_db._normalize_skill_description(None) == ""
    assert skill_db._normalize_skill_description("") == ""

    exact = "x" * MAX_LENGTH
    assert skill_db._normalize_skill_description(exact) == exact

    over_by_one = "a" * (MAX_LENGTH + 1)
    assert skill_db._normalize_skill_description(over_by_one) == over_by_one[:MAX_LENGTH]
    assert len(skill_db._normalize_skill_description(over_by_one)) == MAX_LENGTH

    over_long = "b" * 5000
    assert skill_db._normalize_skill_description(over_long) == over_long[:MAX_LENGTH]
    assert len(skill_db._normalize_skill_description(over_long)) == MAX_LENGTH

    store = []
    _patch_get_db_session(monkeypatch, store)
    created = skill_db.create_skill(
        {"name": "skill-truncate", "description": over_long, "content": "content"},
        "tenant-truncate",
    )
    assert created["description"] == over_long[:MAX_LENGTH]
    assert len(created["description"]) == MAX_LENGTH

    upsert_store = []
    _patch_get_db_session(monkeypatch, upsert_store)
    skill_db.upsert_scanned_skills(
        [{"name": "scan-skill", "description": over_long, "content": "content"}],
        "user-truncate",
        "tenant-truncate",
    )
    assert len(upsert_store) == 1
    assert upsert_store[0].skill_description == over_long[:MAX_LENGTH]
    assert len(upsert_store[0].skill_description) == MAX_LENGTH

    assert "truncated" in caplog.text
    lowered = caplog.text.lower()
    for secret in ("api_key", "api key", "token", "password", "secret"):
        assert secret not in lowered
