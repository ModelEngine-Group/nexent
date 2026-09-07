"""Unit tests for ``database.evaluation_annotation_db``.

Targets
-------
* Schema CRUD: ``list_annotation_schemas`` / ``create_annotation_schema``
  (incl. ``created_by`` backfill) / ``update_annotation_schema`` (None-value
  skip, missing row -> None) / ``count_annotations_for_schema`` /
  ``delete_annotation_schema`` (bool return).
* Annotation CRUD: ``list_annotations_by_evaluation_id`` (grouping by
  case_id), ``list_annotations_by_case_ids`` (empty short-circuit + in_
  filter), ``batch_upsert_annotations`` (update vs insert split, single
  commit), ``get_annotation_values``, ``delete_annotations_by_evaluation_schema``.
* Helpers: ``_schema_to_dict`` / ``_annotation_to_dict`` (None vs str time).

Isolation pattern mirrors ``test_evaluator_db.py``: permanent ``sys.modules``
stubs for the ``database`` package (registered idempotently via
``_register_package``), the module loaded with ``spec_from_file_location``
(skips ``database/__init__.py``), and a queue-driven fake session so every
query in a function returns a dedicated mock chain.
"""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# 1. Path setup + idempotent package registration
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

MODULE_UNDER_TEST = "database.evaluation_annotation_db"


def _register_package(name: str) -> types.ModuleType:
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "__path__"):
        return existing
    pkg = types.ModuleType(name)
    backend_path = _BACKEND_DIR / name
    pkg.__path__ = [str(backend_path)] if backend_path.is_dir() else []
    sys.modules[name] = pkg
    return pkg


# ---------------------------------------------------------------------------
# 2. Sys.modules stub chain (permanent, idempotent)
# ---------------------------------------------------------------------------


class _Col:
    """Stand-in for a SQLAlchemy InstrumentedAttribute on stub ORM classes.

    Only the operators ``evaluation_annotation_db.py`` uses are implemented
    so ``session.query(...).filter(...)`` calls do not crash; the fake
    session ignores filter predicates anyway.
    """

    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return ("eq", self.name, other)

    def __ne__(self, other):
        return ("ne", self.name, other)

    def in_(self, seq):
        return ("in", self.name, list(seq))

    def __repr__(self):  # pragma: no cover - debug aid
        return f"_Col({self.name})"


def _make_orm(cls_name: str, col_names: list[str]) -> type:
    """Stub ORM class: columns default to None on instances, _Col on the class."""

    def _init(self, **kwargs):
        for c in col_names:
            setattr(self, c, None)
        for k, v in kwargs.items():
            setattr(self, k, v)

    attrs = {"__init__": _init, "__repr__": lambda self: f"<{cls_name}>"}
    for c in col_names:
        attrs[c] = _Col(c)
    return type(cls_name, (), attrs)


def _install_stubs():
    """Register placeholder modules for every transitive import of the target."""
    _db_pkg = _register_package("database")

    _client = types.ModuleType("database.client")
    _client.get_db_session = None  # patched per test
    _db_pkg.client = _client
    sys.modules["database.client"] = _client

    _SchemaCls = _make_orm(
        "EvaluationAnnotationSchema",
        [
            "schema_id",
            "tenant_id",
            "name",
            "description",
            "annotation_type",
            "options",
            "created_by",
            "create_time",
            "update_time",
        ],
    )
    _AnnCls = _make_orm(
        "EvaluationAnnotation",
        [
            "annotation_id",
            "tenant_id",
            "case_id",
            "schema_id",
            "value",
            "agent_evaluation_id",
            "created_by",
            "updated_by",
            "create_time",
            "update_time",
        ],
    )
    _CaseCls = _make_orm(
        "AgentEvaluationCase",
        ["agent_evaluation_case_id", "agent_evaluation_id", "tenant_id"],
    )
    db_mod = types.ModuleType("database.db_models")
    db_mod.EvaluationAnnotationSchema = _SchemaCls
    db_mod.EvaluationAnnotation = _AnnCls
    db_mod.AgentEvaluationCase = _CaseCls
    _db_pkg.db_models = db_mod
    sys.modules["database.db_models"] = db_mod
    return _SchemaCls, _AnnCls, _CaseCls


