import sys
import os
import unittest
from unittest.mock import patch, MagicMock
import types
from contextlib import contextmanager
from enum import Enum

# Ensure backend modules can be imported and avoid real MinIO init
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

# Stub consts.model for MemoryAgentShareMode
consts_model = types.ModuleType("consts.model")
class MemoryAgentShareMode(str, Enum):
    ALWAYS = "always"
    ASK = "ask"
    NEVER = "never"
consts_model.MemoryAgentShareMode = MemoryAgentShareMode
sys.modules["consts.model"] = consts_model

# Stub consts.const values used by service
consts_const = types.ModuleType("consts.const")
consts_const.MEMORY_SWITCH_KEY = "MEMORY_SWITCH"
consts_const.MEMORY_AGENT_SHARE_KEY = "MEMORY_AGENT_SHARE"
consts_const.DISABLE_AGENT_ID_KEY = "DISABLE_AGENT_ID"
consts_const.DISABLE_USERAGENT_ID_KEY = "DISABLE_USERAGENT_ID"
consts_const.DEFAULT_MEMORY_SWITCH_KEY = "N"
consts_const.DEFAULT_MEMORY_AGENT_SHARE_KEY = MemoryAgentShareMode.NEVER.value
sys.modules["consts.const"] = consts_const

# Stub nexent.core.agents.agent_model for MemoryContext and MemoryUserConfig
agent_model_mod = types.ModuleType("nexent.core.agents.agent_model")
class MemoryUserConfig:
    def __init__(self, memory_switch: bool, agent_share_option: str, disable_agent_ids, disable_user_agent_ids):
        self.memory_switch = memory_switch
        self.agent_share_option = agent_share_option
        self.disable_agent_ids = disable_agent_ids
        self.disable_user_agent_ids = disable_user_agent_ids
class MemoryContext:
    def __init__(self, user_config, memory_config, tenant_id, user_id, agent_id):
        self.user_config = user_config
        self.memory_config = memory_config
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.agent_id = agent_id
agent_model_mod.MemoryUserConfig = MemoryUserConfig
agent_model_mod.MemoryContext = MemoryContext
sys.modules["nexent.core.agents.agent_model"] = agent_model_mod

# Fake out database.client to prevent boto3/MinIO side effects and provide needed APIs
fake_client = types.ModuleType("database.client")

def _filter_property(data, model_class):
    try:
        fields = set(model_class.__table__.columns.keys())
    except Exception:
        fields = set(data.keys())
    return {k: v for k, v in data.items() if k in fields}

@contextmanager
def _get_db_session(db_session=None):
    class DummySession:
        def query(self, *_, **__):
            class DummyQuery:
                def filter(self, *__, **___):
                    class DummyAll:
                        def all(self_inner):
                            return []
                    return DummyAll()
            return DummyQuery()
        def add(self, *_a, **_k):
            pass
        def commit(self):
            pass
        def rollback(self):
            pass
        def close(self):
            pass
        def execute(self, *_, **__):
            return None
        def scalars(self, *_, **__):
            class Dummy:
                def first(self):
                    return None
            return Dummy()
    sess = DummySession() if db_session is None else db_session
    try:
        yield sess
    finally:
        pass

fake_client.filter_property = _filter_property
fake_client.get_db_session = _get_db_session
sys.modules["database.client"] = fake_client
sys.modules['boto3'] = MagicMock()

# Stub database.memory_config_db to avoid importing SQLAlchemy models at import time
memcfg_db = types.ModuleType("database.memory_config_db")

def _noop(*args, **kwargs):
    return True

def _return_empty_list(*args, **kwargs):
    return []

memcfg_db.get_all_configs_by_user_id = _return_empty_list
memcfg_db.get_memory_config_info = _return_empty_list
memcfg_db.insert_config = _noop
memcfg_db.delete_config_by_config_id = _noop
memcfg_db.update_config_by_id = _noop
sys.modules["database.memory_config_db"] = memcfg_db

