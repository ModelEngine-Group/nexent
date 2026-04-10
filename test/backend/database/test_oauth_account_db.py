import sys
import os
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

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
    get_oauth_account_by_provider,
    insert_oauth_account,
    list_oauth_accounts_by_user_id,
    soft_delete_oauth_account,
    update_oauth_account_tokens,
)


def _make_mock_session():
    session = MagicMock()
    mock_get_db_session.return_value.__enter__ = MagicMock(return_value=session)
    mock_get_db_session.return_value.__exit__ = MagicMock(return_value=False)
    return session


class TestInsertOAuthAccount(unittest.TestCase):
    def test_insert_and_return_dict(self):
        mock_session = _make_mock_session()
        mock_account = MagicMock()
        mock_session.add = MagicMock()
        mock_session.flush = MagicMock()
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

        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()
        self.assertEqual(result["provider"], "github")


class TestGetOAuthAccountByProvider(unittest.TestCase):
    def test_returns_dict_when_found(self):
        mock_session = _make_mock_session()
        mock_account = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_account
        )
        client_mock.as_dict.return_value = {
            "provider": "github",
            "provider_user_id": "12345",
        }

        result = get_oauth_account_by_provider("github", "12345")

        self.assertIsNotNone(result)
        self.assertEqual(result["provider"], "github")

    def test_returns_none_when_not_found(self):
        mock_session = _make_mock_session()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = get_oauth_account_by_provider("github", "nonexistent")

        self.assertIsNone(result)


class TestListOAuthAccountsByUserId(unittest.TestCase):
    def test_returns_list_of_dicts(self):
        mock_session = _make_mock_session()
        mock_account = MagicMock()
        mock_session.query.return_value.filter.return_value.all.return_value = [
            mock_account
        ]
        client_mock.as_dict.return_value = {"provider": "github", "user_id": "user-1"}

        result = list_oauth_accounts_by_user_id("user-1")

        self.assertEqual(len(result), 1)

    def test_returns_empty_list(self):
        mock_session = _make_mock_session()
        mock_session.query.return_value.filter.return_value.all.return_value = []

        result = list_oauth_accounts_by_user_id("user-1")

        self.assertEqual(len(result), 0)


class TestUpdateOAuthAccountTokens(unittest.TestCase):
    def test_updates_and_returns_true(self):
        mock_session = _make_mock_session()
        mock_account = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_account
        )

        result = update_oauth_account_tokens(
            provider="github",
            provider_user_id="12345",
            access_token="new_encrypted_token",
            provider_username="new_name",
        )

        self.assertTrue(result)
        self.assertEqual(mock_account.access_token, "new_encrypted_token")
        self.assertEqual(mock_account.provider_username, "new_name")

    def test_returns_false_when_not_found(self):
        mock_session = _make_mock_session()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = update_oauth_account_tokens("github", "nonexistent")

        self.assertFalse(result)

    def test_skips_none_fields(self):
        mock_session = _make_mock_session()
        mock_account = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_account
        )

        update_oauth_account_tokens("github", "12345")

        self.assertFalse(
            hasattr(mock_account, "access_token")
            and mock_account.access_token is not None
            and mock_account.access_token != mock_account.access_token
        )


class TestSoftDeleteOAuthAccount(unittest.TestCase):
    def test_soft_deletes_and_returns_true(self):
        mock_session = _make_mock_session()
        mock_account = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_account
        )

        result = soft_delete_oauth_account("user-1", "github")

        self.assertTrue(result)
        self.assertEqual(mock_account.delete_flag, "Y")

    def test_returns_false_when_not_found(self):
        mock_session = _make_mock_session()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = soft_delete_oauth_account("user-1", "github")

        self.assertFalse(result)


class TestCountOAuthAccountsByUserId(unittest.TestCase):
    def test_returns_correct_count(self):
        mock_session = _make_mock_session()
        mock_session.query.return_value.filter.return_value.count.return_value = 3

        result = count_oauth_accounts_by_user_id("user-1")

        self.assertEqual(result, 3)

    def test_returns_zero_when_no_accounts(self):
        mock_session = _make_mock_session()
        mock_session.query.return_value.filter.return_value.count.return_value = 0

        result = count_oauth_accounts_by_user_id("user-1")

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
