"""Unit tests for ``evaluator_db`` versioning / CLONE / in-use guards.

Targets
-------
* ``update_evaluator`` – DRAFT in-place mutation vs PUBLISHED→CLONE to a new
  DRAFT row with ``version_no+1``, including ``_check_evaluator_in_use``
  block-before-mutate semantics.
* ``_check_evaluator_in_use`` – membership scan over
  ``agent_evaluation_t.evaluator_config.evaluator_ids`` JSONB, respecting
  the ``tenant_id`` boundary filter.
* ``restore_evaluator_version`` – safety checks (missing target → ``None``,
  current-version in-use → raise, valid target → bulk reset of
  ``is_current`` + single-row flip to ``True``).
* ``delete_evaluator_version`` – guard order (missing→False, is_current→raise,
  in-use→raise, valid→delete + return ``True``).
* ``publish_evaluator`` – first-publish sets ``version_group_id``.

All tests drive the logic by injecting a MagicMock ``session`` through the
``database.client.get_db_session`` context-manager helper (a pattern borrowed
from the existing ``test_agent_evaluation_service`` suite).  A dedicated
``_SessionHarness`` helper class wires the common ``session.query(...)`` chain
to return configurable mock rows so each branch path can be exercised with
minimal boilerplate.
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
# 1. Path setup + idempotent package registration (mirrors
#    test_agent_evaluation_service.py pattern)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _register_package(name: str) -> types.ModuleType:
    """Register ``name`` as a real package on ``sys.modules``.

    Real ``__path__`` (pointing to the matching backend dir when one applies)
    is used so subsequent ``from X.Y import Z`` resolution can locate
    submodules; this prevents sibling tests from seeing a stubbed package
    with no resolvable submodules.

    If ``sys.modules[name]`` already exposes ``__path__`` (e.g. a stub
    created by a sibling test file) we reuse it so we don't fork the
    package identity mid-session — module-level execution of one test
    file would otherwise orphan the other file's package object, and
    ``from package import X`` would then short-circuit through a stale
    cache that has no entry in ``sys.modules``.
    """
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "__path__"):
        return existing
    pkg = types.ModuleType(name)
    backend_path = _BACKEND_DIR / name
    if backend_path.is_dir():
        pkg.__path__ = [str(backend_path)]
    else:
        pkg.__path__ = []
    sys.modules[name] = pkg
    return pkg


# ---------------------------------------------------------------------------
# 2. Sys.modules stub chain – permanent top-level install (no monkeypatch,
#    no undo)
# ---------------------------------------------------------------------------

MODULE_UNDER_TEST = "database.evaluator_db"


def _install_stubs():
    """Register placeholder modules for every transitive import of evaluator_db.

    Runs once at module-collection time and is *never* undone – sibling tests
    share the same stub objects via ``_register_package`` idempotency.

    Returns a 4-tuple of the ORM stubs / exception class / status enum so the
    ``evaluator_mod`` fixture can pin them onto the freshly loaded module.
    """

    def mk_mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    # ---- consts / exceptions ---------------------------------------------
    _consts_pkg = _register_package("consts")
    _Err = type(
        "Err",
        (),
        {
            "COMMON_VALIDATION_ERROR": "COMMON_VALIDATION_ERROR",
            "AGENT_EVALUATION_EVALUATOR_IN_USE": "AGENT_EVALUATION_EVALUATOR_IN_USE",
        },
    )
    _ec_mod = mk_mod("consts.error_code", ErrorCode=_Err)
    _consts_pkg.error_code = _ec_mod
    _ERS = type("ERS", (), {"PENDING": "PENDING", "RUNNING": "RUNNING"})
    _es_mod = mk_mod("consts.evaluation_status", EvalRunStatus=_ERS)
    _consts_pkg.evaluation_status = _es_mod

    class _AppException(Exception):
        def __init__(self, code: Any, msg: str = "", extra=None):
            super().__init__(msg)
            self.code = code
            self.message = msg
            self.extra = extra

    _ex_mod = mk_mod("consts.exceptions", AppException=_AppException)
    _consts_pkg.exceptions = _ex_mod

    # database.client.get_db_session – wired lazily by the harness per test.
    _db_pkg = _register_package("database")
    _dc_mod = mk_mod("database.client")
    _dc_mod.get_db_session = None  # patched per test
    _db_pkg.client = _dc_mod

    # db_models (ORM classes referenced by session.query(ClassName))
    _EvalCls = type("Evaluator", (), {})
    _AgentEvalCls = type("AgentEvaluation", (), {})
    db_mod = mk_mod(
        "database.db_models",
        Evaluator=_EvalCls,
        AgentEvaluation=_AgentEvalCls,
    )
    _db_pkg.db_models = db_mod
    return db_mod.Evaluator, db_mod.AgentEvaluation, _AppException, _ERS


_INSTALLED = _install_stubs()


@pytest.fixture(scope="module")
def evaluator_mod():
    """Module-scoped fresh import of evaluator_db with stubs installed.

    The module-under-test is loaded by ``importlib.util.spec_from_file_location``
    because: (1) the ``database`` package on ``sys.path`` has a real
    ``__init__.py`` that pulls in SQLAlchemy-heavy imports; (2) we need
    ``database.client`` and ``database.db_models`` to resolve to our stubs
    instead of the real implementations.  Using ``spec_from_file_location``
    lets us skip the ``database`` package-import step and still satisfy the
    ``from database.client import get_db_session`` line in the module.

    Stubs are pre-installed at module-collection time (see ``_install_stubs``
    above) and captured in ``_INSTALLED`` — no ``monkeypatch`` undo is needed
    because the stubs are intentionally permanent (idempotent registration via
    ``_register_package`` keeps them consistent across sibling test files).
    """
    import importlib.util as _ilu

    repo_root = _REPO_ROOT
    backend_root = _BACKEND_DIR
    for extra in (str(repo_root), str(backend_root)):
        if extra not in sys.path:
            sys.path.insert(0, extra)

    Evaluator, AgentEvaluation, AppExc, ERS = _INSTALLED

    if MODULE_UNDER_TEST in sys.modules:
        del sys.modules[MODULE_UNDER_TEST]
    db_pkg = _register_package("database")
    if hasattr(db_pkg, "evaluator_db"):
        try:
            delattr(db_pkg, "evaluator_db")
        except AttributeError:
            pass

    _src = backend_root / "database" / "evaluator_db.py"
    _spec = _ilu.spec_from_file_location(MODULE_UNDER_TEST, str(_src))
    assert _spec is not None and _spec.loader is not None, (
        f"cannot locate evaluator_db.py at {_src}"
    )
    mod = _ilu.module_from_spec(_spec)
    sys.modules[MODULE_UNDER_TEST] = mod
    _spec.loader.exec_module(mod)
    db_pkg.evaluator_db = mod

    # Pin useful references on the module for tests
    mod.EvaluatorCls = Evaluator
    mod.AgentEvalCls = AgentEvaluation
    mod.AppException = AppExc
    mod.EvalRunStatus = ERS
    yield mod


# ---------------------------------------------------------------------------
# 2. Session harness – builds mock session.query(...).filter(...).all/first chains
# ---------------------------------------------------------------------------


class _Col:
    """Stand-in for a SQLAlchemy InstrumentedAttribute on stub ORM classes.

    Only the operations that evaluator_db.py actually uses are implemented:
    ``a == b``, ``a.in_(list)`` produce string-encoded "predicate tokens"
    that ``_Query`` can decode without needing a full SQLAlchemy import.
    ``.desc()`` / ``.asc()`` are no-ops returning self (for ORDER BY).
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

    def is_(self, other):
        return ("is", self.name, other)

    def __le__(self, other):
        return ("le", self.name, other)

    def __ge__(self, other):
        return ("ge", self.name, other)

    def desc(self):
        return ("order", self.name, "desc", self)

    def asc(self):
        return ("order", self.name, "asc", self)

    def __repr__(self):
        return f"_Col({self.name})"


