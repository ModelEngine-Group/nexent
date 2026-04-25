import sys
import os
import unittest
from unittest.mock import MagicMock

test_dir = os.path.dirname(__file__)
backend_dir = os.path.abspath(os.path.join(test_dir, "../../../backend"))
sys.path.insert(0, backend_dir)

consts_mock = MagicMock()
consts_mock.const = MagicMock()
consts_mock.const.MINIO_ENDPOINT = "http://localhost:9000"
consts_mock.const.MINIO_ACCESS_KEY = "test"
consts_mock.const.MINIO_SECRET_KEY = "test"
consts_mock.const.MINIO_REGION = "us-east-1"
consts_mock.const.MINIO_DEFAULT_BUCKET = "test"
consts_mock.const.POSTGRES_HOST = "localhost"
consts_mock.const.POSTGRES_USER = "test"
consts_mock.const.NEXENT_POSTGRES_PASSWORD = "test"
consts_mock.const.POSTGRES_DB = "test"
consts_mock.const.POSTGRES_PORT = 5432
consts_mock.const.DEFAULT_TENANT_ID = "default-tenant"
sys.modules["consts"] = consts_mock
sys.modules["consts.const"] = consts_mock.const

sys.modules["consts.exceptions"] = MagicMock()
sys.modules["boto3"] = MagicMock()

sqlalchemy_mock = MagicMock()
sys.modules["sqlalchemy"] = sqlalchemy_mock
sys.modules["sqlalchemy.exc"] = sqlalchemy_mock.exc
sys.modules["sqlalchemy.orm"] = MagicMock()
sys.modules["sqlalchemy.dialects"] = MagicMock()
sys.modules["sqlalchemy.dialects.postgresql"] = MagicMock()

mock_get_db_session = MagicMock()
mock_as_dict = MagicMock()

client_mock = MagicMock()
client_mock.get_db_session = mock_get_db_session
client_mock.as_dict = mock_as_dict
client_mock.MinioClient = MagicMock()
client_mock.PostgresClient = MagicMock()
client_mock.db_client = MagicMock()
client_mock.filter_property = MagicMock()
sys.modules["database.client"] = client_mock

db_models_mock = MagicMock()
db_models_mock.UserOAuthAccount = MagicMock()
db_models_mock.TableBase = MagicMock()
sys.modules["database.db_models"] = db_models_mock

from database.oauth_account_db import (
    count_oauth_accounts_by_user_id,
    delete_oauth_account,
    get_oauth_account_by_provider,
    get_soft_deleted_oauth_account,
    insert_oauth_account,
    list_oauth_accounts_by_user_id,
    reactivate_oauth_account,
    rebind_oauth_account,
    soft_delete_all_oauth_accounts_by_user_id,
    update_oauth_account_tokens,
)


def _make_mock_session():
    session = MagicMock()
    query_mock = MagicMock()
    filter_mock = MagicMock()
    session.query.return_value = query_mock
    query_mock.filter.return_value = filter_mock
    
    mock_get_db_session.return_value.__enter__ = MagicMock(return_value=session)
    mock_get_db_session.return_value.__exit__ = MagicMock(return_value=False)
    return session, query_mock, filter_mock


class TestInsertOAuthAccount(unittest.TestCase):
    def test_insert_and_return_dict(self):
        session, query, filter_mock = _make_mock_session()
        mock_account = MagicMock()
        session.add = MagicMock()
        session.flush = MagicMock()
        client_mock.as_dict.return_value = {
            "provider": "github",
            "provider_user_id": "12345",
            "user_id": "user-1",
        }

        result = insert_oauth_account(
            user_id="user-1",
            provider="github",
            provider_user_id="12345",
            provider_email="test@github.com",
        )

        session.add.assert_called_once()
        session.flush.assert_called_once()
        self.assertEqual(result["provider"], "github")