_INSTALLED = _install_stubs()


@pytest.fixture(scope="module")
def ann_mod():
    """Module-scoped fresh import of evaluation_annotation_db with stubs."""
    import importlib.util as _ilu

    for extra in (str(_REPO_ROOT), str(_BACKEND_DIR)):
        if extra not in sys.path:
            sys.path.insert(0, extra)

    if MODULE_UNDER_TEST in sys.modules:
        del sys.modules[MODULE_UNDER_TEST]
    db_pkg = _register_package("database")
    if hasattr(db_pkg, "evaluation_annotation_db"):
        delattr(db_pkg, "evaluation_annotation_db")

    src = _BACKEND_DIR / "database" / "evaluation_annotation_db.py"
    spec = _ilu.spec_from_file_location(MODULE_UNDER_TEST, str(src))
    assert spec is not None and spec.loader is not None, f"cannot locate {src}"
    mod = _ilu.module_from_spec(spec)
    sys.modules[MODULE_UNDER_TEST] = mod
    spec.loader.exec_module(mod)
    db_pkg.evaluation_annotation_db = mod

    SchemaCls, AnnCls, CaseCls = _INSTALLED
    mod.SchemaCls = SchemaCls
    mod.AnnCls = AnnCls
    mod.CaseCls = CaseCls

    # tuple_ is imported from real sqlalchemy at module load; replace it with
    # a lightweight fake so batch_upsert's tuple_(col, col).in_(pairs) call
    # does not need real Column objects.
    class _FakeTupleExpr:
        def __init__(self, *cols):
            self.cols = list(cols)

        def in_(self, seq):
            return ("tuple-in", self.cols, list(seq))

    mod.tuple_ = _FakeTupleExpr
    yield mod


# ---------------------------------------------------------------------------
# 3. Fake session: queue-driven query chains
# ---------------------------------------------------------------------------


_UNSET = object()


def _chain(*, all_rows=_UNSET, first=_UNSET, count=_UNSET, delete=_UNSET) -> MagicMock:
    q = MagicMock(name="query-chain")
    q.filter.return_value = q
    q.order_by.return_value = q
    q.join.return_value = q
    if all_rows is not _UNSET:
        q.all.return_value = all_rows
    if first is not _UNSET:
        q.first.return_value = first
    if count is not _UNSET:
        q.count.return_value = count
    if delete is not _UNSET:
        q.delete.return_value = delete
    return q


class _FakeSession:
    """Session whose ``query`` pops chains in call order."""

    def __init__(self, chains: list[MagicMock] | None = None):
        self.chains = list(chains or [])
        self.added: list[Any] = []
        self.commits = 0
        self.refreshed: list[Any] = []

    def query(self, *args, **kwargs):
        if not self.chains:
            return MagicMock(name="query")
        return self.chains.pop(0)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        self.refreshed.append(obj)


@contextmanager
def _patch_session(mod, sess):
    @contextmanager
    def _cm():
        yield sess

    old = getattr(mod, "get_db_session", None)
    mod.get_db_session = _cm
    try:
        yield sess
    finally:
        if old is not None:
            mod.get_db_session = old


# ---------------------------------------------------------------------------
# 4. Schema CRUD tests
# ---------------------------------------------------------------------------


