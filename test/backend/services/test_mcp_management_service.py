"""
Unit tests for backend/services/mcp_management_service.py
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
sys.modules['boto3'] = MagicMock()
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

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
patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
      return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

from consts.exceptions import McpNotFoundError, McpNameConflictError, UnauthorizedError

from backend.services.mcp_management_service import (
    _to_community_card,
    _get_mcp_review_admin_scope,
    _resolve_author_display_name,
    list_community_mcp_services,
    list_community_mcp_tag_stats,
    list_community_mcp_review_services,
    publish_community_mcp_service,
    update_community_mcp_service,
    approve_community_mcp_service,
    reject_community_mcp_service,
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
    "review_status": "approved",
    "review_type": "initial_listing",
    "download_count": 5,
    "source_mcp_id": None,
    "create_time": "t1",
    "update_time": "t2",
}

REVIEW_RECORD = {
    "review_id": 10,
    "market_id": None,
    "tenant_id": "tid",
    "user_id": "uid",
    "mcp_name": "new-svc",
    "mcp_server": "http://new",
    "description": "new desc",
    "transport_type": "url",
    "config_json": None,
    "registry_json": None,
    "tags": ["b"],
    "review_status": "pending",
    "review_type": "initial_listing",
    "source_mcp_id": 1,
    "create_time": "t1",
    "update_time": "t2",
}


# ============================================================================
# Helper / utility function tests
# ============================================================================

class TestToCommunityCard(unittest.TestCase):
    """Test _to_community_card transforms a DB row to the API response shape."""

    def test_market_record(self):
        card = _to_community_card(MARKET_RECORD)
        self.assertEqual(card["marketId"], 1)
        self.assertEqual(card["communityId"], 1)
        self.assertEqual(card["name"], "svc1")
        self.assertEqual(card["reviewStatus"], "approved")
        self.assertEqual(card["installCount"], 5)

    def test_review_record_no_market_id(self):
        card = _to_community_card(REVIEW_RECORD)
        self.assertIsNone(card["marketId"])
        self.assertEqual(card["reviewId"], 10)
        self.assertEqual(card["communityId"], 10)
        self.assertEqual(card["reviewStatus"], "pending")

    def test_review_record_with_market_id(self):
        row = {**REVIEW_RECORD, "market_id": 2}
        card = _to_community_card(row)
        self.assertEqual(card["marketId"], 2)
        self.assertEqual(card["communityId"], 2)

    def test_minimal_row_defaults(self):
        card = _to_community_card({})
        self.assertIsNone(card["marketId"])
        self.assertEqual(card["tags"], [])
        self.assertEqual(card["installCount"], 0)
        self.assertEqual(card["reviewStatus"], "approved")
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
# list_community_mcp_services
# ============================================================================

class TestListCommunityMcpServices(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.get_mcp_market_records')
    async def test_list_empty(self, mock_get):
        mock_get.return_value = {"count": 0, "nextCursor": None, "items": []}
        result = await list_community_mcp_services(tenant_id="tid", limit=30)
        self.assertEqual(result["count"], 0)
        mock_get.assert_called_once_with(
            tenant_id="tid", search=None, tag=None,
            transport_type=None, cursor=None, limit=30,
        )

    @patch('backend.services.mcp_management_service.get_mcp_market_records')
    async def test_list_with_items(self, mock_get):
        mock_get.return_value = {
            "count": 1, "nextCursor": None,
            "items": [MARKET_RECORD],
        }
        result = await list_community_mcp_services(tenant_id="tid")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["name"], "svc1")
        self.assertEqual(result["items"][0]["marketId"], 1)

    @patch('backend.services.mcp_management_service.get_mcp_market_records')
    async def test_list_with_filters(self, mock_get):
        mock_get.return_value = {"count": 0, "nextCursor": None, "items": []}
        await list_community_mcp_services(
            tenant_id="tid", search="key", tag="python",
            transport_type="url", cursor="10", limit=20,
        )
        mock_get.assert_called_once_with(
            tenant_id="tid", search="key", tag="python",
            transport_type="url", cursor="10", limit=20,
        )


# ============================================================================
# list_community_mcp_tag_stats
# ============================================================================

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

    @patch('backend.services.mcp_management_service.list_mcp_market_review_records')
    @patch('backend.services.mcp_management_service._get_mcp_review_admin_scope')
    async def test_list_reviews(self, mock_scope, mock_list):
        mock_scope.return_value = "tid"
        mock_list.return_value = {
            "count": 1, "nextCursor": None,
            "items": [REVIEW_RECORD],
        }
        result = await list_community_mcp_review_services(
            tenant_id="tid", user_id="uid", status="pending",
        )
        self.assertEqual(result["count"], 1)
        mock_scope.assert_called_once_with("uid", "tid")
        mock_list.assert_called_once()

    @patch('backend.services.mcp_management_service.list_mcp_market_review_records')
    @patch('backend.services.mcp_management_service._get_mcp_review_admin_scope')
    async def test_list_reviews_with_filters(self, mock_scope, mock_list):
        mock_scope.return_value = None
        mock_list.return_value = {"count": 0, "nextCursor": None, "items": []}
        await list_community_mcp_review_services(
            tenant_id="tid", user_id="su_uid", status="approved",
            search="key", tag="python", transport_type="url",
            cursor="5", limit=10,
        )
        mock_list.assert_called_once_with(
            tenant_id=None, status="approved", search="key",
            tag="python", transport_type="url", cursor="5", limit=10,
        )


# ============================================================================
# publish_community_mcp_service
# ============================================================================

class TestPublishCommunityMcpService(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.create_mcp_market_review')
    @patch('backend.services.mcp_management_service.check_mcp_market_name_exists')
    @patch('backend.services.mcp_management_service.get_mcp_record_by_id_and_tenant')
    async def test_publish_success(self, mock_get, mock_check, mock_create):
        mock_get.return_value = {
            "mcp_id": 1, "mcp_name": "svc", "mcp_server": "http://srv",
            "description": "desc", "tags": ["a"],
            "registry_json": None, "config_json": None,
            "transport_type": "url",
        }
        mock_check.return_value = False
        mock_create.return_value = 42

        review_id = await publish_community_mcp_service(
            tenant_id="tid", user_id="uid", mcp_id=1,
        )
        self.assertEqual(review_id, 42)
        mock_check.assert_called_once_with("svc")

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

    @patch('backend.services.mcp_management_service.create_mcp_market_review')
    @patch('backend.services.mcp_management_service.check_mcp_market_name_exists')
    @patch('backend.services.mcp_management_service.get_mcp_record_by_id_and_tenant')
    async def test_publish_with_overrides(self, mock_get, mock_check, mock_create):
        mock_get.return_value = {
            "mcp_id": 1, "mcp_name": "svc", "mcp_server": "http://srv",
            "description": "desc", "tags": ["a"],
            "registry_json": None, "config_json": None,
            "transport_type": "url",
        }
        mock_check.return_value = False
        mock_create.return_value = 7

        review_id = await publish_community_mcp_service(
            tenant_id="tid", user_id="uid", mcp_id=1,
            name="override-name", description="override-desc",
            tags=["b"], mcp_server="http://override",
        )
        self.assertEqual(review_id, 7)
        call_data = mock_create.call_args[1]["mcp_data"]
        self.assertEqual(call_data["mcp_name"], "override-name")
        self.assertEqual(call_data["mcp_server"], "http://override")


# ============================================================================
# update_community_mcp_service
# ============================================================================

class TestUpdateCommunityMcpService(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.create_mcp_market_review')
    @patch('backend.services.mcp_management_service.check_mcp_market_name_exists')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_update_success(self, mock_get, mock_check, mock_create):
        mock_get.return_value = {
            "market_id": 1, "mcp_name": "svc",
            "config_json": None, "registry_json": None,
        }
        mock_check.return_value = False
        await update_community_mcp_service(
            tenant_id="tid", user_id="uid", market_id=1,
            name="new-name", description="new-desc", tags=["x"],
            registry_json=None,
        )
        mock_create.assert_called_once()
        call_data = mock_create.call_args[1]["mcp_data"]
        self.assertEqual(call_data["review_type"], "update")
        self.assertEqual(call_data["mcp_name"], "new-name")

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

    @patch('backend.services.mcp_management_service.create_mcp_market_review')
    @patch('backend.services.mcp_management_service.check_mcp_market_name_exists')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_update_same_name_skips_check(self, mock_get, mock_check, mock_create):
        mock_get.return_value = {
            "market_id": 1, "mcp_name": "svc",
            "config_json": None, "registry_json": None,
        }
        await update_community_mcp_service(
            tenant_id="tid", user_id="uid", market_id=1,
            name="svc", description="updated", tags=[], registry_json=None,
        )
        mock_check.assert_not_called()

    @patch('backend.services.mcp_management_service.create_mcp_market_review')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_update_infers_transport_type(self, mock_get, mock_create):
        mock_get.return_value = {
            "market_id": 1, "mcp_name": "svc",
            "config_json": None, "registry_json": None,
        }
        await update_community_mcp_service(
            tenant_id="tid", user_id="uid", market_id=1,
            name="svc", description="d", tags=[],
            registry_json=None, mcp_server="http://new",
        )
        call_data = mock_create.call_args[1]["mcp_data"]
        self.assertEqual(call_data["transport_type"], "url")


# ============================================================================
# approve_community_mcp_service
# ============================================================================

class TestApproveCommunityMcpService(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.update_mcp_record_market_id_by_id')
    @patch('backend.services.mcp_management_service.update_mcp_market_review_market_id')
    @patch('backend.services.mcp_management_service.create_mcp_market_record')
    @patch('backend.services.mcp_management_service.get_mcp_market_review_by_id')
    @patch('backend.services.mcp_management_service._get_mcp_review_admin_scope')
    @patch('backend.services.mcp_management_service.update_mcp_market_review_status')
    async def test_approve_initial_listing(
        self, mock_status, mock_scope, mock_get_review,
        mock_create, mock_link, mock_link_mcp,
    ):
        mock_scope.return_value = "tid"
        mock_get_review.return_value = {
            **REVIEW_RECORD,
            "market_id": None,
            "tenant_id": "tid",
            "user_id": "uid",
            "source_mcp_id": 1,
        }
        mock_create.return_value = 100

        await approve_community_mcp_service(
            tenant_id="tid", user_id="admin_uid", review_id=10,
        )

        mock_create.assert_called_once()
        mock_link.assert_called_once_with(
            review_id=10, market_id=100, user_id="admin_uid",
        )
        mock_link_mcp.assert_called_once_with(
            mcp_id=1, tenant_id="tid", user_id="uid", market_id=100,
        )
        mock_status.assert_called_once()

    @patch('backend.services.mcp_management_service.update_mcp_market_record')
    @patch('backend.services.mcp_management_service.get_mcp_market_review_by_id')
    @patch('backend.services.mcp_management_service._get_mcp_review_admin_scope')
    @patch('backend.services.mcp_management_service.update_mcp_market_review_status')
    async def test_approve_update(
        self, mock_status, mock_scope, mock_get_review, mock_update,
    ):
        mock_scope.return_value = "tid"
        mock_get_review.return_value = {
            **REVIEW_RECORD,
            "market_id": 5,
            "mcp_name": "updated-name",
            "description": "updated-desc",
        }

        await approve_community_mcp_service(
            tenant_id="tid", user_id="admin_uid", review_id=10,
        )

        mock_update.assert_called_once()
        call_data = mock_update.call_args[1]
        self.assertEqual(call_data["market_id"], 5)
        mock_status.assert_called_once()

    @patch('backend.services.mcp_management_service.get_mcp_market_review_by_id')
    @patch('backend.services.mcp_management_service._get_mcp_review_admin_scope')
    async def test_approve_not_found(self, mock_scope, mock_get):
        mock_scope.return_value = "tid"
        mock_get.return_value = None
        with self.assertRaises(McpNotFoundError):
            await approve_community_mcp_service(
                tenant_id="tid", user_id="uid", review_id=999,
            )


# ============================================================================
# reject_community_mcp_service
# ============================================================================

class TestRejectCommunityMcpService(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.update_mcp_market_review_status')
    @patch('backend.services.mcp_management_service.get_mcp_market_review_by_id')
    @patch('backend.services.mcp_management_service._get_mcp_review_admin_scope')
    async def test_reject_success(self, mock_scope, mock_get, mock_status):
        mock_scope.return_value = "tid"
        mock_get.return_value = {"review_id": 10, "tenant_id": "tid"}
        await reject_community_mcp_service(
            tenant_id="tid", user_id="admin_uid", review_id=10,
        )
        mock_status.assert_called_once_with(
            review_id=10, tenant_id="tid", user_id="admin_uid",
            review_status="rejected",
        )

    @patch('backend.services.mcp_management_service.get_mcp_market_review_by_id')
    @patch('backend.services.mcp_management_service._get_mcp_review_admin_scope')
    async def test_reject_not_found(self, mock_scope, mock_get):
        mock_scope.return_value = "tid"
        mock_get.return_value = None
        with self.assertRaises(McpNotFoundError):
            await reject_community_mcp_service(
                tenant_id="tid", user_id="uid", review_id=999,
            )


# ============================================================================
# delete_community_mcp_service
# ============================================================================

class TestDeleteCommunityMcpService(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.clear_mcp_record_market_id')
    @patch('backend.services.mcp_management_service.list_mcp_market_review_records_by_market_id')
    @patch('backend.services.mcp_management_service.delete_mcp_market_record_by_id')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_delete_market_record(
        self, mock_get, mock_delete, mock_list_reviews, mock_clear,
    ):
        mock_get.return_value = {"market_id": 1}
        mock_list_reviews.return_value = [
            {"review_id": 10},
            {"review_id": 11},
        ]
        await delete_community_mcp_service(
            tenant_id="tid", user_id="uid", market_id=1,
        )
        mock_delete.assert_called_once_with(market_id=1, user_id="uid")

    @patch('backend.services.mcp_management_service.update_mcp_market_review_status')
    @patch('backend.services.mcp_management_service.get_mcp_market_review_by_id')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_delete_review_only(self, mock_get_market, mock_get_review, mock_status):
        mock_get_market.return_value = None
        mock_get_review.return_value = {"review_id": 10}
        await delete_community_mcp_service(
            tenant_id="tid", user_id="uid", market_id=10,
        )
        mock_status.assert_called_once_with(
            review_id=10, tenant_id=None, user_id="uid",
            review_status="rejected",
        )

    @patch('backend.services.mcp_management_service.get_mcp_market_review_by_id')
    @patch('backend.services.mcp_management_service.get_mcp_market_record_by_id')
    async def test_delete_not_found(self, mock_get_market, mock_get_review):
        mock_get_market.return_value = None
        mock_get_review.return_value = None
        with self.assertRaises(McpNotFoundError):
            await delete_community_mcp_service(
                tenant_id="tid", user_id="uid", market_id=999,
            )


# ============================================================================
# list_my_community_mcp_services
# ============================================================================

class TestListMyCommunityMcpServices(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.list_mcp_market_review_records_by_tenant_and_user')
    @patch('backend.services.mcp_management_service.list_mcp_market_records_by_tenant_and_user')
    async def test_list_my_services(self, mock_market, mock_review):
        mock_market.return_value = [MARKET_RECORD]
        mock_review.return_value = []
        result = await list_my_community_mcp_services(
            tenant_id="tid", user_id="uid",
        )
        self.assertEqual(result["count"], 1)
        mock_market.assert_called_once_with(tenant_id="tid", user_id="uid")
        mock_review.assert_called_once_with(
            tenant_id="tid", user_id="uid", include_approved=True,
        )

    @patch('backend.services.mcp_management_service.list_mcp_market_review_records_by_tenant_and_user')
    @patch('backend.services.mcp_management_service.list_mcp_market_records_by_tenant_and_user')
    async def test_list_my_includes_active_reviews(self, mock_market, mock_review):
        mock_market.return_value = []
        mock_review.return_value = [
            {**REVIEW_RECORD, "review_status": "pending"},
        ]
        result = await list_my_community_mcp_services(
            tenant_id="tid", user_id="uid",
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["reviewStatus"], "pending")


# ============================================================================
# list_registry_mcp_services
# ============================================================================

class TestListRegistryMcpServices(unittest.IsolatedAsyncioTestCase):

    @patch('backend.services.mcp_management_service.aiohttp.ClientSession')
    async def test_list_success(self, mock_session_cls):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"servers": [{"name": "s1"}], "metadata": {}}
        )
        mock_response.__aenter__.return_value = mock_response

        mock_session = MagicMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session_cls.return_value = mock_session

        result = await list_registry_mcp_services()
        self.assertEqual(len(result["servers"]), 1)

    @patch('backend.services.mcp_management_service.aiohttp.ClientSession')
    async def test_list_error(self, mock_session_cls):
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.__aenter__.return_value = mock_response

        mock_session = MagicMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session_cls.return_value = mock_session

        with self.assertRaises(RuntimeError):
            await list_registry_mcp_services()


if __name__ == '__main__':
    unittest.main()