class TestGetOAuthAccountByProvider(unittest.TestCase):
    def test_returns_dict_when_found(self):
        session, query, filter_mock = _make_mock_session()
        mock_account = MagicMock()
        filter_mock.first.return_value = mock_account
        client_mock.as_dict.return_value = {
            "provider": "github",
            "provider_user_id": "12345",
        }

        result = get_oauth_account_by_provider("github", "12345")

        self.assertIsNotNone(result)
        self.assertEqual(result["provider"], "github")

    def test_returns_none_when_not_found(self):
        session, query, filter_mock = _make_mock_session()
        filter_mock.first.return_value = None

        result = get_oauth_account_by_provider("github", "nonexistent")

        self.assertIsNone(result)


class TestListOAuthAccountsByUserId(unittest.TestCase):
    def test_returns_list_of_dicts(self):
        session, query, filter_mock = _make_mock_session()
        mock_account = MagicMock()
        filter_mock.all.return_value = [mock_account]
        client_mock.as_dict.return_value = {"provider": "github", "user_id": "user-1"}

        result = list_oauth_accounts_by_user_id("user-1")

        self.assertEqual(len(result), 1)

    def test_returns_empty_list(self):
        session, query, filter_mock = _make_mock_session()
        filter_mock.all.return_value = []

        result = list_oauth_accounts_by_user_id("user-1")

        self.assertEqual(len(result), 0)


class TestUpdateOAuthAccountTokens(unittest.TestCase):
    def test_updates_and_returns_true(self):
        session, query, filter_mock = _make_mock_session()
        mock_account = MagicMock()
        filter_mock.first.return_value = mock_account

        result = update_oauth_account_tokens(
            provider="github",
            provider_user_id="12345",
            provider_username="new_name",
        )

        self.assertTrue(result)
        self.assertEqual(mock_account.provider_username, "new_name")

    def test_returns_false_when_not_found(self):
        session, query, filter_mock = _make_mock_session()
        filter_mock.first.return_value = None

        result = update_oauth_account_tokens("github", "nonexistent")

        self.assertFalse(result)

    def test_skips_none_fields(self):
        session, query, filter_mock = _make_mock_session()
        mock_account = MagicMock()
        filter_mock.first.return_value = mock_account

        update_oauth_account_tokens("github", "12345")


class TestDeleteOAuthAccount(unittest.TestCase):
    def test_soft_deletes_and_returns_true(self):
        session, query, filter_mock = _make_mock_session()
        mock_account = MagicMock()
        filter_mock.first.return_value = mock_account

        result = delete_oauth_account("user-1", "github")

        self.assertTrue(result)
        self.assertEqual(mock_account.delete_flag, "Y")

    def test_returns_false_when_not_found(self):
        session, query, filter_mock = _make_mock_session()
        filter_mock.first.return_value = None

        result = delete_oauth_account("user-1", "github")

        self.assertFalse(result)


class TestReactivateOAuthAccount(unittest.TestCase):
    def test_reactivates_and_returns_true(self):
        session, query, filter_mock = _make_mock_session()
        mock_account = MagicMock()
        mock_account.delete_flag = "Y"
        filter_mock.first.return_value = mock_account

        result = reactivate_oauth_account(
            provider="github",
            provider_user_id="12345",
            user_id="user-2",
            provider_email="new@email.com",
            provider_username="newname",
        )

        self.assertTrue(result)
        self.assertEqual(mock_account.delete_flag, "N")
        self.assertEqual(mock_account.user_id, "user-2")

    def test_returns_false_when_not_found(self):
        session, query, filter_mock = _make_mock_session()
        filter_mock.first.return_value = None

        result = reactivate_oauth_account("github", "12345", "user-1")

        self.assertFalse(result)


class TestCountOAuthAccountsByUserId(unittest.TestCase):
    def test_returns_correct_count(self):
        session, query, filter_mock = _make_mock_session()
        filter_mock.count.return_value = 3

        result = count_oauth_accounts_by_user_id("user-1")

        self.assertEqual(result, 3)

    def test_returns_zero_when_no_accounts(self):
        session, query, filter_mock = _make_mock_session()
        filter_mock.count.return_value = 0

        result = count_oauth_accounts_by_user_id("user-1")

        self.assertEqual(result, 0)