# Stub utils.memory_utils to ensure import works even if not patched
utils_memory_utils = types.ModuleType("utils.memory_utils")
utils_memory_utils.build_memory_config = lambda tenant_id: {}
sys.modules["utils.memory_utils"] = utils_memory_utils


class TestMemoryConfigService(unittest.TestCase):
    def setUp(self):
        self.user_id = "u1"
        self.tenant_id = "t1"
        self.agent_id = 123

    # ------------------------------- helpers -------------------------------
    @patch("backend.services.memory_config_service.get_all_configs_by_user_id")
    def test_get_user_configs_defaults_and_aggregation(self, m_get_all):
        # one single key, and two multi values
        m_get_all.return_value = [
            {"config_key": "MEMORY_SWITCH", "config_value": "Y", "value_type": "single"},
            {"config_key": "DISABLE_AGENT_ID", "config_value": "A1", "value_type": "multi"},
            {"config_key": "DISABLE_AGENT_ID", "config_value": "A2", "value_type": "multi"},
        ]

        from backend.services.memory_config_service import get_user_configs, MEMORY_AGENT_SHARE_KEY

        configs = get_user_configs(self.user_id)
        # present keys preserved
        self.assertEqual(configs["MEMORY_SWITCH"], "Y")
        self.assertEqual(configs["DISABLE_AGENT_ID"], ["A1", "A2"])
        # missing single key gets default
        self.assertIn(MEMORY_AGENT_SHARE_KEY, configs)

    @patch("backend.services.memory_config_service.get_all_configs_by_user_id", return_value=[])
    def test_get_user_configs_default_switch_when_missing(self, m_get_all):
        from backend.services.memory_config_service import get_user_configs

        configs = get_user_configs(self.user_id)
        # MEMORY_SWITCH should be defaulted when missing from DB
        self.assertIn(consts_const.MEMORY_SWITCH_KEY, configs)
        self.assertEqual(configs[consts_const.MEMORY_SWITCH_KEY], consts_const.DEFAULT_MEMORY_SWITCH_KEY)

    # --------------------------- _update_single_config ---------------------------
    @patch("backend.services.memory_config_service.update_config_by_id")
    @patch("backend.services.memory_config_service.get_memory_config_info")
    def test_update_single_config_update_branch_success(self, m_get_info, m_update):
        m_get_info.return_value = [{"config_id": 10}]
        m_update.return_value = True

        from backend.services.memory_config_service import _update_single_config

        ok = _update_single_config(self.user_id, "MEMORY_SWITCH", "Y")
        self.assertTrue(ok)
        m_update.assert_called_once()

    @patch("backend.services.memory_config_service.update_config_by_id", return_value=False)
    @patch("backend.services.memory_config_service.get_memory_config_info", return_value=[{"config_id": 11}])
    def test_update_single_config_update_branch_fail(self, m_get_info, m_update):
        from backend.services.memory_config_service import _update_single_config

        ok = _update_single_config(self.user_id, "MEMORY_SWITCH", "N")
        self.assertFalse(ok)

    @patch("backend.services.memory_config_service.insert_config", return_value=True)
    @patch("backend.services.memory_config_service.get_memory_config_info", return_value=[])
    def test_update_single_config_insert_branch_success(self, m_get_info, m_insert):
        from backend.services.memory_config_service import _update_single_config

        ok = _update_single_config(self.user_id, "MEMORY_SWITCH", "Y")
        self.assertTrue(ok)
        m_insert.assert_called_once()

    @patch("backend.services.memory_config_service.insert_config", return_value=False)
    @patch("backend.services.memory_config_service.get_memory_config_info", return_value=[])
    def test_update_single_config_insert_branch_fail(self, m_get_info, m_insert):
        from backend.services.memory_config_service import _update_single_config

        ok = _update_single_config(self.user_id, "MEMORY_SWITCH", "Y")
        self.assertFalse(ok)

    # ------------------------------ _add_multi_value ------------------------------
    @patch("backend.services.memory_config_service.insert_config", return_value=True)
    @patch("backend.services.memory_config_service.get_memory_config_info", return_value=[])
    def test_add_multi_value_insert_success(self, m_get_info, m_insert):
        from backend.services.memory_config_service import _add_multi_value

        ok = _add_multi_value(self.user_id, "DISABLE_AGENT_ID", "A1")
        self.assertTrue(ok)

    @patch("backend.services.memory_config_service.insert_config", return_value=False)
    @patch("backend.services.memory_config_service.get_memory_config_info", return_value=[])
    def test_add_multi_value_insert_fail(self, m_get_info, m_insert):
        from backend.services.memory_config_service import _add_multi_value

        ok = _add_multi_value(self.user_id, "DISABLE_AGENT_ID", "A1")
        self.assertFalse(ok)

    @patch("backend.services.memory_config_service.get_memory_config_info", return_value=[{"config_value": "A1"}])
    def test_add_multi_value_already_exists(self, m_get_info):
        from backend.services.memory_config_service import _add_multi_value

        ok = _add_multi_value(self.user_id, "DISABLE_AGENT_ID", "A1")
        self.assertTrue(ok)

    # ---------------------------- _remove_multi_value ----------------------------
    @patch("backend.services.memory_config_service.delete_config_by_config_id", return_value=True)
    @patch("backend.services.memory_config_service.get_memory_config_info", return_value=[{"config_id": 9, "config_value": "A1"}])
    def test_remove_multi_value_success(self, m_get_info, m_del):
        from backend.services.memory_config_service import _remove_multi_value

        ok = _remove_multi_value(self.user_id, "DISABLE_AGENT_ID", "A1")
        self.assertTrue(ok)
        m_del.assert_called_once_with(9, updated_by=self.user_id)

    @patch("backend.services.memory_config_service.delete_config_by_config_id", return_value=False)
    @patch("backend.services.memory_config_service.get_memory_config_info", return_value=[{"config_id": 9, "config_value": "A1"}])
    def test_remove_multi_value_fail(self, m_get_info, m_del):
        from backend.services.memory_config_service import _remove_multi_value

        ok = _remove_multi_value(self.user_id, "DISABLE_AGENT_ID", "A1")
        self.assertFalse(ok)

    @patch("backend.services.memory_config_service.get_memory_config_info", return_value=[{"config_id": 9, "config_value": "A2"}])
    def test_remove_multi_value_not_found(self, m_get_info):
        from backend.services.memory_config_service import _remove_multi_value

        ok = _remove_multi_value(self.user_id, "DISABLE_AGENT_ID", "A1")
        self.assertTrue(ok)  # treat not found as success

    # -------------------------- getters/setters wrappers --------------------------
    @patch("backend.services.memory_config_service.get_user_configs", return_value={"MEMORY_SWITCH": "Y"})
    def test_get_memory_switch(self, m_get):
        from backend.services.memory_config_service import get_memory_switch

        self.assertTrue(get_memory_switch(self.user_id))

    @patch("backend.services.memory_config_service._update_single_config", return_value=True)
    def test_set_memory_switch_true(self, m_upd):
        from backend.services.memory_config_service import set_memory_switch

        self.assertTrue(set_memory_switch(self.user_id, True))
        m_upd.assert_called_once()

    @patch("backend.services.memory_config_service.get_user_configs", return_value={"MEMORY_AGENT_SHARE": "always"})
    def test_get_agent_share_valid(self, m_get):
        from backend.services.memory_config_service import get_agent_share
        self.assertEqual(get_agent_share(self.user_id), MemoryAgentShareMode.ALWAYS)

    @patch("backend.services.memory_config_service.get_user_configs", return_value={"MEMORY_AGENT_SHARE": "weird"})
    def test_get_agent_share_invalid(self, m_get):
        from backend.services.memory_config_service import get_agent_share
        self.assertEqual(get_agent_share(self.user_id), MemoryAgentShareMode.NEVER)

    @patch("backend.services.memory_config_service._update_single_config", return_value=True)
    def test_set_agent_share(self, m_upd):
        from backend.services.memory_config_service import set_agent_share
        self.assertTrue(set_agent_share(self.user_id, MemoryAgentShareMode.ASK))

    @patch("backend.services.memory_config_service.get_user_configs", return_value={"DISABLE_AGENT_ID": ["A1", "A2"]})
    def test_get_disabled_agent_ids(self, m_get):
        from backend.services.memory_config_service import get_disabled_agent_ids

        ids = get_disabled_agent_ids(self.user_id)
        self.assertEqual(ids, ["A1", "A2"])

    @patch("backend.services.memory_config_service.get_user_configs", return_value={})
    def test_get_disabled_agent_ids_default_empty(self, m_get):
        from backend.services.memory_config_service import get_disabled_agent_ids

        ids = get_disabled_agent_ids(self.user_id)
        self.assertEqual(ids, [])

    @patch("backend.services.memory_config_service.get_user_configs", return_value={"DISABLE_USERAGENT_ID": ["UA1"]})
    def test_get_disabled_useragent_ids(self, m_get):
        from backend.services.memory_config_service import get_disabled_useragent_ids

        ids = get_disabled_useragent_ids(self.user_id)
        self.assertEqual(ids, ["UA1"])

    @patch("backend.services.memory_config_service.get_user_configs", return_value={})
    def test_get_disabled_useragent_ids_default_empty(self, m_get):
        from backend.services.memory_config_service import get_disabled_useragent_ids

        ids = get_disabled_useragent_ids(self.user_id)
        self.assertEqual(ids, [])

    @patch("backend.services.memory_config_service._add_multi_value", return_value=True)
    def test_add_disabled_agent_id(self, m_add):
        from backend.services.memory_config_service import add_disabled_agent_id

        self.assertTrue(add_disabled_agent_id(self.user_id, "A1"))
        m_add.assert_called_once()

    @patch("backend.services.memory_config_service._remove_multi_value", return_value=True)
    def test_remove_disabled_agent_id(self, m_rm):
        from backend.services.memory_config_service import remove_disabled_agent_id

        self.assertTrue(remove_disabled_agent_id(self.user_id, "A1"))
        m_rm.assert_called_once()

    @patch("backend.services.memory_config_service._add_multi_value", return_value=True)
    def test_add_disabled_useragent_id(self, m_add):
        from backend.services.memory_config_service import add_disabled_useragent_id

        self.assertTrue(add_disabled_useragent_id(self.user_id, "UA1"))
        m_add.assert_called_once()

    @patch("backend.services.memory_config_service._remove_multi_value", return_value=True)
    def test_remove_disabled_useragent_id(self, m_rm):
        from backend.services.memory_config_service import remove_disabled_useragent_id

        self.assertTrue(remove_disabled_useragent_id(self.user_id, "UA1"))
        m_rm.assert_called_once()

    # ---------------------------- build_memory_context ----------------------------
    @patch("backend.services.memory_config_service.get_memory_switch", return_value=False)
    def test_build_memory_context_switch_off(self, m_switch):
        with patch("backend.services.memory_config_service.get_agent_share", return_value=MagicMock(value="never")), \
             patch("backend.services.memory_config_service.get_disabled_agent_ids", return_value=[]), \
             patch("backend.services.memory_config_service.get_disabled_useragent_ids", return_value=[]):
            from backend.services.memory_config_service import build_memory_context

            ctx = build_memory_context(self.user_id, self.tenant_id, self.agent_id)
            self.assertEqual(ctx.tenant_id, self.tenant_id)
            self.assertEqual(ctx.user_id, self.user_id)
            self.assertEqual(ctx.agent_id, str(self.agent_id))
            self.assertEqual(ctx.memory_config, {})  # empty dict when off

    @patch("backend.services.memory_config_service.get_memory_switch", return_value=True)
    def test_build_memory_context_switch_on(self, m_switch):
        with patch("backend.services.memory_config_service.get_agent_share", return_value=MagicMock(value="ask")), \
             patch("backend.services.memory_config_service.get_disabled_agent_ids", return_value=["A1"]), \
             patch("backend.services.memory_config_service.get_disabled_useragent_ids", return_value=["UA1"]), \
             patch("backend.services.memory_config_service.build_memory_config", return_value={"cfg": 1}) as m_build:
            from backend.services.memory_config_service import build_memory_context

            ctx = build_memory_context(self.user_id, self.tenant_id, self.agent_id)
            self.assertEqual(ctx.memory_config, {"cfg": 1})
            m_build.assert_called_once_with(self.tenant_id)

    def test_build_memory_context_skip_query(self):
        """Test build_memory_context with skip_query=True"""
        from backend.services.memory_config_service import build_memory_context

        ctx = build_memory_context(self.user_id, self.tenant_id, self.agent_id, skip_query=True)

        self.assertEqual(ctx.tenant_id, self.tenant_id)
        self.assertEqual(ctx.user_id, self.user_id)
        self.assertEqual(ctx.agent_id, str(self.agent_id))
        self.assertEqual(ctx.memory_config, {})  # empty dict when query skipped
        self.assertEqual(ctx.user_config.memory_switch, False)
        self.assertEqual(ctx.user_config.agent_share_option, "never")  # Updated to "never"
        self.assertEqual(ctx.user_config.disable_agent_ids, [])
        self.assertEqual(ctx.user_config.disable_user_agent_ids, [])

    def test_build_memory_context_skip_query_no_db_calls(self):
        """Test that skip_query=True doesn't make any database calls"""
        from backend.services.memory_config_service import build_memory_context

        # Mock all the database functions to ensure they're not called
        with patch("backend.services.memory_config_service.get_memory_switch") as mock_memory_switch, \
             patch("backend.services.memory_config_service.get_agent_share") as mock_agent_share, \
             patch("backend.services.memory_config_service.get_disabled_agent_ids") as mock_disabled_agents, \
             patch("backend.services.memory_config_service.get_disabled_useragent_ids") as mock_disabled_user_agents, \
             patch("backend.services.memory_config_service.build_memory_config") as mock_build_config:

            ctx = build_memory_context(self.user_id, self.tenant_id, self.agent_id, skip_query=True)

            # Verify no database functions were called
            mock_memory_switch.assert_not_called()
            mock_agent_share.assert_not_called()
            mock_disabled_agents.assert_not_called()
            mock_disabled_user_agents.assert_not_called()
            mock_build_config.assert_not_called()

            # Verify the context is still properly constructed
            self.assertEqual(ctx.tenant_id, self.tenant_id)
            self.assertEqual(ctx.user_id, self.user_id)
            self.assertEqual(ctx.agent_id, str(self.agent_id))

    def test_build_memory_context_default_behavior(self):
        """Test build_memory_context default behavior (skip_query=False)"""
        from backend.services.memory_config_service import build_memory_context

        # Test that default parameter works as expected
        ctx = build_memory_context(self.user_id, self.tenant_id, self.agent_id)

        # Should have called database functions (covered by existing tests)
        # Just verify the structure
        self.assertEqual(ctx.tenant_id, self.tenant_id)
        self.assertEqual(ctx.user_id, self.user_id)
        self.assertEqual(ctx.agent_id, str(self.agent_id))
        self.assertIsInstance(ctx.memory_config, dict)
        self.assertIsNotNone(ctx.user_config)


if __name__ == "__main__":
    unittest.main()
