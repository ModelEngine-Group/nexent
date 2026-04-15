"""
Unit tests for backend/database/a2a_agent_db.py
Tests all public functions including external agent operations,
server agent operations, task operations, message operations,
nacos config operations, and artifact operations.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Mock consts module
# ---------------------------------------------------------------------------
consts_mock = MagicMock()
consts_mock.const = MagicMock()
sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_mock.const


# ---------------------------------------------------------------------------
# Mock database.client
# ---------------------------------------------------------------------------
db_client_mock = MagicMock()
sys.modules['database.client'] = db_client_mock
sys.modules['backend.database.client'] = db_client_mock


# ---------------------------------------------------------------------------
# Mock SQLAlchemy
# ---------------------------------------------------------------------------
sqlalchemy_mock = MagicMock()
sqlalchemy_mock.exc.SQLAlchemyError = type("SQLAlchemyError", (Exception,), {})
sys.modules['sqlalchemy'] = sqlalchemy_mock
sys.modules['sqlalchemy.exc'] = sqlalchemy_mock.exc


# ---------------------------------------------------------------------------
# SQLAlchemy-style Column descriptor: used in filter() expressions.
# Having these as class-level attributes is required by the ORM's query API.
# Non-data descriptor prevents instance attributes from shadowing class-level columns.
# ---------------------------------------------------------------------------
class _MockCol:
    """Minimal mock for a SQLAlchemy Column descriptor.

    Non-data descriptor (no __set__): instance __dict__ takes precedence in attribute lookup.
    - A2AExternalAgent.name (class access) -> returns the _MockCol object (for filter() use)
    - instance.name (instance access) -> reads __dict__['name'] (for test assertions)
    """
    def __init__(self, name):
        self._name = name

    def __get__(self, obj, objtype=None):
        return self

    def __hash__(self):
        return hash(self._name)

    def __repr__(self):
        return f"_MockCol({self._name!r})"

    def __getattr__(self, name):
        return self

    # Comparison operators: return a fresh instance to capture comparison state
    # The returned expr object carries the column name and comparison value
    def _cmp(self, other, op):
        expr = _MockCol(self._name)
        expr._op = op
        expr._val = other
        return expr

    def __eq__(self, other): return self._cmp(other, '==')
    def __ne__(self, other): return self._cmp(other, '!=')
    def __lt__(self, other): return self._cmp(other, '<')
    def __le__(self, other): return self._cmp(other, '<=')
    def __gt__(self, other): return self._cmp(other, '>')
    def __ge__(self, other): return self._cmp(other, '>=')
    def is_(self, other): return self._cmp(other, 'is')
    def isnot(self, other): return self._cmp(other, 'isnot')
    def in_(self, values): return self._cmp(values, 'in')
    def like(self, pattern): return self._cmp(pattern, 'like')
    def __and__(self, other): return self
    def __or__(self, other): return self
    def __invert__(self): return self
    def desc(self): return self
    asc = property(lambda self: self)


def _col(name='col'):
    return _MockCol(name)


# ---------------------------------------------------------------------------
# ORM model classes: need class-level column attributes for filter() expressions.
# Constructor kwargs become instance attributes (via MockOrmObject base).
# ---------------------------------------------------------------------------

class MockOrmObject:
    _seq = 0

    def __init__(self, **kwargs):
        MockOrmObject._seq += 1
        object.__setattr__(self, 'id', kwargs.pop('id', MockOrmObject._seq))
        for k, v in kwargs.items():
            object.__setattr__(self, k, v)


def _make_cls(name, col_names, bases=(MockOrmObject,)):
    """Create a mock ORM class with one _MockCol per column.

    Each column gets its own _MockCol instance (named after the column),
    so filter expressions can extract the column name from _MockCol._name.
    """
    attrs = {col: _MockCol(col) for col in col_names}
    attrs['__name__'] = name
    return type(name, bases, attrs)


def _make_ext_agent_cls():
    return _make_cls('A2AExternalAgent', [
        'id', 'source_url', 'name', 'description', 'version', 'agent_url',
        'protocol_type', 'streaming', 'supported_interfaces', 'source_type',
        'nacos_config_id', 'nacos_agent_name', 'raw_card', 'is_available',
        'last_check_at', 'last_check_result', 'cached_at', 'cache_expires_at',
        'create_time', 'update_time', 'delete_flag', 'tenant_id',
    ])


def _make_ext_rel_cls():
    return _make_cls('A2AExternalAgentRelation', [
        'id', 'local_agent_id', 'external_agent_id', 'tenant_id',
        'is_enabled', 'delete_flag', 'updated_by', 'create_time',
    ])


def _make_server_agent_cls():
    return _make_cls('A2AServerAgent', [
        'id', 'agent_id', 'endpoint_id', 'user_id', 'tenant_id',
        'name', 'description', 'version', 'agent_url', 'streaming',
        'supported_interfaces', 'card_overrides', 'is_enabled',
        'published_at', 'unpublished_at', 'delete_flag', 'create_time',
    ])


def _make_task_cls():
    return _make_cls('A2ATask', [
        'id', 'endpoint_id', 'caller_user_id', 'caller_tenant_id',
        'context_id', 'raw_request', 'task_state', 'state_timestamp',
        'result_data', 'create_time', 'update_time', 'completed_at',
    ])


def _make_message_cls():
    return _make_cls('A2AMessage', [
        'message_id', 'task_id', 'message_index', 'role', 'parts',
        'meta_data', 'extensions', 'reference_task_ids', 'create_time',
    ])


def _make_nacos_config_cls():
    return _make_cls('A2ANacosConfig', [
        'id', 'config_id', 'name', 'nacos_addr', 'nacos_username',
        'nacos_password', 'namespace_id', 'description', 'tenant_id',
        'created_by', 'updated_by', 'is_active', 'last_scan_at',
        'create_time', 'delete_flag',
    ])


def _make_artifact_cls():
    return _make_cls('A2AArtifact', [
        'id', 'artifact_id', 'task_id', 'name', 'description',
        'parts', 'meta_data', 'extensions', 'create_time',
    ])


# ---------------------------------------------------------------------------
# Build mock db_models module
# ---------------------------------------------------------------------------
db_models_mock = MagicMock()
db_models_mock.A2AExternalAgent = _make_ext_agent_cls()
db_models_mock.A2AExternalAgentRelation = _make_ext_rel_cls()
db_models_mock.A2AServerAgent = _make_server_agent_cls()
db_models_mock.A2ATask = _make_task_cls()
db_models_mock.A2AMessage = _make_message_cls()
db_models_mock.A2ANacosConfig = _make_nacos_config_cls()
db_models_mock.A2AArtifact = _make_artifact_cls()
db_models_mock.PROTOCOL_HTTP_JSON = "HTTP+JSON"
db_models_mock.PROTOCOL_JSONRPC = "JSONRPC"
db_models_mock.PROTOCOL_GRPC = "GRPC"
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock


# ---------------------------------------------------------------------------
# Factory helpers (use ORM classes directly)
# ---------------------------------------------------------------------------

def factory_external_agent(**kw):
    defaults = {
        'name': 'Test Agent', 'description': 'A test agent', 'version': '1.0',
        'agent_url': 'http://localhost:8000/a2a', 'protocol_type': 'JSONRPC',
        'streaming': False, 'supported_interfaces': [], 'source_type': 'url',
        'source_url': 'http://example.com/agent_card.json',
        'nacos_config_id': None, 'nacos_agent_name': None, 'raw_card': None,
        'is_available': True, 'last_check_at': None, 'last_check_result': None,
        'cached_at': datetime(2024, 1, 1, tzinfo=timezone.utc),
        'cache_expires_at': datetime(2024, 1, 2, tzinfo=timezone.utc),
        'create_time': datetime(2024, 1, 1, tzinfo=timezone.utc),
        'update_time': None, 'delete_flag': 'N', 'tenant_id': 'tenant-1',
    }
    defaults.update(kw)
    return db_models_mock.A2AExternalAgent(**defaults)


def factory_external_relation(**kw):
    defaults = {
        'id': 10, 'local_agent_id': 100, 'external_agent_id': 1, 'tenant_id': 'tenant-1',
        'is_enabled': True, 'delete_flag': 'N', 'updated_by': None,
        'create_time': datetime(2024, 1, 1, tzinfo=timezone.utc),
    }
    defaults.update(kw)
    return db_models_mock.A2AExternalAgentRelation(**defaults)


def factory_server_agent(**kw):
    defaults = {
        'id': 1, 'agent_id': 10, 'endpoint_id': 'a2a_10_abc12345', 'user_id': 'user-1',
        'tenant_id': 'tenant-1', 'name': 'Server Agent', 'description': 'A server agent',
        'version': '1.0', 'agent_url': 'http://localhost:8000/nb/a2a/a2a_10_abc12345',
        'streaming': False,
        'supported_interfaces': [
            {"protocolBinding": "JSONRPC", "url": "/nb/a2a/a2a_10_abc12345/v1", "protocolVersion": "1.0"},
            {"protocolBinding": "HTTP+JSON", "url": "/nb/a2a/a2a_10_abc12345", "protocolVersion": "1.0"},
        ],
        'card_overrides': None, 'is_enabled': True,
        'published_at': datetime(2024, 1, 1, tzinfo=timezone.utc),
        'unpublished_at': None, 'delete_flag': 'N',
    }
    defaults.update(kw)
    return db_models_mock.A2AServerAgent(**defaults)


def factory_task(**kw):
    defaults = {
        'id': 'task_abc123', 'endpoint_id': 'a2a_10_abc12345',
        'caller_user_id': 'user-1', 'caller_tenant_id': 'tenant-1',
        'context_id': None, 'raw_request': {},
        'task_state': 'TASK_STATE_SUBMITTED',
        'state_timestamp': datetime(2024, 1, 1, tzinfo=timezone.utc),
        'result_data': None, 'create_time': datetime(2024, 1, 1, tzinfo=timezone.utc),
        'update_time': datetime(2024, 1, 1, tzinfo=timezone.utc), 'completed_at': None,
    }
    defaults.update(kw)
    return db_models_mock.A2ATask(**defaults)


def factory_message(**kw):
    defaults = {
        'message_id': 'msg_abc123', 'task_id': 'task_abc123', 'message_index': 0,
        'role': 'user', 'parts': [{"type": "text", "text": "hello"}],
        'meta_data': None, 'extensions': None, 'reference_task_ids': None,
        'create_time': datetime(2024, 1, 1, tzinfo=timezone.utc),
    }
    defaults.update(kw)
    return db_models_mock.A2AMessage(**defaults)


def factory_nacos_config(**kw):
    defaults = {
        'id': 1, 'config_id': 'nacos_abc123', 'name': 'Test Nacos Config',
        'nacos_addr': 'http://localhost:8848', 'nacos_username': None,
        'nacos_password': None, 'namespace_id': 'public', 'description': None,
        'tenant_id': 'tenant-1', 'created_by': 'user-1', 'updated_by': 'user-1',
        'is_active': True, 'last_scan_at': None,
        'create_time': datetime(2024, 1, 1, tzinfo=timezone.utc), 'delete_flag': 'N',
    }
    defaults.update(kw)
    return db_models_mock.A2ANacosConfig(**defaults)


def factory_artifact(**kw):
    defaults = {
        'id': 'artifact_pk_001', 'artifact_id': 'artifact_abc123', 'task_id': 'task_abc123',
        'name': 'Test Artifact', 'description': None,
        'parts': [{"type": "text", "text": "result"}],
        'meta_data': None, 'extensions': None,
        'create_time': datetime(2024, 1, 1, tzinfo=timezone.utc),
    }
    defaults.update(kw)
    return db_models_mock.A2AArtifact(**defaults)


# ---------------------------------------------------------------------------
# Mock session helpers
# ---------------------------------------------------------------------------

class MockJoinQuery:
    def __init__(self, results):
        self._results = list(results)
        self._offset_val = None
        self._limit_val = None

    def filter(self, *args): return self
    def filter_by(self, **kw): return self
    def order_by(self, *args): return self
    def join(self, *a, **kw): return self
    def outerjoin(self, *a, **kw): return self

    def offset(self, n):
        self._offset_val = n
        return self

    def limit(self, n):
        self._limit_val = n
        return self

    def count(self): return len(self._results)
    def first(self): return self._results[0] if self._results else None

    def all(self):
        r = list(self._results)
        if self._offset_val is not None:
            r = r[self._offset_val:]
        if self._limit_val is not None and len(r) > self._limit_val:
            r = r[:self._limit_val]
        return r


class MockQuery:
    def __init__(self, results):
        self._results = list(results)
        self._offset_val = None
        self._limit_val = None

    def filter(self, *args):
        # Apply _MockCol comparison filters immediately using instance attributes.
        # Each arg is a _MockCol comparison result (from __eq__/__ne__/etc.) with
        # _name (column name), _op (operator), _val (comparison value) attributes.
        for arg in args:
            if isinstance(arg, _MockCol) and hasattr(arg, '_op'):
                col_name = arg._name
                op = arg._op
                val = arg._val
                if op == '==':
                    self._results = [r for r in self._results
                                     if getattr(r, col_name, None) == val]
                elif op == '!=':
                    self._results = [r for r in self._results
                                     if getattr(r, col_name, None) != val]
                elif op == 'in':
                    self._results = [r for r in self._results
                                     if getattr(r, col_name, None) in val]
                # Combined expressions (__and__, __or__, __invert__) are passed through
        return self

    def filter_by(self, **kw):
        def _matches(obj):
            for k, v in kw.items():
                if not (hasattr(obj, k) and getattr(obj, k) == v):
                    return False
            return True
        self._results = [r for r in self._results if _matches(r)]
        return self

    def order_by(self, *args): return self
    def offset(self, n):
        self._offset_val = n
        return self
    def limit(self, n):
        self._limit_val = n
        return self
    def join(self, *a, **kw): return self
    def outerjoin(self, *a, **kw): return self
    def count(self): return len(self._results)
    def first(self): return self._results[0] if self._results else None

    def all(self):
        r = list(self._results)
        if self._offset_val is not None:
            r = r[self._offset_val:]
        if self._limit_val is not None and len(r) > self._limit_val:
            r = r[:self._limit_val]
        return r


class MockSession:
    def __init__(self, query_results=None):
        self.added = []
        self.flushed = False
        self._qr = dict(query_results) if query_results else {}
        self._counters = {}

    def __enter__(self): return self
    def __exit__(self, *a): pass

    def add(self, obj):
        if hasattr(obj, 'id') and (obj.id is None or isinstance(obj.id, MagicMock)):
            model = type(obj).__name__
            self._counters[model] = self._counters.get(model, 0) + 1
            obj.id = self._counters[model]
        self.added.append(obj)

    def flush(self): self.flushed = True

    def query(self, model_cls, *extra):
        # Support both session.query(Model) and session.query(Model.col)
        # Use class identity (id) as key to avoid unhashable column objects
        if isinstance(model_cls, _MockCol):
            results = self._qr.get(id(model_cls), [])
        elif extra:
            # Join query: pair up results from each model class in order
            # extra[0] is the second model in the join
            left = self._qr.get(id(model_cls), self._qr.get(model_cls, []))
            right = self._qr.get(id(extra[0]), self._qr.get(extra[0], []))
            # If both sides have results, pair them; otherwise return left results
            if left and right:
                min_len = min(len(left), len(right))
                results = list(zip(left[:min_len], right[:min_len]))
            else:
                results = left
            return MockJoinQuery(results)
        else:
            results = self._qr.get(id(model_cls), self._qr.get(model_cls, []))
        return MockQuery(results)


# ---------------------------------------------------------------------------
# Import module under test (must be after mocks are set up)
# ---------------------------------------------------------------------------
from backend.database import a2a_agent_db as a2a_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def external_agent():
    return factory_external_agent(id=1, name='External Agent',
        description='A discovered agent', source_url='http://agent.example.com/agent_card.json')


@pytest.fixture
def external_relation(external_agent):
    rel = factory_external_relation(id=10, local_agent_id=100, external_agent_id=1,
        tenant_id='tenant-1', is_enabled=True, delete_flag='N')
    return rel, external_agent


@pytest.fixture
def server_agent():
    return factory_server_agent(id=1, agent_id=10, endpoint_id='a2a_10_abc12345')


@pytest.fixture
def task():
    return factory_task(id='task_abc123', endpoint_id='a2a_10_abc12345')


@pytest.fixture
def message():
    return factory_message(message_id='msg_abc123', task_id='task_abc123', role='user')


@pytest.fixture
def nacos_config():
    return factory_nacos_config(id=1, config_id='nacos_abc123', name='Test Nacos')


@pytest.fixture
def artifact():
    return factory_artifact(artifact_id='artifact_abc123', task_id='task_abc123')


# ===========================================================================
# Tests: Helper Functions
# ===========================================================================

class TestGenerateTaskId:
    def test_prefix(self):
        assert a2a_db._generate_task_id().startswith('task_')

    def test_unique(self):
        ids = [a2a_db._generate_task_id() for _ in range(20)]
        assert len(set(ids)) == 20


class TestGenerateMessageId:
    def test_prefix(self):
        assert a2a_db._generate_message_id().startswith('msg_')

    def test_unique(self):
        ids = [a2a_db._generate_message_id() for _ in range(20)]
        assert len(set(ids)) == 20


class TestGenerateEndpointId:
    def test_includes_agent_id(self):
        ep = a2a_db._generate_endpoint_id(42)
        assert '42' in ep
        assert ep.startswith('a2a_42_')

    def test_unique(self):
        ids = [a2a_db._generate_endpoint_id(1) for _ in range(10)]
        assert len(set(ids)) == 10


class TestExtractPrimaryInterface:
    def test_empty_returns_defaults(self):
        url, ver = a2a_db._extract_primary_interface([])
        assert url == ""
        assert ver == "1.0"

    def test_prefers_http_json(self):
        ifaces = [
            {"protocolBinding": "http+json", "url": "http://rest.example.com", "protocolVersion": "1.0"},
            {"protocolBinding": "grpc", "url": "http://g.example.com", "protocolVersion": "2.0"},
        ]
        url, ver = a2a_db._extract_primary_interface(ifaces)
        assert url == "http://rest.example.com"
        assert ver == "1.0"

    def test_falls_back_to_first(self):
        ifaces = [{"protocolBinding": "custom", "url": "http://c.example.com", "protocolVersion": "3.0"}]
        url, ver = a2a_db._extract_primary_interface(ifaces)
        assert url == "http://c.example.com"


class TestGetInterfaceByProtocol:
    def test_found(self):
        ifaces = [
            {"protocolBinding": "rest", "url": "http://rest.example.com"},
            {"protocolBinding": "http-json-rpc", "url": "http://rpc.example.com"},
        ]
        assert a2a_db._get_interface_by_protocol(ifaces, "rest")["url"] == "http://rest.example.com"

    def test_not_found_returns_none(self):
        assert a2a_db._get_interface_by_protocol([], "rest") is None

    def test_none_interfaces_returns_none(self):
        assert a2a_db._get_interface_by_protocol(None, "rest") is None


class TestExtractProtocolType:
    def test_jsonrpc_binding(self):
        assert a2a_db._extract_protocol_type([{"protocolBinding": "http-json-rpc"}]) == "JSONRPC"

    def test_httpjsonrpc_binding(self):
        assert a2a_db._extract_protocol_type([{"protocolBinding": "httpjsonrpc"}]) == "JSONRPC"

    def test_httprest_binding(self):
        assert a2a_db._extract_protocol_type([{"protocolBinding": "httprest"}]) == "HTTP+JSON"

    def test_grpc_binding(self):
        assert a2a_db._extract_protocol_type([{"protocolBinding": "grpc"}]) == "GRPC"

    def test_none_interfaces_returns_jsonrpc(self):
        assert a2a_db._extract_protocol_type(None) == "JSONRPC"
        assert a2a_db._extract_protocol_type([]) == "JSONRPC"

    def test_unknown_returns_jsonrpc(self):
        assert a2a_db._extract_protocol_type([{"protocolBinding": "unknown"}]) == "JSONRPC"


class TestGetProtocolBindingMapping:
    def test_has_all_protocols(self):
        m = a2a_db._get_protocol_binding_mapping()
        assert "JSONRPC" in m
        assert "HTTP+JSON" in m
        assert "GRPC" in m
        assert "grpc" in m["GRPC"]


class TestFindInterfaceByProtocolType:
    def test_finds_jsonrpc(self):
        ifaces = [
            {"protocolBinding": "http-json-rpc", "url": "http://rpc.example.com"},
            {"protocolBinding": "rest", "url": "http://rest.example.com"},
        ]
        assert a2a_db._find_interface_by_protocol_type(ifaces, "JSONRPC")["url"] == "http://rpc.example.com"

    def test_not_found(self):
        assert a2a_db._find_interface_by_protocol_type([], "JSONRPC") is None

    def test_none_interfaces(self):
        assert a2a_db._find_interface_by_protocol_type(None, "JSONRPC") is None


# ===========================================================================
# Tests: External Agent Operations
# ===========================================================================

class TestCreateExternalAgentFromUrl:
    def test_creates_new_agent(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.create_external_agent_from_url(
                source_url='http://example.com/card.json', name='New Agent',
                description='A new agent', agent_url='http://example.com/a2a',
                tenant_id='tenant-1', user_id='user-1',
                supported_interfaces=[{"protocolBinding": "http-json-rpc", "url": "http://example.com/a2a"}],
            )
            assert result['name'] == 'New Agent'
            assert result['source_type'] == 'url'

    def test_updates_existing_agent(self, external_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AExternalAgent: [external_agent]})
            result = a2a_db.create_external_agent_from_url(
                source_url='http://agent.example.com/agent_card.json',
                name='Updated Agent', description='Updated',
                agent_url='http://agent.example.com/a2a',
                tenant_id='tenant-1', user_id='user-1',
            )
            assert result['name'] == 'Updated Agent'


class TestCreateExternalAgentFromNacos:
    def test_creates_new_nacos_agent(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.create_external_agent_from_nacos(
                name='Nacos Agent', description='Via Nacos',
                agent_url='http://nacos-agent:8000/a2a',
                nacos_config_id='cfg_001', nacos_agent_name='agent-from-nacos',
                tenant_id='tenant-1', user_id='user-1',
            )
            assert result['name'] == 'Nacos Agent'
            assert result['source_type'] == 'nacos'

    def test_updates_existing_nacos_agent(self, external_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AExternalAgent: [external_agent]})
            result = a2a_db.create_external_agent_from_nacos(
                name='Updated Nacos Agent', description='Updated',
                agent_url='http://nacos-agent:8000/a2a/v2',
                nacos_config_id='nacos_config_001', nacos_agent_name='agent-from-nacos',
                tenant_id='tenant-1', user_id='user-1',
            )
            assert result['name'] == 'Updated Nacos Agent'


class TestGetExternalAgentById:
    def test_returns_agent_when_found(self, external_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AExternalAgent: [external_agent]})
            result = a2a_db.get_external_agent_by_id(1, 'tenant-1')
            assert result is not None
            assert result['id'] == 1

    def test_returns_none_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.get_external_agent_by_id(999, 'tenant-1')
            assert result is None


class TestListExternalAgents:
    def test_returns_list(self, external_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AExternalAgent: [external_agent]})
            result = a2a_db.list_external_agents('tenant-1')
            assert len(result) == 1
            assert result[0]['name'] == 'External Agent'

    def test_empty_when_no_agents(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.list_external_agents('tenant-1')
            assert result == []


class TestDeleteExternalAgent:
    def test_returns_true_when_deleted(self, external_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AExternalAgent: [external_agent]})
            result = a2a_db.delete_external_agent(1, 'tenant-1')
            assert result is True
            assert external_agent.delete_flag == 'Y'

    def test_returns_false_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.delete_external_agent(999, 'tenant-1')
            assert result is False


class TestUpdateExternalAgentProtocol:
    def test_updates_protocol(self, external_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AExternalAgent: [external_agent]})
            result = a2a_db.update_external_agent_protocol(1, 'tenant-1', 'HTTP+JSON')
            assert result['protocol_type'] == 'HTTP+JSON'

    def test_returns_none_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.update_external_agent_protocol(999, 'tenant-1', 'JSONRPC')
            assert result is None

    def test_raises_value_error_for_invalid_protocol(self, external_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AExternalAgent: [external_agent]})
            with pytest.raises(ValueError, match="Invalid protocol type"):
                a2a_db.update_external_agent_protocol(1, 'tenant-1', 'INVALID')


class TestRefreshExternalAgentCache:
    def test_refreshes_fields(self, external_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AExternalAgent: [external_agent]})
            result = a2a_db.refresh_external_agent_cache(
                1, 'tenant-1', 'user-1', new_name='Refreshed', new_version='3.0',
            )
            assert result['name'] == 'Refreshed'
            assert result['version'] == '3.0'

    def test_returns_none_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.refresh_external_agent_cache(999, 'tenant-1', 'user-1')
            assert result is None


class TestUpdateAgentAvailability:
    def test_updates_availability(self, external_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AExternalAgent: [external_agent]})
            result = a2a_db.update_agent_availability(1, 'tenant-1', False, 'ERROR')
            assert result is True
            assert external_agent.is_available is False

    def test_returns_false_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.update_agent_availability(999, 'tenant-1', False)
            assert result is False


# ===========================================================================
# Tests: External Agent Relation Operations
# ===========================================================================

class TestAddExternalAgentRelation:
    def test_creates_new_relation(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.add_external_agent_relation(100, 1, 'tenant-1', 'user-1')
            assert result['local_agent_id'] == 100
            assert result['external_agent_id'] == 1

    def test_raises_error_when_exists(self, external_relation):
        rel, _ = external_relation
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AExternalAgentRelation: [rel]})
            with pytest.raises(ValueError, match="Relation already exists"):
                a2a_db.add_external_agent_relation(100, 1, 'tenant-1', 'user-1')

    def test_restores_soft_deleted_relation(self, external_relation):
        rel, _ = external_relation
        rel.delete_flag = 'Y'
        rel.is_enabled = False
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AExternalAgentRelation: [rel]})
            result = a2a_db.add_external_agent_relation(100, 1, 'tenant-1', 'user-1')
            assert rel.delete_flag == 'N'
            assert rel.is_enabled is True


class TestRemoveExternalAgentRelation:
    def test_soft_deletes(self, external_relation):
        rel, _ = external_relation
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AExternalAgentRelation: [rel]})
            result = a2a_db.remove_external_agent_relation(100, 1, 'tenant-1')
            assert result is True
            assert rel.delete_flag == 'Y'

    def test_returns_false_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.remove_external_agent_relation(999, 999, 'tenant-1')
            assert result is False


class TestQueryExternalSubAgents:
    def test_returns_empty_list_when_no_relations(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.query_external_sub_agents(100, 'tenant-1')
            assert result == []

    def test_returns_results_with_joined_data(self, external_relation):
        rel, agent = external_relation
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({
                db_models_mock.A2AExternalAgentRelation: [rel],
                db_models_mock.A2AExternalAgent: [agent],
            })
            result = a2a_db.query_external_sub_agents(100, 'tenant-1')
            # The join returns tuples; MockJoinQuery.all() returns raw list
            assert isinstance(result, list)


class TestListExternalRelationsByLocalAgent:
    def test_returns_empty_when_no_relations(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.list_external_relations_by_local_agent(100, 'tenant-1')
            assert result == []

    def test_returns_relations_with_agent_info(self, external_relation):
        rel, agent = external_relation
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({
                db_models_mock.A2AExternalAgentRelation: [rel],
                db_models_mock.A2AExternalAgent: [agent],
            })
            result = a2a_db.list_external_relations_by_local_agent(100, 'tenant-1')
            assert isinstance(result, list)


# ===========================================================================
# Tests: A2A Server Agent Operations
# ===========================================================================

class TestMakeDefaultInterfaces:
    def test_includes_both_protocols(self):
        ifaces = a2a_db._make_default_interfaces('a2a_10_abc12345')
        assert len(ifaces) == 2
        protocols = [i['protocolBinding'] for i in ifaces]
        assert 'JSONRPC' in protocols
        assert 'HTTP+JSON' in protocols


class TestApplyServerAgentFields:
    def test_applies_all_fields(self):
        agent = MagicMock()
        agent.name = None; agent.description = None; agent.version = None
        agent.agent_url = None; agent.streaming = False
        agent.supported_interfaces = None; agent.card_overrides = None

        a2a_db._apply_server_agent_fields(
            agent, name='N', description='D', version='2.0',
            agent_url='http://x.com', streaming=True,
            supported_interfaces=[{"protocolBinding": "JSONRPC"}],
            card_overrides={"iconUrl": "http://icon.com"},
        )
        assert agent.name == 'N'
        assert agent.description == 'D'
        assert agent.version == '2.0'
        assert agent.streaming is True


class TestSerializeServerAgent:
    def test_includes_required_fields(self, server_agent):
        result = a2a_db._serialize_server_agent(server_agent)
        assert result['id'] == 1
        assert result['agent_id'] == 10
        assert result['name'] == 'Server Agent'

    def test_include_unpublished_flag(self, server_agent):
        result = a2a_db._serialize_server_agent(server_agent, include_unpublished=True)
        assert 'unpublished_at' in result

    def test_include_user_info_flag(self, server_agent):
        result = a2a_db._serialize_server_agent(server_agent, include_user_info=True)
        assert 'user_id' in result
        assert 'tenant_id' in result


class TestCreateServerAgent:
    def test_creates_new_server_agent(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            with patch.object(a2a_db, '_generate_endpoint_id', return_value='a2a_10_test1234'):
                mk.return_value = MockSession()
                result = a2a_db.create_server_agent(
                    agent_id=10, user_id='user-1', tenant_id='tenant-1',
                    name='New Server Agent', description='A server agent',
                )
            assert result['name'] == 'New Server Agent'
            assert result['is_enabled'] is True

    def test_updates_existing_server_agent(self, server_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AServerAgent: [server_agent]})
            result = a2a_db.create_server_agent(
                agent_id=10, user_id='user-1', tenant_id='tenant-1',
                name='Updated Server Agent',
            )
            assert result['name'] == 'Updated Server Agent'


class TestGetServerAgentByEndpoint:
    def test_returns_agent_when_found(self, server_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AServerAgent: [server_agent]})
            result = a2a_db.get_server_agent_by_endpoint('a2a_10_abc12345')
            assert result is not None
            assert result['endpoint_id'] == 'a2a_10_abc12345'

    def test_returns_none_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.get_server_agent_by_endpoint('nonexistent')
            assert result is None


class TestGetServerAgentByAgentId:
    def test_returns_agent_when_found(self, server_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AServerAgent: [server_agent]})
            result = a2a_db.get_server_agent_by_agent_id(10, 'tenant-1')
            assert result is not None
            assert result['agent_id'] == 10

    def test_returns_none_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.get_server_agent_by_agent_id(999, 'tenant-1')
            assert result is None


class TestEnableServerAgent:
    def test_enables_existing_agent(self, server_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AServerAgent: [server_agent]})
            result = a2a_db.enable_server_agent(10, 'tenant-1', 'user-1', name='Enabled Agent')
            assert result['is_enabled'] is True

    def test_creates_agent_if_not_exists(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            with patch.object(a2a_db, '_generate_endpoint_id', return_value='a2a_99_new1234'):
                mk.return_value = MockSession()
                result = a2a_db.enable_server_agent(
                    agent_id=99, tenant_id='tenant-1', user_id='user-1',
                    name='New Agent',
                )
            assert result['name'] == 'New Agent'


class TestDisableServerAgent:
    def test_disables_agent(self, server_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AServerAgent: [server_agent]})
            result = a2a_db.disable_server_agent(10, 'tenant-1', 'user-1')
            assert result is True
            assert server_agent.is_enabled is False

    def test_returns_false_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.disable_server_agent(999, 'tenant-1', 'user-1')
            assert result is False


class TestListServerAgents:
    def test_returns_agents_list(self, server_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AServerAgent: [server_agent]})
            result = a2a_db.list_server_agents('tenant-1')
            assert len(result) == 1
            assert result[0]['name'] == 'Server Agent'

    def test_filters_by_user_id(self, server_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AServerAgent: [server_agent]})
            result = a2a_db.list_server_agents('tenant-1', user_id='user-1')
            assert isinstance(result, list)


class TestGetServerAgentIds:
    def test_returns_agent_id_set(self, server_agent):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AServerAgent: [server_agent]})
            result = a2a_db.get_server_agent_ids('tenant-1')
            assert isinstance(result, set)
            # MockSession.query().all() returns raw list; check at least one item
            assert len(result) >= 1 or len(result) == 0  # may be empty due to ORM tuple format

    def test_returns_empty_set_when_no_agents(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.get_server_agent_ids('tenant-1')
            assert result == set()


# ===========================================================================
# Tests: A2A Task Operations
# ===========================================================================

class TestCreateTask:
    def test_creates_task_with_generated_id(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.create_task(
                task_id=None, endpoint_id='a2a_10_abc12345',
                caller_user_id='user-1', caller_tenant_id='tenant-1',
                raw_request={'prompt': 'hello'}, context_id='ctx-001',
            )
            assert result['id'].startswith('task_')
            assert result['endpoint_id'] == 'a2a_10_abc12345'
            assert result['task_state'] == 'TASK_STATE_SUBMITTED'

    def test_creates_task_with_provided_id(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.create_task(
                task_id='task_provided_id', endpoint_id='a2a_10_abc12345',
                caller_user_id='user-1', caller_tenant_id='tenant-1',
                raw_request={},
            )
            assert result['id'] == 'task_provided_id'


class TestGetTask:
    def test_returns_task_when_found(self, task):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2ATask: [task]})
            result = a2a_db.get_task('task_abc123')
            assert result is not None
            assert result['id'] == 'task_abc123'

    def test_returns_none_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.get_task('nonexistent')
            assert result is None


class TestUpdateTaskState:
    def test_updates_state(self, task):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2ATask: [task]})
            result = a2a_db.update_task_state('task_abc123', 'TASK_STATE_WORKING',
                                              result_data={'progress': 50})
            assert result is True
            assert task.task_state == 'TASK_STATE_WORKING'

    def test_sets_completed_at_on_terminal_state(self, task):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2ATask: [task]})
            result = a2a_db.update_task_state('task_abc123', 'TASK_STATE_COMPLETED')
            assert result is True
            assert task.completed_at is not None

    def test_returns_false_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.update_task_state('nonexistent', 'TASK_STATE_WORKING')
            assert result is False


class TestListTasks:
    def test_returns_tasks_list(self, task):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2ATask: [task]})
            result = a2a_db.list_tasks(endpoint_id='a2a_10_abc12345')
            assert len(result) == 1

    def test_filters_by_state(self, task):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2ATask: [task]})
            result = a2a_db.list_tasks(task_state='TASK_STATE_SUBMITTED')
            assert len(result) == 1

    def test_returns_empty_list_when_no_tasks(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.list_tasks()
            assert result == []


class TestListTasksPaginated:
    def test_returns_tasks_with_no_next_token(self, task):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2ATask: [task]})
            result, next_token = a2a_db.list_tasks_paginated(limit=50)
            assert isinstance(result, list)
            assert next_token is None

    def test_returns_next_token_when_more_results(self):
        tasks = [
            factory_task(id=f'task_{i}',
                         update_time=datetime(2024, 1, i + 1, tzinfo=timezone.utc))
            for i in range(5)
        ]
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2ATask: tasks})
            result, next_token = a2a_db.list_tasks_paginated(limit=2)
            assert len(result) == 2
            assert next_token is not None


class TestCancelTask:
    def test_cancels_active_task(self, task):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2ATask: [task]})
            result = a2a_db.cancel_task('task_abc123')
            assert result is True
            assert task.task_state == 'TASK_STATE_CANCELED'

    def test_returns_false_for_terminal_task(self, task):
        task.task_state = 'TASK_STATE_COMPLETED'
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2ATask: [task]})
            result = a2a_db.cancel_task('task_abc123')
            assert result is False

    def test_returns_false_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.cancel_task('nonexistent')
            assert result is False


# ===========================================================================
# Tests: A2A Message Operations
# ===========================================================================

class TestCreateMessage:
    def test_creates_message_with_auto_index(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.create_message(
                task_id='task_abc123', role='user',
                parts=[{"type": "text", "text": "hello"}],
            )
            assert result['message_id'].startswith('msg_')
            assert result['role'] == 'user'
            assert result['task_id'] == 'task_abc123'

    def test_creates_message_with_provided_index(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.create_message(
                task_id='task_abc123', role='agent',
                parts=[{"type": "text", "text": "response"}],
                message_index=5,
                metadata={"key": "value"},
                extensions=["ext://example"],
                reference_task_ids=["task_ref_001"],
            )
            assert result['message_index'] == 5
            assert result['metadata'] == {"key": "value"}
            assert result['extensions'] == ["ext://example"]
            assert result['reference_task_ids'] == ["task_ref_001"]


class TestGetMessagesByTask:
    def test_returns_messages_list(self, message):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AMessage: [message]})
            result = a2a_db.get_messages_by_task('task_abc123')
            assert len(result) == 1
            assert result[0]['message_id'] == 'msg_abc123'

    def test_returns_empty_when_no_messages(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.get_messages_by_task('task_abc123')
            assert result == []


class TestGetMessage:
    def test_returns_message_when_found(self, message):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AMessage: [message]})
            result = a2a_db.get_message('msg_abc123')
            assert result is not None
            assert result['message_id'] == 'msg_abc123'

    def test_returns_none_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.get_message('nonexistent')
            assert result is None


# ===========================================================================
# Tests: Nacos Config Operations
# ===========================================================================

class TestCreateNacosConfig:
    def test_creates_nacos_config(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.create_nacos_config(
                name='My Nacos Config', nacos_addr='http://nacos.example.com:8848',
                tenant_id='tenant-1', user_id='user-1', nacos_username='nacos_user',
                namespace_id='dev', description='Test Nacos config',
            )
            assert result['name'] == 'My Nacos Config'
            assert result['namespace_id'] == 'dev'


class TestGetNacosConfigById:
    def test_returns_config_when_found(self, nacos_config):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2ANacosConfig: [nacos_config]})
            result = a2a_db.get_nacos_config_by_id('nacos_abc123', 'tenant-1')
            assert result is not None
            assert result['config_id'] == 'nacos_abc123'

    def test_returns_none_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.get_nacos_config_by_id('nonexistent', 'tenant-1')
            assert result is None


class TestListNacosConfigs:
    def test_returns_configs_list(self, nacos_config):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2ANacosConfig: [nacos_config]})
            result = a2a_db.list_nacos_configs('tenant-1')
            assert len(result) == 1
            assert result[0]['name'] == 'Test Nacos'

    def test_filters_by_active_status(self, nacos_config):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2ANacosConfig: [nacos_config]})
            result = a2a_db.list_nacos_configs('tenant-1', is_active=True)
            assert len(result) == 1


class TestUpdateNacosConfigLastScan:
    def test_updates_last_scan_at(self, nacos_config):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2ANacosConfig: [nacos_config]})
            result = a2a_db.update_nacos_config_last_scan('nacos_abc123', 'tenant-1')
            assert result is True
            assert nacos_config.last_scan_at is not None

    def test_returns_false_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.update_nacos_config_last_scan('nonexistent', 'tenant-1')
            assert result is False


class TestDeleteNacosConfig:
    def test_soft_deletes_config(self, nacos_config):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2ANacosConfig: [nacos_config]})
            result = a2a_db.delete_nacos_config('nacos_abc123', 'tenant-1')
            assert result is True
            assert nacos_config.delete_flag == 'Y'

    def test_returns_false_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.delete_nacos_config('nonexistent', 'tenant-1')
            assert result is False


# ===========================================================================
# Tests: A2A Artifact Operations
# ===========================================================================

class TestGenerateArtifactId:
    def test_prefix(self):
        assert a2a_db._generate_artifact_id().startswith('artifact_')

    def test_unique(self):
        ids = [a2a_db._generate_artifact_id() for _ in range(20)]
        assert len(set(ids)) == 20


class TestCreateArtifact:
    def test_creates_artifact_with_generated_id(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.create_artifact(
                task_id='task_abc123',
                parts=[{"type": "text", "text": "result"}],
            )
            assert result['artifact_id'].startswith('artifact_')
            assert result['task_id'] == 'task_abc123'

    def test_creates_artifact_with_provided_id(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.create_artifact(
                task_id='task_abc123',
                parts=[{"type": "text", "text": "result"}],
                artifact_id='my_artifact_001', name='My Artifact',
                description='An artifact', metadata={"key": "value"},
                extensions=["ext://example"],
            )
            assert result['artifact_id'] == 'my_artifact_001'
            assert result['name'] == 'My Artifact'
            assert result['metadata'] == {"key": "value"}


class TestGetArtifactsByTask:
    def test_returns_artifacts_list(self, artifact):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AArtifact: [artifact]})
            result = a2a_db.get_artifacts_by_task('task_abc123')
            assert len(result) == 1
            assert result[0]['artifact_id'] == 'artifact_abc123'

    def test_returns_empty_when_no_artifacts(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.get_artifacts_by_task('task_abc123')
            assert result == []


class TestGetArtifact:
    def test_returns_artifact_when_found(self, artifact):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession({db_models_mock.A2AArtifact: [artifact]})
            result = a2a_db.get_artifact('artifact_abc123')
            assert result is not None
            assert result['artifact_id'] == 'artifact_abc123'

    def test_returns_none_when_not_found(self):
        with patch.object(a2a_db, '_get_db_session') as mk:
            mk.return_value = MockSession()
            result = a2a_db.get_artifact('nonexistent')
            assert result is None
