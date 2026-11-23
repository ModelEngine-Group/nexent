"""Unit tests for ``aidp_exceptions`` domain exception classes.

Each exception carries structured context (kb_id, tenant_id, etc.) and produces
a human-readable message. Tests verify instantiation, attribute storage,
string representation, raise/catch semantics, and inheritance.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
BACKEND_ROOT = str(Path(PROJECT_ROOT) / "backend")
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from ext_components.aidp.consts.aidp_exceptions import (
    AidpGroupValidationError,
    AidpKbConflictError,
    AidpKbNotFoundError,
    AidpKbPermissionDeniedError,
    AidpKbSyncError,
)


# ---------------------------------------------------------------------------
# AidpKbNotFoundError
# ---------------------------------------------------------------------------

class TestAidpKbNotFoundError:
    def test_without_tenant_id(self):
        exc = AidpKbNotFoundError("kb-1")
        assert exc.kb_id == "kb-1"
        assert exc.tenant_id is None
        assert str(exc) == "AIDP knowledge base kb-1 not found"

    def test_with_tenant_id(self):
        exc = AidpKbNotFoundError("kb-1", tenant_id="t-42")
        assert exc.kb_id == "kb-1"
        assert exc.tenant_id == "t-42"
        assert str(exc) == "AIDP knowledge base kb-1 not found in tenant t-42"

    def test_raise_and_catch(self):
        with pytest.raises(AidpKbNotFoundError) as info:
            raise AidpKbNotFoundError("kb-x")
        assert info.value.kb_id == "kb-x"

    def test_is_exception_subclass(self):
        assert isinstance(AidpKbNotFoundError("kb"), Exception)


# ---------------------------------------------------------------------------
# AidpKbPermissionDeniedError
# ---------------------------------------------------------------------------

class TestAidpKbPermissionDeniedError:
    def test_instantiation_and_message(self):
        exc = AidpKbPermissionDeniedError("kb-1", "user-7", "write")
        assert exc.kb_id == "kb-1"
        assert exc.user_id == "user-7"
        assert exc.required == "write"
        assert str(exc) == "User user-7 lacks write permission on kb-1"

    def test_raise_and_catch(self):
        with pytest.raises(AidpKbPermissionDeniedError) as info:
            raise AidpKbPermissionDeniedError("kb-2", "u-1", "read")
        assert "read" in str(info.value)

    def test_is_exception_subclass(self):
        assert isinstance(
            AidpKbPermissionDeniedError("kb", "u", "r"), Exception
        )


# ---------------------------------------------------------------------------
# AidpKbConflictError
# ---------------------------------------------------------------------------

class TestAidpKbConflictError:
    def test_instantiation_and_message(self):
        exc = AidpKbConflictError("kb-1", "t-99")
        assert exc.kb_id == "kb-1"
        assert exc.tenant_id == "t-99"
        assert str(exc) == "Knowledge base kb-1 already exists in tenant t-99"

    def test_raise_and_catch(self):
        with pytest.raises(AidpKbConflictError):
            raise AidpKbConflictError("kb-3", "t-1")

    def test_is_exception_subclass(self):
        assert isinstance(AidpKbConflictError("kb", "t"), Exception)


# ---------------------------------------------------------------------------
# AidpKbSyncError
# ---------------------------------------------------------------------------

class TestAidpKbSyncError:
    def test_operation_only(self):
        exc = AidpKbSyncError("sync")
        assert exc.operation == "sync"
        assert exc.kb_id is None
        assert exc.cause is None
        assert str(exc) == "AIDP sync failed"

    def test_with_kb_id(self):
        exc = AidpKbSyncError("fetch", kb_id="kb-5")
        assert exc.kb_id == "kb-5"
        assert exc.cause is None
        assert str(exc) == "AIDP fetch for kb-5 failed"

    def test_with_cause(self):
        cause = ConnectionError("timeout")
        exc = AidpKbSyncError("sync", cause=cause)
        assert exc.cause is cause
        assert "timeout" in str(exc)
        assert str(exc) == "AIDP sync failed (timeout)"

    def test_with_kb_id_and_cause(self):
        cause = RuntimeError("bad response")
        exc = AidpKbSyncError("push", kb_id="kb-8", cause=cause)
        assert exc.operation == "push"
        assert exc.kb_id == "kb-8"
        assert exc.cause is cause
        assert str(exc) == "AIDP push for kb-8 failed (bad response)"

    def test_raise_and_catch(self):
        with pytest.raises(AidpKbSyncError) as info:
            raise AidpKbSyncError("import", kb_id="kb-10")
        assert info.value.operation == "import"

    def test_is_exception_subclass(self):
        assert isinstance(AidpKbSyncError("op"), Exception)


# ---------------------------------------------------------------------------
# AidpGroupValidationError
# ---------------------------------------------------------------------------

class TestAidpGroupValidationError:
    def test_instantiation_and_message(self):
        exc = AidpGroupValidationError([1, 2, 3], "t-5")
        assert exc.invalid_ids == [1, 2, 3]
        assert exc.tenant_id == "t-5"
        assert str(exc) == "Group ids [1, 2, 3] are not part of tenant t-5"

    def test_invalid_ids_is_copied(self):
        original = [10, 20]
        exc = AidpGroupValidationError(original, "t-1")
        original.append(30)
        assert exc.invalid_ids == [10, 20]

    def test_empty_invalid_ids(self):
        exc = AidpGroupValidationError([], "t-1")
        assert exc.invalid_ids == []
        assert "[]" in str(exc)

    def test_raise_and_catch(self):
        with pytest.raises(AidpGroupValidationError) as info:
            raise AidpGroupValidationError([99], "t-x")
        assert info.value.invalid_ids == [99]

    def test_is_exception_subclass(self):
        assert isinstance(AidpGroupValidationError([], "t"), Exception)


# ---------------------------------------------------------------------------
# __all__ public API
# ---------------------------------------------------------------------------

class TestPublicAPI:
    def test_all_exports(self):
        from ext_components.aidp.consts import aidp_exceptions

        expected = {
            "AidpKbNotFoundError",
            "AidpKbPermissionDeniedError",
            "AidpKbConflictError",
            "AidpKbSyncError",
            "AidpGroupValidationError",
        }
        assert set(aidp_exceptions.__all__) == expected