def _build_stub_orm_classes():
    """Produce stub ORM classes with Column attributes so .filter() calls don't crash.

    The class also accepts keyword arguments in ``__init__`` (just like a
    real SQLAlchemy ORM class) so that ``Evaluator(tenant_id=..., name=...)``
    in the CLONE branch of ``update_evaluator`` does not raise TypeError.
    """
    eval_cols = [
        "evaluator_id",
        "tenant_id",
        "source",
        "name",
        "status",
        "version_no",
        "version_group_id",
        "is_current",
        "evaluator_type",
        "prompt",
        "code",
        "description",
        "name_en",
        "description_en",
        "prompt_en",
        "score_range_min",
        "score_range_max",
        "pass_threshold",
        "input_fields",
        "model_id",
        "created_by",
        "create_time",
        "update_time",
    ]
    ae_cols = [
        "agent_evaluation_id",
        "tenant_id",
        "status",
        "evaluator_config",
        "agent_name",
        "agent_id",
    ]

    class _ORMBase:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        def __repr__(self):  # pragma: no cover - debug aid
            return (
                f"<ORM {type(self).__name__} "
                + ", ".join(
                    f"{k}={getattr(self, k)}" for k in list(vars(self).keys())[:6]
                )
                + ">"
            )

    def _mk_class(cls_name, col_names):
        def _init(self, **kwargs):
            # Initialise every declared column to None first so _to_dict()'s
            # `row.X if row.X else None` accesses never raise AttributeError
            # for columns that were not explicitly set by the caller.
            for c in col_names:
                setattr(self, c, None)
            for k, v in kwargs.items():
                setattr(self, k, v)

        def _repr(self):  # pragma: no cover - debug aid
            return (
                f"<ORM {type(self).__name__} "
                + ", ".join(
                    f"{k}={getattr(self, k)}" for k in list(vars(self).keys())[:6]
                )
                + ">"
            )

        attrs = {"__init__": _init, "__repr__": _repr}
        for c in col_names:
            attrs.setdefault(c, _Col(c))
        return type(cls_name, (_ORMBase,), attrs)

    return _mk_class("Evaluator", eval_cols), _mk_class("AgentEvaluation", ae_cols)