class TestGetSoftDeletedOAuthAccount(unittest.TestCase):
    def test_returns_dict_when_soft_deleted_found(self):
        session, query, filter_mock = _make_mock_session()
        mock_account = MagicMock()
        mock_account.delete_flag = "Y"
        filter_mock.first.return_value = mock_account
        client_mock.as_dict.return_value = {
            "provider": "github",
            "provider_user_id": "12345",
            "user_id": "user-1",
            "delete_flag": "Y",
        }

        result = get_soft_deleted_oauth_account("github", "12345")

        self.assertIsNotNone(result)
        self.assertEqual(result["delete_flag"], "Y")
        self.assertEqual(result["provider"], "github")

    def test_returns_none_when_not_soft_deleted(self):
        session, query, filter_mock = _make_mock_session()
        filter_mock.first.return_value = None

        result = get_soft_deleted_oauth_account("github", "12345")

        self.assertIsNone(result)

    def test_returns_none_when_not_found(self):
        session, query, filter_mock = _make_mock_session()
        filter_mock.first.return_value = None

        result = get_soft_deleted_oauth_account("github", "nonexistent")

        self.assertIsNone(result)


class TestRebindOAuthAccount(unittest.TestCase):
    def test_rebinds_to_new_user(self):
        session, query, filter_mock = _make_mock_session()
        mock_account = MagicMock()
        mock_account.delete_flag = "N"
        filter_mock.first.return_value = mock_account
        client_mock.as_dict.return_value = {
            "provider": "github",
            "provider_user_id": "12345",
            "user_id": "new-user",
        }

        result = rebind_oauth_account(
            provider="github",
            provider_user_id="12345",
            new_user_id="new-user",
            provider_email="new@email.com",
            provider_username="newname",
        )

        self.assertTrue(result)
        self.assertEqual(mock_account.user_id, "new-user")
        self.assertEqual(mock_account.provider_email, "new@email.com")
        self.assertEqual(mock_account.provider_username, "newname")
        self.assertEqual(mock_account.updated_by, "new-user")

    def test_rebinds_keeps_existing_email_when_none_provided(self):
        session, query, filter_mock = _make_mock_session()
        mock_account = MagicMock()
        mock_account.delete_flag = "N"
        mock_account.provider_email = "existing@email.com"
        mock_account.provider_username = "existingname"
        filter_mock.first.return_value = mock_account
        client_mock.as_dict.return_value = {"provider": "github", "user_id": "new-user"}

        result = rebind_oauth_account(
            provider="github",
            provider_user_id="12345",
            new_user_id="new-user",
        )

        self.assertTrue(result)
        self.assertEqual(mock_account.provider_email, "existing@email.com")

    def test_returns_false_when_not_found(self):
        session, query, filter_mock = _make_mock_session()
        filter_mock.first.return_value = None

        result = rebind_oauth_account("github", "nonexistent", "new-user")

        self.assertFalse(result)


class TestSoftDeleteAllOAuthAccountsByUserId(unittest.TestCase):
    def test_soft_deletes_all_accounts(self):
        session, query, filter_mock = _make_mock_session()
        mock_account1 = MagicMock()
        mock_account1.delete_flag = "N"
        mock_account2 = MagicMock()
        mock_account2.delete_flag = "N"
        filter_mock.all.return_value = [mock_account1, mock_account2]

        result = soft_delete_all_oauth_accounts_by_user_id("user-1", deleted_by="admin")

        self.assertEqual(result, 2)
        self.assertEqual(mock_account1.delete_flag, "Y")
        self.assertEqual(mock_account2.delete_flag, "Y")
        self.assertEqual(mock_account1.updated_by, "admin")
        self.assertEqual(mock_account2.updated_by, "admin")

    def test_returns_zero_when_no_accounts(self):
        session, query, filter_mock = _make_mock_session()
        filter_mock.all.return_value = []

        result = soft_delete_all_oauth_accounts_by_user_id("user-1", "admin")

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
