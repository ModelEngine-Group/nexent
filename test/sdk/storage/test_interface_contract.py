# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SI-001/005/009/011: lightweight contracts and explicit failure semantics."""

import subprocess
import sys
from pathlib import Path
from threading import Event
from time import monotonic

import pytest
from nexent.storage.errors import (
    CapabilityUnsupported,
    DeadlineExceeded,
    InvalidInput,
    OperationCancelled,
)
from nexent.storage.models import (
    TTL,
    CapabilitySet,
    OperationContext,
    StorageScope,
    TTLMode,
)


def test_contract_import_does_not_load_drivers_or_application_packages():
    sdk = Path(__file__).resolve().parents[3] / "sdk"
    code = """
import importlib.abc, sys
sys.path.insert(0, sys.argv[1])
class RejectDrivers(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'boto3', 'redis', 'sqlalchemy', 'psycopg2',
                                     'elasticsearch', 'backend', 'infrastructure', 'dotenv'}:
            raise AssertionError('Unexpected dependency ' + fullname)
sys.meta_path.insert(0, RejectDrivers())
from nexent.storage.interfaces import StorageInterface, KeyValueStore, RecordStore, ObjectStore, VectorStore
from nexent.storage.models import StorageScope
from nexent import MessageObserver
from nexent.core.utils.observer import MessageObserver as ObserverImplementation
from nexent.storage import StorageClient, StorageConfig, MinIOStorageConfig
assert MessageObserver is ObserverImplementation
assert StorageScope('runtime', 'tenant', 'actor', frozenset({'cache'})).tenant_id == 'tenant'
assert not {'boto3', 'redis', 'sqlalchemy', 'elasticsearch'} & sys.modules.keys()
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(sdk)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("tenant", [None, "", " "])
def test_empty_tenant_never_grants_system_access(tenant):
    with pytest.raises(InvalidInput):
        StorageScope("runtime", tenant, "actor", frozenset({"cache"}))


def test_capabilities_fail_before_an_unsupported_operation():
    capabilities = CapabilitySet(frozenset({"kv.get", "kv.put"}))
    capabilities.require("kv.get")
    with pytest.raises(CapabilityUnsupported):
        capabilities.require("kv.compare_exchange")


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf")])
def test_expiring_ttl_requires_a_finite_positive_duration(seconds):
    with pytest.raises(InvalidInput):
        TTL(TTLMode.DURATION, seconds)


def test_preserve_and_no_expiry_are_distinct():
    assert TTL(TTLMode.PRESERVE) != TTL(TTLMode.NO_EXPIRY)
    with pytest.raises(InvalidInput):
        TTL(TTLMode.PRESERVE, 10)


def test_deadline_and_cancellation_are_checked_without_io():
    with pytest.raises(DeadlineExceeded):
        OperationContext("expired", monotonic() - 1).remaining()
    cancelled = Event()
    cancelled.set()
    with pytest.raises(OperationCancelled):
        OperationContext("cancelled", monotonic() + 1, cancelled).remaining()


def test_scope_copies_mutable_namespace_inputs():
    namespaces = {"cache"}
    scope = StorageScope("runtime", "tenant", "actor", namespaces)
    namespaces.add("other")
    assert scope.namespaces == frozenset({"cache"})


@pytest.mark.parametrize("namespaces", [None, "cache"])
def test_scope_rejects_namespace_inputs_that_are_not_collections(namespaces):
    with pytest.raises(InvalidInput):
        StorageScope("runtime", "tenant", "actor", namespaces)