class _SessionHarness:
    """Helper that builds a mock SQLAlchemy session + query chain with pluggable rows.

    Usage::

        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(evaluator_id=7, tenant_id="t1", status="DRAFT", ...)
        h.add_active_run(agent_evaluation_id=100, tenant_id="t1", evaluator_ids=[7, 9])
        with h.patch_session():
            evaluator_mod.update_evaluator(7, "t1", name="new name")
        # verify mutations via h.evaluator_rows / h.deleted_ids / h.added_rows
    """

    def __init__(self, evaluator_mod):
        self.evaluator_mod = evaluator_mod
        # Install stub ORM classes onto the module so they are picked up
        # by the lazy `from database.db_models import X` inside session cm.
        self.EvaluatorCls, self.AgentEvalCls = _build_stub_orm_classes()
        try:
            import database.db_models as _dm

            _dm.Evaluator = self.EvaluatorCls
            _dm.AgentEvaluation = self.AgentEvalCls
        except Exception:
            pass
        self.evaluator_rows: dict[int, Any] = {}
        self.agent_eval_rows: dict[int, Any] = {}
        self.added_rows: list[Any] = []
        self.deleted_ids: list[int] = []
        self.update_args: list[
            tuple
        ] = []  # (orm_class, update_dict, count_of_rows_updated)
        self.flushed = False
        self.commits = 0
        self.refreshed_rows: list[Any] = []

    # ---- Row builders ----------------------------------------------------

    def add_evaluator_row(
        self,
        evaluator_id: int,
        tenant_id: str = "t1",
        status: str = "DRAFT",
        version_no: int = 1,
        version_group_id=None,
        is_current: bool = True,
        source: str = "custom",
        evaluator_type: str = "code",
        name: str = "ev",
        description: str = "",
        name_en=None,
        description_en=None,
        prompt=None,
        prompt_en=None,
        code=None,
        score_range_min: float = 0.0,
        score_range_max: float = 1.0,
        pass_threshold: float = 0.5,
        input_fields=None,
        model_id=None,
        created_by="u1",
        create_time=None,
    ) -> Any:
        attrs = dict(
            evaluator_id=evaluator_id,
            tenant_id=tenant_id,
            status=status,
            version_no=version_no,
            version_group_id=version_group_id,
            is_current=is_current,
            source=source,
            evaluator_type=evaluator_type,
            name=name,
            description=description,
            name_en=name_en,
            description_en=description_en,
            prompt=prompt,
            prompt_en=prompt_en,
            code=code,
            score_range_min=score_range_min,
            score_range_max=score_range_max,
            pass_threshold=pass_threshold,
            input_fields=input_fields,
            model_id=model_id,
            created_by=created_by,
            create_time=create_time,
            update_time=None,
        )
        row = self._make_mock_obj(**attrs)
        self.evaluator_rows[evaluator_id] = row
        return row

    def add_active_run(
        self,
        agent_evaluation_id: int,
        tenant_id: str = "t1",
        status: str = "RUNNING",
        evaluator_ids: list[int] | None = None,
        agent_name: str | None = None,
    ) -> Any:
        attrs = dict(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            status=status,
            evaluator_config={"evaluator_ids": evaluator_ids or []},
            agent_name=agent_name,
        )
        row = self._make_mock_obj(**attrs)
        self.agent_eval_rows[agent_evaluation_id] = row
        return row

    @staticmethod
    def _make_mock_obj(**attrs) -> Any:
        class _Row:
            pass

        r = _Row()
        for k, v in attrs.items():
            setattr(r, k, v)
        return r

    # ---- Build the session + query chain -------------------------------

    def build_session(self) -> MagicMock:
        harness = self

        class _Query:
            """Per-ORM-class query chain: .filter/.order_by collect, .first/.all/.delete/.update dispatch."""

            def __init__(self, model):
                self.model = model
                self._filters: list[
                    tuple
                ] = []  # list of (op, col_name, value) predicate tokens

            # ---- Query builder methods ---------------------------------------

            def filter(self, *args, **kwargs):
                for a in args:
                    if (
                        isinstance(a, tuple)
                        and len(a) >= 3
                        and a[0] in {"eq", "ne", "in", "is", "le", "ge", "order"}
                    ):
                        self._filters.append(a)
                    elif isinstance(a, _Col):
                        # Bare column reference passed to filter() – SQLAlchemy
                        # interprets this as a truthy predicate (equivalent to
                        # `col == True`).  This is how `Evaluator.is_current`
                        # is used in `restore_evaluator_version`.
                        self._filters.append(("eq", a.name, True))
                    # else: ignore (unrecognised SQLAlchemy token – shouldn't happen)
                for k, v in kwargs.items():
                    self._filters.append(("eq", k, v))
                return self

            def filter_by(self, **kw):
                for k, v in kw.items():
                    self._filters.append(("eq", k, v))
                return self

            def order_by(self, *args, **kwargs):
                for a in args:
                    if isinstance(a, tuple) and a[0] == "order":
                        self._filters.append(a)
                    elif isinstance(a, _Col):
                        self._filters.append(("order", a.name, "asc", a))
                return self

            # ---- Terminal methods -------------------------------------------

            def first(self):
                rows = self._select()
                return rows[0] if rows else None

            def all(self):
                return self._select()

            def delete(self, synchronize_session=None):
                rows = self._select()
                for r in rows:
                    eid = getattr(r, "evaluator_id", None)
                    if eid is not None and eid in harness.evaluator_rows:
                        del harness.evaluator_rows[eid]
                        harness.deleted_ids.append(eid)
                return len(rows)

            def update(self, values, synchronize_session=None):
                rows = self._select()
                for r in rows:
                    for k, v in values.items():
                        setattr(r, k, v)
                harness.update_args.append(
                    (
                        getattr(self.model, "__name__", str(self.model)),
                        dict(values),
                        len(rows),
                    )
                )
                return len(rows)

            # ---- Selection engine -------------------------------------------

            def _select(self):
                model_name = getattr(self.model, "__name__", str(self.model))
                if model_name == "Evaluator":
                    pool = list(harness.evaluator_rows.values())
                elif model_name == "AgentEvaluation":
                    pool = list(harness.agent_eval_rows.values())
                else:
                    pool = []
                return [r for r in pool if self._row_passes(r)]

            def _row_passes(self, row):
                """Walk predicate tokens and match each against the row object."""
                for tok in self._filters:
                    op, col = tok[0], tok[1]
                    val = tok[2]
                    if op == "order":
                        # ORDER BY is never a filter predicate.
                        continue
                    row_val = getattr(row, col, object())
                    if op == "eq":
                        if row_val != val:
                            return False
                    elif op == "ne":
                        if row_val == val:
                            return False
                    elif op == "in":
                        # col .in_([list]) → row value must be in the list
                        if row_val not in val:
                            return False
                    elif op == "is":
                        if (
                            bool(row_val) != bool(val)
                            if isinstance(val, bool)
                            else (row_val is not val)
                        ):
                            # SQLAlchemy .is_(True)/.is_(False) → treat as == for booleans
                            if isinstance(val, bool):
                                if bool(row_val) != val:
                                    return False
                            elif row_val is not val:
                                return False
                    elif op in {"le", "ge"}:
                        try:
                            ok = (row_val <= val) if op == "le" else (row_val >= val)
                            if not ok:
                                return False
                        except TypeError:
                            # incomparable types – treat as failing the filter
                            return False
                return True

        sess = MagicMock(name="session")
        sess.query = _Query

        def _add(obj):
            harness.added_rows.append(obj)
            if not hasattr(obj, "evaluator_id") or obj.evaluator_id is None:
                next_id = (
                    max(harness.evaluator_rows.keys())
                    if harness.evaluator_rows
                    else 1000
                ) + 1
                try:
                    obj.evaluator_id = next_id
                except Exception:
                    pass
            if hasattr(obj, "evaluator_id") and isinstance(obj.evaluator_id, int):
                harness.evaluator_rows[obj.evaluator_id] = obj

        sess.add = _add
        sess.flush = lambda: setattr(harness, "flushed", True)
        sess.refresh = lambda obj: harness.refreshed_rows.append(obj)
        sess.commit = lambda: setattr(harness, "commits", harness.commits + 1)

        def _delete(obj):
            eid = getattr(obj, "evaluator_id", None)
            if eid is not None and eid in harness.evaluator_rows:
                del harness.evaluator_rows[eid]
                harness.deleted_ids.append(eid)

        sess.delete = _delete
        return sess

    @contextmanager
    def patch_session(self):
        """Patch ``evaluator_mod.get_db_session`` to yield our harness session.

        The patch targets the import-time binding inside the module under test
        rather than ``database.client`` because Python's ``from X import Y``
        statement copies the reference at import time, so a later assignment
        to ``database.client.get_db_session`` would be invisible to the
        already-loaded module.
        """
        sess = self.build_session()

        @contextmanager
        def _fake_cm():
            yield sess

        target = self.evaluator_mod
        old = getattr(target, "get_db_session", None)
        target.get_db_session = _fake_cm
        # Also keep database.client patched for any nested code path
        try:
            import database.client as _client

            _client_old = getattr(_client, "get_db_session", None)
            _client.get_db_session = _fake_cm
        except Exception:
            _client_old = None
        try:
            yield sess
        finally:
            if old is not None:
                target.get_db_session = old
            try:
                import database.client as _client2

                if _client_old is not None:
                    _client2.get_db_session = _client_old
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 3. update_evaluator tests
# ---------------------------------------------------------------------------


