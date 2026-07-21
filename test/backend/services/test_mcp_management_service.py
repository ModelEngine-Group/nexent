"""
Unit tests for backend/services/mcp_management_service.py
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
sys.modules['boto3'] = MagicMock()
from unittest.mock import patch as _patch
try:
    _patch('botocore.client.BaseClient._make_api_call', return_value={}).start()
except Exception:
    pass

# Mock all database dependencies before imports
db_client_mock = MagicMock()
db_client_mock.get_db_session = MagicMock()
db_client_mock.as_dict = MagicMock()
db_client_mock.filter_property = MagicMock()
db_client_mock.MinioClient = MagicMock()

sys.modules['database.client'] = db_client_mock
sys.modules['backend.database.client'] = db_client_mock

# Mock database submodules
sys.modules['database.market_mcp_db'] = MagicMock()
sys.modules['database.market_review_db'] = MagicMock()
sys.modules['database.remote_mcp_db'] = MagicMock()
sys.modules['database.db_models'] = MagicMock()
sys.modules['database.user_tenant_db'] = MagicMock()

sys.modules['backend.database.market_mcp_db'] = sys.modules['database.market_mcp_db']
sys.modules['backend.database.market_review_db'] = sys.modules['database.market_review_db']
sys.modules['backend.database.remote_mcp_db'] = sys.modules['database.remote_mcp_db']
sys.modules['backend.database.db_models'] = sys.modules['database.db_models']
sys.modules['backend.database.user_tenant_db'] = sys.modules['database.user_tenant_db']

storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
try:
    _patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
           return_value=storage_client_mock).start()
    _patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
    _patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()
except Exception:
    pass

from consts.exceptions import McpNotFoundError, McpNameConflictError, UnauthorizedError

from backend.services.mcp_management_service import (
    _to_community_card,
    _get_mcp_review_admin_scope,
    _resolve_author_display_name,
    _resolve_user_email,
    _validate_market_status_transition,
    list_community_mcp_services,
    list_community_mcp_tag_stats,
    list_community_mcp_review_services,
    publish_community_mcp_service,
    update_community_mcp_service,
    approve_community_mcp_service,
    reject_community_mcp_service,
    change_mcp_market_status,
    delete_community_mcp_service,
    list_my_community_mcp_services,
    list_registry_mcp_services,
)

# Re-patch exception references in the module
import backend.services.mcp_management_service as svc_mod
svc_mod.McpNotFoundError = McpNotFoundError
svc_mod.McpNameConflictError = McpNameConflictError
svc_mod.UnauthorizedError = UnauthorizedError

MARKET_RECORD = {
    "market_id": 1,
    "tenant_id": "tid",
    "user_id": "uid",
    "mcp_name": "svc1",
    "mcp_server": "http://srv",
    "description": "desc",
    "transport_type": "url",
    "config_json": None,
    "registry_json": None,
    "tags": ["a"],
    "review_status": "shared",
    "download_count": 5,
    "source_mcp_id": 1,
    "submitted_by": "user@test.com",
    "create_time": "t1",
    "update_time": "t2",
}

PENDING_RECORD = {
    "market_id": 2,
    "tenant_id": "tid",
    "user_id": "uid",
    "mcp_name": "new-svc",
    "mcp_server": "http://new",
    "description": "new desc",
    "transport_type": "url",
    "config_json": None,
    "registry_json": None,
    "tags": ["b"],
    "review_status": "pending_review",
    "download_count": 0,
    "source_mcp_id": 1,
    "submitted_by": None,
    "create_time": "t1",
    "update_time": "t2",
}


# ============================================================================
# Helper / utility function tests
# ============================================================================

class TestToCommunityCard(unittest.TestCase):
    """Test _to_community_card transforms a DB row to the API response shape."""

    def test_market_record_shared(self):
        card = _to_community_card(MARKET_RECORD)
        self.assertEqual(card["marketId"], 1)
        self.assertEqual(card["communityId"], 1)
        self.assertEqual(card["name"], "svc1")
        self.assertEqual(card["reviewStatus"], "approved")
        self.assertEqual(card["installCount"], 5)

    def test_minimal_row_defaults(self):
        card = _to_community_card({})
        self.assertIsNone(card["marketId"])
        self.assertEqual(card["tags"], [])
        self.assertEqual(card["installCount"], 0)
        self.assertEqual(card["reviewStatus"], "offline")
        self.assertEqual(card["reviewType"], "initial_listing")

    def test_config_json_not_dict(self):
        card = _to_community_card({"config_json": "string", "registry_json": 123})
        self.assertIsNone(card["configJson"])
        self.assertIsNone(card["registryJson"])

    def test_author_display_name_resolved(self):
        with patch('backend.services.mcp_management_service.get_user_tenant_by_user_id') as mock_get:
            mock_get.return_value = {"user_email": "user@example.com"}
            card = _to_community_card({"user_id": "uid"})
            self.assertEqual(card["authorDisplayName"], "user@example.com")

    def test_author_display_name_no_user(self):
        card = _to_community_card({"user_id": None})
        self.assertIsNone(card["authorDisplayName"])

    def test_shared_fields_included(self):
        """to_community_card should include shared_fields from the market record row."""
        card = _to_community_card({
            **MARKET_RECORD,
            "group_ids": "2,4",
            "ingroup_permission": "EDIT",
            "shared_fields": {"serverUrl": True, "authorizationToken": False},
        })
        self.assertEqual(card["groupIds"], "2,4")
        self.assertEqual(card["ingroupPermission"], "EDIT")
        self.assertEqual(card["sharedFields"], {"serverUrl": True, "authorizationToken": False})


class TestGetMcpReviewAdminScope(unittest.TestCase):
    """Test _get_mcp_review_admin_scope checks user role."""

    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    def test_admin_returns_tenant_id(self, mock_get):
        mock_get.return_value = {"user_role": "ADMIN"}
        result = _get_mcp_review_admin_scope("uid", "tid")
        self.assertEqual(result, "tid")

    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    def test_super_admin_returns_none(self, mock_get):
        mock_get.return_value = {"user_role": "SUPER_ADMIN"}
        result = _get_mcp_review_admin_scope("uid", "tid")
        self.assertIsNone(result)

    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    def test_su_returns_none(self, mock_get):
        mock_get.return_value = {"user_role": "SU"}
        result = _get_mcp_review_admin_scope("uid", "tid")
        self.assertIsNone(result)

    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    def test_dev_raises_unauthorized(self, mock_get):
        mock_get.return_value = {"user_role": "DEV"}
        with self.assertRaises(UnauthorizedError):
            _get_mcp_review_admin_scope("uid", "tid")

    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    def test_no_role_found_raises(self, mock_get):
        mock_get.return_value = {}
        with self.assertRaises(UnauthorizedError):
            _get_mcp_review_admin_scope("uid", "tid")


class TestResolveAuthorDisplayName(unittest.TestCase):
    """Test _resolve_author_display_name resolves user_id to email."""

    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    def test_resolves_email(self, mock_get):
        mock_get.return_value = {"user_email": "  author@test.com  "}
        result = _resolve_author_display_name("uid")
        self.assertEqual(result, "author@test.com")

    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    def test_none_user_id(self, mock_get):
        result = _resolve_author_display_name(None)
        self.assertIsNone(result)

    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    def test_no_email_in_record(self, mock_get):
        mock_get.return_value = {}
        result = _resolve_author_display_name("uid")
        self.assertIsNone(result)


# ============================================================================
# _validate_market_status_transition (NEW)
# ============================================================================

class TestValidateMarketStatusTransition(unittest.TestCase):
    """Test _validate_market_status_transition covers role, ownership, and transitions."""

    def make_record(self, **overrides):
        return {"tenant_id": "tid", "user_id": "uid", **overrides}

    # --- SU role ---

    def test_su_valid_transition_pending_to_shared(self):
        result = _validate_market_status_transition(
            user_role="SU", current_status="pending_review", new_status="shared",
            record=self.make_record(), user_id="suid", tenant_id="tid",
        )
        self.assertIsNone(result)

    def test_su_valid_transition_pending_to_rejected(self):
        result = _validate_market_status_transition(
            user_role="SU", current_status="pending_review", new_status="rejected",
            record=self.make_record(), user_id="suid", tenant_id="tid",
        )
        self.assertIsNone(result)

    def test_su_valid_transition_shared_to_not_shared(self):
        result = _validate_market_status_transition(
            user_role="SU", current_status="shared", new_status="not_shared",
            record=self.make_record(), user_id="suid", tenant_id="tid",
        )
        self.assertIsNone(result)

    def test_su_invalid_transition_raises(self):
        with self.assertRaises(ValueError):
            _validate_market_status_transition(
                user_role="SU", current_status="shared", new_status="rejected",
                record=self.make_record(), user_id="suid", tenant_id="tid",
            )

    # --- ADMIN role ---

    def test_admin_cross_tenant_raises(self):
        with self.assertRaises(UnauthorizedError):
            _validate_market_status_transition(
                user_role="ADMIN", current_status="pending_review", new_status="shared",
                record=self.make_record(tenant_id="other_tid"),
                user_id="admin_uid", tenant_id="tid",
            )

    def test_admin_valid_review_transition_shared(self):
        result = _validate_market_status_transition(
            user_role="ADMIN", current_status="pending_review", new_status="shared",
            record=self.make_record(), user_id="admin_uid", tenant_id="tid",
        )
        self.assertIsNone(result)

    def test_admin_valid_review_transition_rejected(self):
        result = _validate_market_status_transition(
            user_role="ADMIN", current_status="pending_review", new_status="rejected",
            record=self.make_record(), user_id="admin_uid", tenant_id="tid",
        )
        self.assertIsNone(result)

    @patch('backend.services.mcp_management_service._resolve_user_email', return_value="admin@test.com")
    def test_admin_publisher_transition_submit(self, mock_email):
        result = _validate_market_status_transition(
            user_role="ADMIN", current_status="not_shared", new_status="pending_review",
            record=self.make_record(), user_id="admin_uid", tenant_id="tid",
        )
        self.assertEqual(result, "admin@test.com")

    def test_admin_publisher_transition_withdraw(self):
        result = _validate_market_status_transition(
            user_role="ADMIN", current_status="pending_review", new_status="not_shared",
            record=self.make_record(), user_id="admin_uid", tenant_id="tid",
        )
        self.assertIsNone(result)

    def test_admin_invalid_transition_raises(self):
        with self.assertRaises(ValueError):
            _validate_market_status_transition(
                user_role="ADMIN", current_status="shared", new_status="pending_review",
                record=self.make_record(), user_id="admin_uid", tenant_id="tid",
            )

    # --- DEV role ---

    def test_dev_cross_tenant_raises(self):
        with self.assertRaises(UnauthorizedError):
            _validate_market_status_transition(
                user_role="DEV", current_status="not_shared", new_status="pending_review",
                record=self.make_record(tenant_id="other_tid"),
                user_id="uid", tenant_id="tid",
            )

    def test_dev_cross_user_raises(self):
        with self.assertRaises(UnauthorizedError):
            _validate_market_status_transition(
                user_role="DEV", current_status="not_shared", new_status="pending_review",
                record=self.make_record(user_id="other_uid"),
                user_id="uid", tenant_id="tid",
            )

    @patch('backend.services.mcp_management_service._resolve_user_email', return_value="user@test.com")
    def test_dev_valid_submit(self, mock_email):
        result = _validate_market_status_transition(
            user_role="DEV", current_status="not_shared", new_status="pending_review",
            record=self.make_record(), user_id="uid", tenant_id="tid",
        )
        self.assertEqual(result, "user@test.com")

    def test_dev_valid_withdraw(self):
        result = _validate_market_status_transition(
            user_role="DEV", current_status="pending_review", new_status="not_shared",
            record=self.make_record(), user_id="uid", tenant_id="tid",
        )
        self.assertIsNone(result)

    def test_dev_invalid_transition_raises(self):
        with self.assertRaises(ValueError):
            _validate_market_status_transition(
                user_role="DEV", current_status="shared", new_status="pending_review",
                record=self.make_record(), user_id="uid", tenant_id="tid",
            )

    # --- Unauthorized role ---

    def test_unknown_role_raises(self):
        with self.assertRaises(UnauthorizedError):
            _validate_market_status_transition(
                user_role="USER", current_status="not_shared", new_status="pending_review",
                record=self.make_record(), user_id="uid", tenant_id="tid",
            )


# ============================================================================
# list_community_mcp_services
# ============================================================================

class TestListCommunityMcpServices(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.get_mcp_market_records')
    async def test_list_empty(self, mock_get):
        mock_get.return_value = {"count": 0, "nextCursor": None, "items": []}
        result = await list_community_mcp_services(tenant_id="tid", user_id="uid", limit=30)
        self.assertEqual(result["count"], 0)
        mock_get.assert_called_once_with(
            tenant_id="tid", search=None, tag=None,
            transport_type=None, cursor=None, limit=30,
            user_id="uid", user_group_ids=[],
        )

    @patch('backend.services.mcp_management_service.get_mcp_market_records')
    async def test_list_with_items(self, mock_get):
        mock_get.return_value = {
            "count": 1, "nextCursor": None,
            "items": [MARKET_RECORD],
        }
        result = await list_community_mcp_services(tenant_id="tid", user_id="uid")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["name"], "svc1")
        self.assertEqual(result["items"][0]["marketId"], 1)

    @patch('backend.services.mcp_management_service.get_mcp_market_records')
    async def test_list_with_filters(self, mock_get):
        mock_get.return_value = {"count": 0, "nextCursor": None, "items": []}
        await list_community_mcp_services(
            tenant_id="tid", user_id="uid", search="key", tag="python",
            transport_type="url", cursor="10", limit=20,
        )
        mock_get.assert_called_once_with(
            tenant_id="tid", search="key", tag="python",
            transport_type="url", cursor="10", limit=20,
            user_id="uid", user_group_ids=[],
        )


# ============================================================================
# list_community_mcp_tag_stats
# ============================================================================

    @patch('backend.services.mcp_management_service.query_group_ids_by_user')
    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    @patch('backend.services.mcp_management_service.get_mcp_market_records')
    async def test_list_with_user_group_ids(self, mock_get, mock_tenant, mock_groups):
        """list_community_mcp_services should pass user_group_ids to get_mcp_market_records."""
        mock_tenant.return_value = {"user_role": "DEV"}
        mock_groups.return_value = [2, 4]
        mock_get.return_value = {"count": 0, "nextCursor": None, "items": []}

        result = await list_community_mcp_services(
            tenant_id="tid", user_id="uid", limit=30,
        )
        self.assertEqual(result["count"], 0)
        mock_get.assert_called_once_with(
            tenant_id="tid", search=None, tag=None,
            transport_type=None, cursor=None, limit=30,
            user_id="uid", user_group_ids=[2, 4],
        )

    @patch('backend.services.mcp_management_service.query_group_ids_by_user')
    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    @patch('backend.services.mcp_management_service.get_mcp_market_records')
    async def test_list_handles_group_query_failure(self, mock_get, mock_tenant, mock_groups):
        """list_community_mcp_services should handle query_group_ids_by_user failure gracefully."""
        mock_tenant.return_value = {"user_role": "DEV"}
        mock_get.return_value = {"count": 0, "nextCursor": None, "items": []}

        result = await list_community_mcp_services(
            tenant_id="tid", user_id="uid", limit=30,
        )
        self.assertEqual(result["count"], 0)
        mock_get.assert_called_once_with(
            tenant_id="tid", search=None, tag=None,
            transport_type=None, cursor=None, limit=30,
            user_id="uid", user_group_ids=[],
        )

    @patch('backend.services.mcp_management_service.query_group_ids_by_user')
    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    @patch('backend.services.mcp_management_service.get_mcp_market_records')
    async def test_list_skips_group_filter_for_admin(self, mock_get, mock_tenant, mock_groups):
        """Admin users should skip group filtering (user_id None, user_group_ids None)."""
        mock_tenant.return_value = {"user_role": "ADMIN"}
        mock_get.return_value = {"count": 0, "nextCursor": None, "items": []}

        result = await list_community_mcp_services(
            tenant_id="tid", user_id="uid", limit=30,
        )
        self.assertEqual(result["count"], 0)
        mock_get.assert_called_once_with(
            tenant_id="tid", search=None, tag=None,
            transport_type=None, cursor=None, limit=30,
            user_id=None, user_group_ids=None,
        )


class TestListCommunityMcpTagStats(unittest.TestCase):

    @patch('backend.services.mcp_management_service.get_mcp_market_tag_stats_by_tenant')
    def test_list_tag_stats(self, mock_get):
        mock_get.return_value = [{"tag": "python", "count": 5}]
        result = list_community_mcp_tag_stats(tenant_id="tid")
        self.assertEqual(len(result), 1)
        mock_get.assert_called_once_with(tenant_id="tid")


# ============================================================================
# list_community_mcp_review_services
# ============================================================================

class TestListCommunityMcpReviewServices(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.list_mcp_market_records_by_status')
    @patch('backend.services.mcp_management_service._get_mcp_review_admin_scope')
    async def test_list_reviews(self, mock_scope, mock_list):
        mock_scope.return_value = "tid"
        mock_list.return_value = {
            "count": 1, "nextCursor": None,
            "items": [PENDING_RECORD],
        }
        result = await list_community_mcp_review_services(
            tenant_id="tid", user_id="uid",
        )
        self.assertEqual(result["count"], 1)
        mock_scope.assert_called_once_with("uid", "tid")
        mock_list.assert_called_once()

    @patch('backend.services.mcp_management_service.list_mcp_market_records_by_status')
    @patch('backend.services.mcp_management_service._get_mcp_review_admin_scope')
    async def test_list_reviews_with_filters(self, mock_scope, mock_list):
        mock_scope.return_value = None
        mock_list.return_value = {"count": 0, "nextCursor": None, "items": []}
        await list_community_mcp_review_services(
            tenant_id="tid", user_id="su_uid", status="pending_review",
            search="key", tag="python", transport_type="url",
            cursor="5", limit=10,
        )
        mock_list.assert_called_once_with(
            tenant_id=None, review_status="pending_review", search="key",
            tag="python", transport_type="url", cursor="5", limit=10,
        )


# ============================================================================
# publish_community_mcp_service
# ============================================================================

class TestPublishCommunityMcpService(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.create_mcp_market_record')
    @patch('backend.services.mcp_management_service._resolve_user_email')
    @patch('backend.services.mcp_management_service.check_mcp_market_name_exists')
    @patch('backend.services.mcp_management_service.get_mcp_record_by_id_and_tenant')
    async def test_publish_success(self, mock_get, mock_check, mock_email, mock_create):
        mock_get.return_value = {
            "mcp_id": 1, "mcp_name": "svc", "mcp_server": "http://srv",
            "description": "desc", "tags": ["a"],
            "registry_json": None, "config_json": None,
            "transport_type": "url",
        }
        mock_check.return_value = False
        mock_email.return_value = "user@test.com"
        mock_create.return_value = 42

        market_id = await publish_community_mcp_service(
            tenant_id="tid", user_id="uid", mcp_id=1,
        )
        self.assertEqual(market_id, 42)
        mock_check.assert_called_once_with("svc")

    @patch('backend.services.mcp_management_service.create_mcp_market_record')
    @patch('backend.services.mcp_management_service._resolve_user_email')
    @patch('backend.services.mcp_management_service.check_mcp_market_name_exists')
    @patch('backend.services.mcp_management_service.get_mcp_record_by_id_and_tenant')
    @patch('backend.services.mcp_management_service.update_mcp_record_manage_fields_by_id')
    async def test_publish_with_shared_fields(self, mock_upd, mock_get, mock_check, mock_email, mock_create):
        """Publish should pass shared_fields to create_mcp_market_record and update source MCP."""
        mock_get.return_value = {
            "mcp_id": 1, "mcp_name": "svc", "mcp_server": "http://srv",
            "description": "desc", "tags": ["a"],
            "registry_json": None, "config_json": None,
            "transport_type": "url",
        }
        mock_check.return_value = False
        mock_email.return_value = "user@test.com"
        mock_create.return_value = 7

        shared = {"serverUrl": True, "authorizationToken": False}
        await publish_community_mcp_service(
            tenant_id="tid", user_id="uid", mcp_id=1,
            group_ids=[2, 4],
            ingroup_permission="EDIT",
            shared_fields=shared,
        )

        # Verify shared_fields in market record
        call_data = mock_create.call_args[1]["mcp_data"]
        self.assertEqual(call_data["group_ids"], "2,4")
        self.assertEqual(call_data["ingroup_permission"], "EDIT")
        self.assertEqual(call_data["shared_fields"], shared)

        # Verify shared_fields updated on source MCP record
        mock_upd.assert_called_once()
        upd_kwargs = mock_upd.call_args[1]
        self.assertEqual(upd_kwargs["shared_fields"], shared)

    @patch('backend.services.mcp_management_service.get_mcp_record_by_id_and_tenant')
    async def test_publish_not_found(self, mock_get):
        mock_get.return_value = None
        with self.assertRaises(McpNotFoundError):
            await publish_community_mcp_service(
                tenant_id="tid", user_id="uid", mcp_id=999,
            )

    @patch('backend.services.mcp_management_service.check_mcp_market_name_exists')
    @patch('backend.services.mcp_management_service.get_mcp_record_by_id_and_tenant')
    async def test_publish_name_conflict(self, mock_get, mock_check):
        mock_get.return_value = {
            "mcp_id": 1, "mcp_name": "svc", "mcp_server": "http://srv",
            "description": "desc", "tags": [],
            "registry_json": None, "config_json": None,
            "transport_type": "url",
        }
        mock_check.return_value = True
        with self.assertRaises(McpNameConflictError):
            await publish_community_mcp_service(
                tenant_id="tid", user_id="uid", mcp_id=1,
            )

    @patch('backend.services.mcp_management_service.create_mcp_market_record')
    @patch('backend.services.mcp_management_service._resolve_user_email')
    @patch('backend.services.mcp_management_service.check_mcp_market_name_exists')
    @patch('backend.services.mcp_management_service.get_mcp_record_by_id_and_tenant')
    async def test_publish_with_overrides(self, mock_get, mock_check, mock_email, mock_create):
        mock_get.return_value = {
            "mcp_id": 1, "mcp_name": "svc", "mcp_server": "http://srv",
            "description": "desc", "tags": ["a"],
            "registry_json": None, "config_json": None,
            "transport_type": "url",
        }
        mock_check.return_value = False
        mock_email.return_value = "user@test.com"
        mock_create.return_value = 7

        market_id = await publish_community_mcp_service(
            tenant_id="tid", user_id="uid", mcp_id=1,
            name="override-name", description="override-desc",
            tags=["b"], mcp_server="http://override",
        )
        self.assertEqual(market_id, 7)
        call_data = mock_create.call_args[1]["mcp_data"]
        self.assertEqual(call_data["mcp_name"], "override-name")
        self.assertEqual(call_data["mcp_server"], "http://override")
        self.assertEqual(call_data["review_status"], "pending_review")
        self.assertEqual(call_data["submitted_by"], "user@test.com")


# ============================================================================
# update_community_mcp_service
# ============================================================================

class TestUpdateCommunityMcpService(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.update_mcp_market_status')
    @patch('backend.services.mcp_management_service.update_mcp_market_record')
    @patch('backend.services.mcp_management_service._resolve_user_email')
    @patch('backend.services.mcp_management_service.check_mcp_market_name_exists')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_update_success(self, mock_get, mock_check, mock_email, mock_update_record, mock_update_status):
        mock_get.return_value = {
            "market_id": 1, "mcp_name": "svc",
            "config_json": None, "registry_json": None,
        }
        mock_check.return_value = False
        mock_email.return_value = "user@test.com"
        await update_community_mcp_service(
            tenant_id="tid", user_id="uid", market_id=1,
            name="new-name", description="new-desc", tags=["x"],
            registry_json=None,
        )
        mock_update_record.assert_called_once()
        mock_update_status.assert_called_once_with(
            market_id=1, user_id="uid",
            review_status="pending_review", submitted_by="user@test.com",
        )

    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_update_not_found(self, mock_get):
        mock_get.return_value = None
        with self.assertRaises(McpNotFoundError):
            await update_community_mcp_service(
                tenant_id="tid", user_id="uid", market_id=999,
                name="x", description="d", tags=[], registry_json=None,
            )

    @patch('backend.services.mcp_management_service.check_mcp_market_name_exists')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_update_name_conflict(self, mock_get, mock_check):
        mock_get.return_value = {
            "market_id": 1, "mcp_name": "old-name",
            "config_json": None, "registry_json": None,
        }
        mock_check.return_value = True
        with self.assertRaises(McpNameConflictError):
            await update_community_mcp_service(
                tenant_id="tid", user_id="uid", market_id=1,
                name="taken-name", description="d", tags=[], registry_json=None,
            )

    @patch('backend.services.mcp_management_service.update_mcp_market_status')
    @patch('backend.services.mcp_management_service.update_mcp_market_record')
    @patch('backend.services.mcp_management_service._resolve_user_email')
    @patch('backend.services.mcp_management_service.check_mcp_market_name_exists')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_update_same_name_skips_check(self, mock_get, mock_check, mock_email, mock_update_record, mock_update_status):
        mock_get.return_value = {
            "market_id": 1, "mcp_name": "svc",
            "config_json": None, "registry_json": None,
        }
        await update_community_mcp_service(
            tenant_id="tid", user_id="uid", market_id=1,
            name="svc", description="updated", tags=[], registry_json=None,
        )
        mock_check.assert_not_called()

    @patch('backend.services.mcp_management_service.update_mcp_market_status')
    @patch('backend.services.mcp_management_service.update_mcp_market_record')
    @patch('backend.services.mcp_management_service._resolve_user_email')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    @patch('backend.services.mcp_management_service.update_mcp_record_manage_fields_by_id')
    async def test_update_with_shared_fields(self, mock_upd_mcp, mock_get, mock_email, mock_update_record, mock_update_status):
        """update_community_mcp_service should update shared_fields on source MCP record."""
        mock_get.return_value = {
            "market_id": 1, "mcp_name": "svc", "mcp_server": "http://srv",
            "config_json": None, "registry_json": None,
            "source_mcp_id": 10, "tags": [],
        }
        mock_email.return_value = "user@test.com"

        shared = {"serverUrl": True}
        await update_community_mcp_service(
            tenant_id="tid", user_id="uid", market_id=1,
            name="svc", description="d", tags=[],
            registry_json=None,
            shared_fields=shared,
        )
        mock_upd_mcp.assert_called_once()
        kwargs = mock_upd_mcp.call_args[1]
        self.assertEqual(kwargs["mcp_id"], 10)
        self.assertEqual(kwargs["shared_fields"], shared)

    @patch('backend.services.mcp_management_service.update_mcp_market_status')
    @patch('backend.services.mcp_management_service.update_mcp_market_record')
    @patch('backend.services.mcp_management_service._resolve_user_email')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_update_infers_transport_type(self, mock_get, mock_email, mock_update_record, mock_update_status):
        mock_get.return_value = {
            "market_id": 1, "mcp_name": "svc",
            "config_json": None, "registry_json": None,
        }
        mock_email.return_value = "user@test.com"
        await update_community_mcp_service(
            tenant_id="tid", user_id="uid", market_id=1,
            name="svc", description="d", tags=[],
            registry_json=None, mcp_server="http://new",
        )
        call_data = mock_update_record.call_args[1]
        self.assertEqual(call_data["transport_type"], "url")


# ============================================================================
# change_mcp_market_status (unified status change)
# ============================================================================

class TestChangeMcpMarketStatus(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.update_mcp_record_market_id_by_id')
    @patch('backend.services.mcp_management_service.update_mcp_market_status')
    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_approve_shared(self, mock_get, mock_tenant, mock_status, mock_link_mcp):
        mock_get.return_value = {
            **PENDING_RECORD, "source_mcp_id": 1,
            "tenant_id": "tid", "user_id": "uid",
        }
        mock_tenant.return_value = {"user_role": "ADMIN"}
        await change_mcp_market_status(
            tenant_id="tid", user_id="admin_uid",
            market_id=2, new_status="shared",
        )
        mock_status.assert_called_once_with(
            market_id=2, user_id="admin_uid",
            review_status="shared", submitted_by=None,
        )
        mock_link_mcp.assert_called_once_with(
            mcp_id=1, tenant_id="tid", user_id="uid", market_id=2,
        )

    @patch('backend.services.mcp_management_service.update_mcp_market_status')
    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_reject(self, mock_get, mock_tenant, mock_status):
        mock_get.return_value = PENDING_RECORD
        mock_tenant.return_value = {"user_role": "ADMIN"}
        await change_mcp_market_status(
            tenant_id="tid", user_id="admin_uid",
            market_id=2, new_status="rejected",
        )
        mock_status.assert_called_once_with(
            market_id=2, user_id="admin_uid",
            review_status="rejected", submitted_by=None,
        )

    @patch('backend.services.mcp_management_service.update_mcp_market_status')
    @patch('backend.services.mcp_management_service._resolve_user_email')
    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_submit_for_review(self, mock_get, mock_tenant, mock_email, mock_status):
        mock_get.return_value = {**MARKET_RECORD, "review_status": "not_shared"}
        mock_tenant.return_value = {"user_role": "DEV"}
        mock_email.return_value = "user@test.com"
        await change_mcp_market_status(
            tenant_id="tid", user_id="uid",
            market_id=1, new_status="pending_review",
        )
        mock_status.assert_called_once_with(
            market_id=1, user_id="uid",
            review_status="pending_review", submitted_by="user@test.com",
        )

    @patch('backend.services.mcp_management_service.update_mcp_market_status')
    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_withdraw(self, mock_get, mock_tenant, mock_status):
        mock_get.return_value = PENDING_RECORD
        mock_tenant.return_value = {"user_role": "DEV"}
        await change_mcp_market_status(
            tenant_id="tid", user_id="uid",
            market_id=2, new_status="not_shared",
        )
        mock_status.assert_called_once_with(
            market_id=2, user_id="uid",
            review_status="not_shared", submitted_by=None,
        )

    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_not_found(self, mock_get, mock_tenant):
        mock_get.return_value = None
        with self.assertRaises(McpNotFoundError):
            await change_mcp_market_status(
                tenant_id="tid", user_id="uid",
                market_id=999, new_status="shared",
            )

    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_invalid_transition(self, mock_get, mock_tenant):
        mock_get.return_value = {**MARKET_RECORD, "review_status": "not_shared",
                                  "tenant_id": "tid", "user_id": "uid"}
        mock_tenant.return_value = {"user_role": "DEV"}
        with self.assertRaises(ValueError):
            await change_mcp_market_status(
                tenant_id="tid", user_id="uid",
                market_id=1, new_status="shared",
            )


# ============================================================================
# approve_community_mcp_service (legacy wrapper)
# ============================================================================

class TestApproveCommunityMcpService(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.change_mcp_market_status')
    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    async def test_approve_legacy(self, mock_tenant, mock_change):
        mock_tenant.return_value = {"user_role": "ADMIN"}
        await approve_community_mcp_service(
            tenant_id="tid", user_id="admin_uid", market_id=10,
        )
        mock_change.assert_called_once_with(
            tenant_id="tid", user_id="admin_uid",
            market_id=10, new_status="shared",
        )

    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    async def test_approve_unauthorized(self, mock_tenant):
        mock_tenant.return_value = {"user_role": "DEV"}
        with self.assertRaises(UnauthorizedError):
            await approve_community_mcp_service(
                tenant_id="tid", user_id="uid", market_id=10,
            )


# ============================================================================
# reject_community_mcp_service (legacy wrapper)
# ============================================================================

class TestRejectCommunityMcpService(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.change_mcp_market_status')
    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    async def test_reject_legacy(self, mock_tenant, mock_change):
        mock_tenant.return_value = {"user_role": "ADMIN"}
        await reject_community_mcp_service(
            tenant_id="tid", user_id="admin_uid", market_id=10,
        )
        mock_change.assert_called_once_with(
            tenant_id="tid", user_id="admin_uid",
            market_id=10, new_status="rejected",
        )

    @patch('backend.services.mcp_management_service.get_user_tenant_by_user_id')
    async def test_reject_unauthorized(self, mock_tenant):
        mock_tenant.return_value = {"user_role": "DEV"}
        with self.assertRaises(UnauthorizedError):
            await reject_community_mcp_service(
                tenant_id="tid", user_id="uid", market_id=10,
            )


# ============================================================================
# delete_community_mcp_service
# ============================================================================

class TestDeleteCommunityMcpService(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.clear_mcp_record_market_id')
    @patch('backend.services.mcp_management_service.delete_mcp_market_record_by_id')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_delete_success(self, mock_get, mock_delete, mock_clear):
        mock_get.return_value = {"market_id": 1, "tenant_id": "tid"}
        await delete_community_mcp_service(
            tenant_id="tid", user_id="uid", market_id=1,
        )
        mock_delete.assert_called_once_with(market_id=1, user_id="uid")
        mock_clear.assert_called_once_with(
            tenant_id="tid", user_id="uid", market_id=1,
        )

    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_delete_not_found(self, mock_get):
        mock_get.return_value = None
        with self.assertRaises(McpNotFoundError):
            await delete_community_mcp_service(
                tenant_id="tid", user_id="uid", market_id=999,
            )


# ============================================================================
# list_my_community_mcp_services
# ============================================================================

class TestListMyCommunityMcpServices(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.list_mcp_market_records_by_tenant_and_user')
    async def test_list_my_services(self, mock_market):
        mock_market.return_value = [MARKET_RECORD]
        result = await list_my_community_mcp_services(
            tenant_id="tid", user_id="uid",
        )
        self.assertEqual(result["count"], 1)
        mock_market.assert_called_once_with(tenant_id="tid", user_id="uid")

    @patch('backend.services.mcp_management_service.list_mcp_market_records_by_tenant_and_user')
    async def test_list_my_services_multiple_statuses(self, mock_market):
        mock_market.return_value = [MARKET_RECORD, PENDING_RECORD]
        result = await list_my_community_mcp_services(
            tenant_id="tid", user_id="uid",
        )
        self.assertEqual(result["count"], 2)
        statuses = {item["reviewStatus"] for item in result["items"]}
        self.assertEqual(statuses, {"approved", "pending"})