class TestSchemaCrud:
    def test_list_schemas_returns_dicts(self, ann_mod):
        rows = [
            ann_mod.SchemaCls(
                schema_id=1, tenant_id="t1", name="a", description="d",
                annotation_type="pass_fail", options=None, created_by="u1",
            ),
            ann_mod.SchemaCls(
                schema_id=2, tenant_id="t1", name="b", description="",
                annotation_type="score", options=[{"label": "x"}], created_by="u1",
                create_time="2026-01-01", update_time="2026-01-02",
            ),
        ]
        sess = _FakeSession([_chain(all_rows=rows)])
        with _patch_session(ann_mod, sess):
            out = ann_mod.list_annotation_schemas("t1")
        assert len(out) == 2
        assert out[0]["schema_id"] == 1
        assert out[0]["create_time"] is None
        assert out[1]["create_time"] == "2026-01-01"
        assert out[1]["update_time"] == "2026-01-02"

    def test_list_schemas_empty(self, ann_mod):
        sess = _FakeSession([_chain(all_rows=[])])
        with _patch_session(ann_mod, sess):
            assert ann_mod.list_annotation_schemas("t1") == []

    def test_create_schema_backfills_created_by(self, ann_mod):
        sess = _FakeSession()
        with _patch_session(ann_mod, sess):
            out = ann_mod.create_annotation_schema(
                "t1", "u1", "name", "desc", "pass_fail",
                options=[{"label": "ok"}],
            )
        assert len(sess.added) == 1
        row = sess.added[0]
        assert row.created_by == "u1"
        assert row.tenant_id == "t1"
        assert row.name == "name"
        assert row.options == [{"label": "ok"}]
        assert sess.commits == 1
        assert sess.refreshed == [row]
        assert out["name"] == "name"
        assert out["create_time"] is None

    def test_update_schema_updates_non_none_fields(self, ann_mod):
        existing = ann_mod.SchemaCls(
            schema_id=5, tenant_id="t1", name="old", description="old d",
            annotation_type="pass_fail", options=None, created_by="u1",
        )
        sess = _FakeSession([_chain(first=existing)])
        with _patch_session(ann_mod, sess):
            out = ann_mod.update_annotation_schema(
                5, "t1", name="new", description="new d", options=[1],
                annotation_type="IGNORED",
            )
        assert existing.name == "new"
        assert existing.description == "new d"
        assert existing.options == [1]
        # annotation_type is not in the updatable key set
        assert existing.annotation_type == "pass_fail"
        assert sess.commits == 1
        assert sess.refreshed == [existing]
        assert out["name"] == "new"

    def test_update_schema_skips_none_and_absent_keys(self, ann_mod):
        existing = ann_mod.SchemaCls(
            schema_id=5, tenant_id="t1", name="keep", description="keep d",
            annotation_type="pass_fail", options=None,
        )
        sess = _FakeSession([_chain(first=existing)])
        with _patch_session(ann_mod, sess):
            ann_mod.update_annotation_schema(
                5, "t1", name=None, description=None, options=None, other=1
            )
        assert existing.name == "keep"
        assert existing.description == "keep d"
        assert existing.options is None
        assert not hasattr(existing, "other")

    def test_update_schema_missing_returns_none(self, ann_mod):
        sess = _FakeSession([_chain(first=None)])
        with _patch_session(ann_mod, sess):
            assert ann_mod.update_annotation_schema(999, "t1", name="x") is None
        assert sess.commits == 0

    def test_count_annotations_for_schema(self, ann_mod):
        sess = _FakeSession([_chain(count=3)])
        with _patch_session(ann_mod, sess):
            assert ann_mod.count_annotations_for_schema(1, "t1") == 3

    @pytest.mark.parametrize("deleted,expected", [(2, True), (0, False)])
    def test_delete_schema_returns_bool(self, ann_mod, deleted, expected):
        sess = _FakeSession([_chain(delete=deleted)])
        with _patch_session(ann_mod, sess):
            assert ann_mod.delete_annotation_schema(1, "t1") is expected
        assert sess.commits == 1


# ---------------------------------------------------------------------------
# 5. Annotation CRUD tests
# ---------------------------------------------------------------------------