class TestUpdateEvaluator:
    def test_draft_in_place_passes(self, evaluator_mod):
        """DRAFT row → update fields in place (no clone), session.commit is called."""
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(
            evaluator_id=1,
            tenant_id="t1",
            status="DRAFT",
            version_no=1,
            version_group_id=None,
            is_current=True,
            name="OldName",
            description="old desc",
            pass_threshold=0.5,
        )
        with h.patch_session():
            result = evaluator_mod.update_evaluator(
                1, "t1", name="NewName", code="x = 1"
            )

        assert result is not None
        assert result["name"] == "NewName"
        assert result["code"] == "x = 1"
        # Draft: version_no unchanged
        assert result["version_no"] == 1
        # Draft: no new rows were added (no clone)
        assert len(h.added_rows) == 0
        assert h.commits >= 1

    def test_published_clones_to_new_draft(self, evaluator_mod):
        """PUBLISHED row → clone with version_no+1; old row's is_current flips False."""
        h = _SessionHarness(evaluator_mod)
        old_row = h.add_evaluator_row(
            evaluator_id=7,
            tenant_id="t1",
            status="PUBLISHED",
            version_no=3,
            version_group_id=7,
            is_current=True,
            name="Stable",
            prompt="Original prompt",
            prompt_en="en",
            pass_threshold=0.8,
            model_id=42,
        )
        with h.patch_session():
            result = evaluator_mod.update_evaluator(
                7, "t1", pass_threshold=0.9, description="new desc"
            )

        # Exactly one row was added (the clone)
        assert len(h.added_rows) == 1
        cloned = h.added_rows[0]
        # Version incremented
        assert cloned.version_no == 4
        # Group preserved
        assert cloned.version_group_id == 7
        # Status became DRAFT
        assert cloned.status == "DRAFT"
        assert cloned.is_current is True
        # model_id copied from the published row
        assert cloned.model_id == 42
        # Updatable fields applied
        assert cloned.pass_threshold == 0.9
        assert cloned.description == "new desc"
        # Old row's is_current flipped to False
        assert old_row.is_current is False
        # Return value is the new cloned dict
        assert result["evaluator_id"] == cloned.evaluator_id
        assert result["version_no"] == 4
        assert result["status"] == "DRAFT"
        # flush + refresh was called on the new object (CLONE branch requirement)
        assert h.flushed is True
        assert cloned in h.refreshed_rows

    def test_published_clone_model_id_carry_regression(self, evaluator_mod):
        """Regression test – clone must carry model_id for LLM-type evaluators."""
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(
            evaluator_id=9,
            tenant_id="t1",
            status="PUBLISHED",
            version_no=1,
            version_group_id=9,
            is_current=True,
            name="llm-judge",
            evaluator_type="llm",
            model_id=99,
            prompt="P",
        )
        with h.patch_session():
            evaluator_mod.update_evaluator(9, "t1", name="Renamed LLM")

        cloned = h.added_rows[0]
        assert cloned.model_id == 99  # the regression check
        assert cloned.name == "Renamed LLM"

    def test_in_use_blocks_update(self, evaluator_mod):
        """Active RUNNING run referencing the evaluator blocks mutation."""
        AppExc = evaluator_mod.AppException
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(evaluator_id=3, tenant_id="t1", status="DRAFT")
        h.add_active_run(
            agent_evaluation_id=1001,
            tenant_id="t1",
            status="RUNNING",
            evaluator_ids=[3, 99],
        )

        with h.patch_session(), pytest.raises(AppExc) as exc_info:
            evaluator_mod.update_evaluator(3, "t1", description="mutate")

        assert exc_info.value.code == "AGENT_EVALUATION_EVALUATOR_IN_USE"
        assert "1 active evaluation run" in exc_info.value.message
        # No mutation happened
        assert h.commits == 0
        assert len(h.added_rows) == 0

    def test_tenant_boundary_in_use_check(self, evaluator_mod):
        """Tenant T2's update is NOT blocked by Tenant T1's active run."""
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(
            evaluator_id=4, tenant_id="t2", status="DRAFT", version_no=1
        )
        # Active run owned by tenant "t1" (NOT "t2")
        h.add_active_run(
            agent_evaluation_id=200, tenant_id="t1", status="RUNNING", evaluator_ids=[4]
        )

        with h.patch_session():
            result = evaluator_mod.update_evaluator(4, "t2", description="t2-only edit")

        # Should succeed (not blocked by t1's run)
        assert result is not None
        assert h.commits >= 1

    def test_update_missing_returns_none(self, evaluator_mod):
        """Unknown evaluator_id / non-matching tenant → None."""
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(evaluator_id=5, tenant_id="t1", status="DRAFT")
        with h.patch_session():
            # Wrong tenant (cross-tenant lookup fails because of == tenant filter)
            result = evaluator_mod.update_evaluator(5, "WRONG_TENANT", description="x")
            assert result is None

            # Unknown id
            result2 = evaluator_mod.update_evaluator(9999, "t1", description="x")
            assert result2 is None

    def test_draft_updatable_fields_ignore_none(self, evaluator_mod):
        """``None`` kwargs are skipped so callers don't accidentally wipe fields."""
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(
            evaluator_id=6,
            tenant_id="t1",
            status="DRAFT",
            version_no=1,
            name="Keep",
            prompt="KeepPrompt",
        )
        with h.patch_session():
            evaluator_mod.update_evaluator(
                6, "t1", code=None, prompt=None, description="only-desc"
            )
        # The initial Keep values must survive (None kwargs skipped)
        updated = h.evaluator_rows[6]
        assert updated.name == "Keep"
        assert updated.prompt == "KeepPrompt"
        assert updated.description == "only-desc"


