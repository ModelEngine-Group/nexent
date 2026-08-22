import sys
from unittest.mock import MagicMock
import pytest

# ---------------------------------------------------------------------------
# Prepare stub modules and objects BEFORE importing the module under test.
# This prevents import-time errors that would otherwise be thrown because the
# real dependencies (SQLAlchemy, a live database, etc.) are not available in
# the unit-test environment.
# ---------------------------------------------------------------------------

# 1) Stub for `database.db_models` providing a minimal `PartnerMappingId` model.
class _PartnerMappingId:
    """Lightweight stand-in for the real SQLAlchemy model.
    It simply keeps every kwarg as an attribute so tests can later introspect
    what was passed in during instantiation.
    """

    # Provide dummy class-level attributes that behave like SQLAlchemy Columns so
    # that expressions such as ``PartnerMappingId.external_id == 'abc'`` used
    # inside the module under test do **not** raise AttributeError.  Using
    # MagicMock gives us an object on which ``__eq__`` is already defined and
    # simply returns another MagicMock, which is perfectly sufficient for the
    # purposes of our test (we never inspect the value of that comparison
    # object).
    external_id = MagicMock(name="external_id_column")
    internal_id = MagicMock(name="internal_id_column")
    mapping_type = MagicMock(name="mapping_type_column")
    delete_flag = MagicMock(name="delete_flag_column")
    tenant_id = MagicMock(name="tenant_id_column")
    user_id = MagicMock(name="user_id_column")

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


db_models_mock = MagicMock()
db_models_mock.PartnerMappingId = _PartnerMappingId
sys.modules['database.db_models'] = db_models_mock

# 2) Stub for `database.client` so that the module under test can import it.
client_mock = MagicMock()
sys.modules['database.client'] = client_mock

# 3) Provide a dummy SQLAlchemyError so that the except clause in the module
#    works without having to install SQLAlchemy in the CI environment.
class _SQLAlchemyError(Exception):
    pass

sys.modules['sqlalchemy'] = MagicMock()
sys.modules['sqlalchemy.exc'] = MagicMock()
sys.modules['sqlalchemy.exc'].SQLAlchemyError = _SQLAlchemyError

# ---------------------------------------------------------------------------
# Now we can safely import the module under test.
# ---------------------------------------------------------------------------
from backend.database import partner_db  # noqa: E402, isort:skip

# Patch the module-level SQLAlchemyError reference so tests can raise it easily.
partner_db.SQLAlchemyError = _SQLAlchemyError


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------
class DummySession(MagicMock):
    """Context-manager friendly MagicMock used to stand in for a DB session."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False  # propagate exceptions (if any)


def _patch_session(monkeypatch, session_instance):
    """Replace `get_db_session` with a context manager returning `session_instance`."""

    ctx_manager = MagicMock()
    ctx_manager.__enter__.return_value = session_instance
    ctx_manager.__exit__.return_value = None
    monkeypatch.setattr(partner_db, 'get_db_session', lambda: ctx_manager)


# ---------------------------------------------------------------------------
# Tests for `add_mapping_id`
# ---------------------------------------------------------------------------

def test_add_mapping_id_success(monkeypatch):
    session = DummySession()
    session.add = MagicMock()
    session.commit = MagicMock()

    _patch_session(monkeypatch, session)

    # Call
    partner_db.add_mapping_id(
        internal_id=1,
        external_id='ext-001',
        tenant_id='tenant-A',
        user_id='user-X',
        mapping_type='CONVERSATION',
    )

    # Assertions – the session methods should have been invoked correctly.
    session.add.assert_called_once()
    args, _ = session.add.call_args
    # The first positional arg is an instance of our stub PartnerMappingId
    assert isinstance(args[0], _PartnerMappingId)
    new_obj = args[0]
    assert new_obj.internal_id == 1
    assert new_obj.external_id == 'ext-001'
    assert new_obj.mapping_type == 'CONVERSATION'
    assert new_obj.tenant_id == 'tenant-A'
    assert new_obj.user_id == 'user-X'

    session.commit.assert_called_once()


def test_add_mapping_id_exception(monkeypatch):
    # get_db_session will raise _SQLAlchemyError to simulate DB failure.
    # Simulate that entering the context raises SQLAlchemyError
    class _CM:
        def __enter__(self):
            raise _SQLAlchemyError("DB down")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(partner_db, 'get_db_session', lambda: _CM())

    # Function should propagate the exception; verify it raises.
    with pytest.raises(_SQLAlchemyError):
        partner_db.add_mapping_id(1, 'e', 't', 'u')


# ---------------------------------------------------------------------------
# Tests for `get_internal_id_by_external`
# ---------------------------------------------------------------------------

def test_get_internal_id_by_external_found(monkeypatch):
    # Build a fake record the query should return.
    record = _PartnerMappingId(internal_id=42, external_id='ext-42')

    # Mock the SQLAlchemy query chain: session.query → filter → first
    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock  # allow chaining
    query_mock.first.return_value = record

    session = DummySession()
    session.query.return_value = query_mock

    _patch_session(monkeypatch, session)

    result = partner_db.get_internal_id_by_external('ext-42', tenant_id='tenant-id', user_id='user-id')
    assert result == 42


def test_get_internal_id_by_external_not_found(monkeypatch):
    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.first.return_value = None  # simulate no record

    session = DummySession()
    session.query.return_value = query_mock

    _patch_session(monkeypatch, session)

    result = partner_db.get_internal_id_by_external('missing')
    assert result is None


def test_get_internal_id_by_external_exception(monkeypatch):
    # Prepare context manager that raises inside __enter__
    class _CM:
        def __enter__(self):
            raise _SQLAlchemyError("fail")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(partner_db, 'get_db_session', lambda: _CM())
    with pytest.raises(_SQLAlchemyError):
        partner_db.get_internal_id_by_external('any')


# ---------------------------------------------------------------------------
# Tests for `get_external_id_by_internal`
# ---------------------------------------------------------------------------

def test_get_external_id_by_internal_found(monkeypatch):
    record = _PartnerMappingId(internal_id=101, external_id='ext-101')

    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.first.return_value = record

    session = DummySession()
    session.query.return_value = query_mock

    _patch_session(monkeypatch, session)

    result = partner_db.get_external_id_by_internal(101, tenant_id='tenant-id', user_id='user-id')
    assert result == 'ext-101'


def test_get_external_id_by_internal_not_found(monkeypatch):
    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.first.return_value = None

    session = DummySession()
    session.query.return_value = query_mock

    _patch_session(monkeypatch, session)

    result = partner_db.get_external_id_by_internal(999)
    assert result is None


def test_get_external_id_by_internal_exception(monkeypatch):
    class _CM:
        def __enter__(self):
            raise _SQLAlchemyError()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(partner_db, 'get_db_session', lambda: _CM())
    with pytest.raises(_SQLAlchemyError):
        partner_db.get_external_id_by_internal(1)