class TestAnnotationCrud:
    def test_list_by_evaluation_id_groups_by_case(self, ann_mod):
        rows = [
            ann_mod.AnnCls(annotation_id=1, tenant_id="t1", case_id=10,
                           schema_id=1, value="pass"),
            ann_mod.AnnCls(annotation_id=2, tenant_id="t1", case_id=10,
                           schema_id=1, value="fail"),
            ann_mod.AnnCls(annotation_id=3, tenant_id="t1", case_id=11,
                           schema_id=2, value="3", create_time="2026-01-01"),
        ]
        sess = _FakeSession([_chain(all_rows=rows)])
        with _patch_session(ann_mod, sess):
            out = ann_mod.list_annotations_by_evaluation_id("t1", 100)
        assert set(out) == {10, 11}
        assert len(out[10]) == 2
        assert out[11][0]["value"] == "3"
        assert out[11][0]["create_time"] == "2026-01-01"

    def test_list_by_case_ids_empty_short_circuit(self, ann_mod):
        sess = _FakeSession()
        with _patch_session(ann_mod, sess):
            assert ann_mod.list_annotations_by_case_ids("t1", []) == {}
        assert sess.chains == []  # no query issued

    def test_list_by_case_ids_groups(self, ann_mod):
        rows = [
            ann_mod.AnnCls(annotation_id=1, tenant_id="t1", case_id=1,
                           schema_id=1, value="a"),
            ann_mod.AnnCls(annotation_id=2, tenant_id="t1", case_id=2,
                           schema_id=1, value="b"),
        ]
        sess = _FakeSession([_chain(all_rows=rows)])
        with _patch_session(ann_mod, sess):
            out = ann_mod.list_annotations_by_case_ids("t1", [1, 2])
        assert set(out) == {1, 2}
        assert out[1][0]["annotation_id"] == 1
        assert out[2][0]["value"] == "b"

    def test_batch_upsert_empty_noop(self, ann_mod):
        sess = _FakeSession()
        with _patch_session(ann_mod, sess):
            ann_mod.batch_upsert_annotations("t1", "u1", [])
        assert sess.commits == 0
        assert sess.added == []

    def test_batch_upsert_update_and_insert(self, ann_mod):
        case_rows = [
            MagicMock(agent_evaluation_case_id=1, agent_evaluation_id=100),
            MagicMock(agent_evaluation_case_id=2, agent_evaluation_id=100),
        ]
        existing = ann_mod.AnnCls(annotation_id=10, tenant_id="t1", case_id=1,
                                  schema_id=1, value="old", created_by="u0")
        sess = _FakeSession([
            _chain(all_rows=case_rows),
            _chain(all_rows=[existing]),
        ])
        anns = [
            {"case_id": 1, "schema_id": 1, "value": "new"},
            {"case_id": 2, "schema_id": 1, "value": "fresh"},
        ]
        with _patch_session(ann_mod, sess):
            ann_mod.batch_upsert_annotations("t1", "u1", anns)

        # update branch: existing row mutated in place
        assert existing.value == "new"
        assert existing.updated_by == "u1"
        # insert branch: exactly one new row added
        assert len(sess.added) == 1
        added = sess.added[0]
        assert added.case_id == 2
        assert added.schema_id == 1
        assert added.value == "fresh"
        assert added.agent_evaluation_id == 100
        assert added.created_by == "u1"
        assert added.tenant_id == "t1"
        assert sess.commits == 1

    def test_get_annotation_values(self, ann_mod):
        rows = [MagicMock(value="pass"), MagicMock(value="fail")]
        sess = _FakeSession([_chain(all_rows=rows)])
        with _patch_session(ann_mod, sess):
            out = ann_mod.get_annotation_values("t1", 100, 1)
        assert out == ["pass", "fail"]

    def test_delete_annotations_by_evaluation_schema(self, ann_mod):
        sess = _FakeSession([_chain(delete=4)])
        with _patch_session(ann_mod, sess):
            assert ann_mod.delete_annotations_by_evaluation_schema("t1", 100, 1) == 4
        assert sess.commits == 1


# ---------------------------------------------------------------------------
# 6. Helper tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_annotation_to_dict_time_fields(self, ann_mod):
        row = ann_mod.AnnCls(annotation_id=1, tenant_id="t1", case_id=1,
                             schema_id=1, value="v")
        out = ann_mod._annotation_to_dict(row)
        assert out["annotation_id"] == 1
        assert out["case_id"] == 1
        assert out["value"] == "v"
        assert out["create_time"] is None
        assert out["update_time"] is None