# ---------------------------------------------------------------------------
# 4. _check_evaluator_in_use tests
# ---------------------------------------------------------------------------


class TestCheckEvaluatorInUse:
    def test_no_active_runs_returns_empty(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        with h.patch_session() as sess:
            out = evaluator_mod._check_evaluator_in_use(1, sess, "t1")
        assert out == []

    def test_membership_check_only_matches_evaluator_id_in_list(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        h.add_active_run(1, "t1", "RUNNING", evaluator_ids=[1, 2, 3])
        h.add_active_run(2, "t1", "PENDING", evaluator_ids=[9, 10])
        with h.patch_session() as sess:
            out = evaluator_mod._check_evaluator_in_use(2, sess, "t1")
        assert len(out) == 1
        assert out[0]["agent_evaluation_id"] == 1

    def test_tenant_filter_is_applied(self, evaluator_mod):
        """Without a tenant-id filter the scan would return T1's runs for T2."""
        h = _SessionHarness(evaluator_mod)
        h.add_active_run(1, "t1", "RUNNING", evaluator_ids=[7])
        h.add_active_run(2, "t2", "RUNNING", evaluator_ids=[7])
        with h.patch_session() as sess:
            out = evaluator_mod._check_evaluator_in_use(7, sess, "t2")
        assert len(out) == 1
        assert out[0]["agent_evaluation_id"] == 2

    def test_malformed_evaluator_config_is_handled(self, evaluator_mod):
        """Non-dict / missing-evaluator_ids config values degrade gracefully."""
        h = _SessionHarness(evaluator_mod)
        bad_config_row = h.add_active_run(3, "t1", "RUNNING")
        # Override with a non-dict (string-garbage) config
        bad_config_row.evaluator_config = "not-a-dict"
        h.add_active_run(4, "t1", "RUNNING", evaluator_ids=[7])
        with h.patch_session() as sess:
            out = evaluator_mod._check_evaluator_in_use(7, sess, "t1")
        # The malformed row must NOT raise; only id 4 matched.
        assert len(out) == 1
        assert out[0]["agent_evaluation_id"] == 4


# ---------------------------------------------------------------------------
# 5. restore_evaluator_version tests
# ---------------------------------------------------------------------------


class TestRestoreEvaluatorVersion:
    def test_missing_target_returns_none(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        with h.patch_session():
            assert evaluator_mod.restore_evaluator_version(9999, "t1") is None

    def test_no_version_group_id_returns_none(self, evaluator_mod):
        """Row without lineage (never published) → None."""
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(
            evaluator_id=10,
            tenant_id="t1",
            status="DRAFT",
            version_no=1,
            version_group_id=None,
            is_current=True,
        )
        with h.patch_session():
            assert evaluator_mod.restore_evaluator_version(10, "t1") is None

    def test_current_is_in_use_blocks_restore(self, evaluator_mod):
        AppExc = evaluator_mod.AppException
        h = _SessionHarness(evaluator_mod)
        # Target: historical (v2, not current)
        h.add_evaluator_row(
            evaluator_id=22,
            tenant_id="t1",
            status="PUBLISHED",
            version_no=2,
            version_group_id=20,
            is_current=False,
        )
        # Current: v3 (is_current=True)
        _current = h.add_evaluator_row(
            evaluator_id=23,
            tenant_id="t1",
            status="PUBLISHED",
            version_no=3,
            version_group_id=20,
            is_current=True,
        )
        # Active run pins the CURRENT version (evaluator_id=23)
        h.add_active_run(500, "t1", "RUNNING", evaluator_ids=[23])

        with h.patch_session(), pytest.raises(AppExc) as exc_info:
            evaluator_mod.restore_evaluator_version(22, "t1")

        assert "active evaluation run" in exc_info.value.message

    def test_restore_resets_is_current_and_sets_target(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        # Row 30 = v1 historical, 31 = v2 is_current (same group)
        hist = h.add_evaluator_row(
            evaluator_id=30,
            tenant_id="t1",
            status="PUBLISHED",
            version_no=1,
            version_group_id=30,
            is_current=False,
        )
        curr = h.add_evaluator_row(
            evaluator_id=31,
            tenant_id="t1",
            status="PUBLISHED",
            version_no=2,
            version_group_id=30,
            is_current=True,
        )
        with h.patch_session():
            result = evaluator_mod.restore_evaluator_version(30, "t1")

        assert result is not None
        assert result["evaluator_id"] == 30
        # Bulk reset → both had is_current set False by update call
        assert curr.is_current is False
        # Target flipped to True by the explicit setter
        assert hist.is_current is True
        assert h.commits >= 1


# ---------------------------------------------------------------------------
# 6. delete_evaluator_version tests
# ---------------------------------------------------------------------------


class TestDeleteEvaluatorVersion:
    def test_missing_version_returns_false(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        with h.patch_session():
            assert evaluator_mod.delete_evaluator_version(404, "t1") is False

    def test_current_version_cannot_be_deleted(self, evaluator_mod):
        AppExc = evaluator_mod.AppException
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(
            evaluator_id=41,
            tenant_id="t1",
            status="PUBLISHED",
            version_no=1,
            version_group_id=41,
            is_current=True,
        )
        with h.patch_session(), pytest.raises(AppExc) as exc_info:
            evaluator_mod.delete_evaluator_version(41, "t1")
        assert "Restore another version first" in exc_info.value.message

    def test_in_use_blocks_deletion(self, evaluator_mod):
        AppExc = evaluator_mod.AppException
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(
            evaluator_id=42,
            tenant_id="t1",
            status="PUBLISHED",
            version_no=1,
            version_group_id=40,
            is_current=False,
        )
        h.add_active_run(600, "t1", "RUNNING", evaluator_ids=[42])
        with h.patch_session(), pytest.raises(AppExc):
            evaluator_mod.delete_evaluator_version(42, "t1")

    def test_successful_delete_returns_true(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(
            evaluator_id=43,
            tenant_id="t1",
            status="PUBLISHED",
            version_no=1,
            version_group_id=40,
            is_current=False,
        )
        with h.patch_session():
            result = evaluator_mod.delete_evaluator_version(43, "t1")

        assert result is True
        assert 43 in h.deleted_ids
        assert h.commits >= 1


# ---------------------------------------------------------------------------
# 7. publish_evaluator tests
# ---------------------------------------------------------------------------


class TestPublishEvaluator:
    def test_missing_draft_returns_none(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        with h.patch_session():
            assert evaluator_mod.publish_evaluator(500, "t1") is None

    def test_first_publish_sets_version_group_id(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        row = h.add_evaluator_row(
            evaluator_id=50,
            tenant_id="t1",
            status="DRAFT",
            version_no=1,
            version_group_id=None,
            is_current=True,
        )
        with h.patch_session():
            result = evaluator_mod.publish_evaluator(
                50, "t1", version_name="v1", release_note="first"
            )

        assert result is not None
        assert result["status"] == "PUBLISHED"
        # version_group_id auto-set to evaluator_id on first publish
        assert row.version_group_id == 50
        assert h.commits >= 1

    def test_republish_preserves_existing_group_id(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(
            evaluator_id=51,
            tenant_id="t1",
            status="DRAFT",
            version_no=3,
            version_group_id=50,
            is_current=True,
        )
        with h.patch_session():
            result = evaluator_mod.publish_evaluator(51, "t1")

        assert result is not None
        # Already grouped → unchanged
        assert result["version_group_id"] == 50


# ---------------------------------------------------------------------------
# 8. list_evaluators / get_evaluator / create_evaluator / delete_evaluator /
#    list_evaluator_versions tests
# ---------------------------------------------------------------------------


class TestListEvaluators:
    def test_lists_current_rows_including_builtin(self, evaluator_mod):
        """Builtin evaluators (tenant_id='') are always included."""
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(
            1, tenant_id="t1", is_current=True, source="custom", evaluator_type="code", status="DRAFT"
        )
        h.add_evaluator_row(
            2, tenant_id="", is_current=True, source="builtin", evaluator_type="llm", status="PUBLISHED"
        )
        h.add_evaluator_row(3, tenant_id="t1", is_current=False, status="DRAFT")
        with h.patch_session():
            out = evaluator_mod.list_evaluators("t1")
        assert {r["evaluator_id"] for r in out} == {1, 2}

    def test_source_filter(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(1, tenant_id="t1", is_current=True, source="custom")
        h.add_evaluator_row(2, tenant_id="t1", is_current=True, source="builtin")
        with h.patch_session():
            out = evaluator_mod.list_evaluators("t1", source="builtin")
        assert [r["evaluator_id"] for r in out] == [2]

    def test_type_filter(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(1, tenant_id="t1", is_current=True, evaluator_type="code")
        h.add_evaluator_row(2, tenant_id="t1", is_current=True, evaluator_type="llm")
        with h.patch_session():
            out = evaluator_mod.list_evaluators("t1", evaluator_type="llm")
        assert [r["evaluator_id"] for r in out] == [2]

    def test_status_filter(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(1, tenant_id="t1", is_current=True, status="DRAFT")
        h.add_evaluator_row(2, tenant_id="t1", is_current=True, status="PUBLISHED")
        with h.patch_session():
            out = evaluator_mod.list_evaluators("t1", status="PUBLISHED")
        assert [r["evaluator_id"] for r in out] == [2]


class TestGetEvaluator:
    def test_returns_row(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(1, tenant_id="t1", name="ev")
        with h.patch_session():
            out = evaluator_mod.get_evaluator(1, "t1")
        assert out is not None
        assert out["name"] == "ev"

    def test_returns_none_when_missing(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        with h.patch_session():
            assert evaluator_mod.get_evaluator(999, "t1") is None


class TestCreateEvaluator:
    def test_creates_draft_row(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        with h.patch_session():
            out = evaluator_mod.create_evaluator(
                tenant_id="t1",
                user_id="u1",
                name="my ev",
                description="desc",
                evaluator_type="code",
                prompt=None,
                code="print(1)",
                model_id=7,
            )
        assert out["name"] == "my ev"
        assert out["status"] == "DRAFT"
        assert out["version_no"] == 1
        assert out["is_current"] is True
        assert out["created_by"] == "u1"
        # model_id is stored on the row but not serialised by _to_dict.
        assert h.evaluator_rows[out["evaluator_id"]].model_id == 7
        assert h.commits >= 1
        assert h.flushed is False  # create uses add/commit/refresh


class TestDeleteEvaluator:
    def test_in_use_raises(self, evaluator_mod):
        AppExc = evaluator_mod.AppException
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(1, tenant_id="t1", source="custom")
        h.add_active_run(10, "t1", "RUNNING", evaluator_ids=[1])
        with h.patch_session(), pytest.raises(AppExc) as ei:
            evaluator_mod.delete_evaluator(1, "t1")
        assert ei.value.code == "AGENT_EVALUATION_EVALUATOR_IN_USE"

    def test_deletes_row(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(1, tenant_id="t1", source="custom")
        with h.patch_session():
            assert evaluator_mod.delete_evaluator(1, "t1") is True
        assert 1 in h.deleted_ids

    def test_missing_returns_false(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        with h.patch_session():
            assert evaluator_mod.delete_evaluator(999, "t1") is False


class TestListEvaluatorVersions:
    def test_missing_current_returns_empty(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        with h.patch_session():
            assert evaluator_mod.list_evaluator_versions(999, "t1") == []

    def test_unpublished_returns_single_row(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(1, tenant_id="t1", version_group_id=None, version_no=1)
        with h.patch_session():
            out = evaluator_mod.list_evaluator_versions(1, "t1")
        assert len(out) == 1
        assert out[0]["evaluator_id"] == 1

    def test_returns_group_versions(self, evaluator_mod):
        h = _SessionHarness(evaluator_mod)
        h.add_evaluator_row(1, tenant_id="t1", version_group_id=10, version_no=1)
        h.add_evaluator_row(2, tenant_id="t1", version_group_id=10, version_no=2)
        h.add_evaluator_row(3, tenant_id="t1", version_group_id=10, version_no=3)
        h.add_evaluator_row(9, tenant_id="t1", version_group_id=99, version_no=1)
        with h.patch_session():
            out = evaluator_mod.list_evaluator_versions(1, "t1")
        assert sorted(r["version_no"] for r in out) == [1, 2, 3]
        assert all(r["version_group_id"] == 10 for r in out)
