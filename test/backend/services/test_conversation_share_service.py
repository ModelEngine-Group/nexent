from datetime import datetime
from unittest.mock import call

import pytest

from services import conversation_share_service as service


@pytest.fixture(autouse=True)
def stable_ids(mocker):
    mocker.patch("services.conversation_share_service._new_token", return_value="share_token")
    ids = iter(["asset_1", "asset_2", "asset_3", "asset_4"])
    mocker.patch("services.conversation_share_service._new_asset_id", side_effect=lambda: next(ids))


def test_extract_object_name_from_supported_references():
    assert service._extract_object_name("s3://bucket/attachments/u/a.pdf") == "attachments/u/a.pdf"
    assert service._extract_object_name("/api/file/preview/attachments/u/a.pdf") == "attachments/u/a.pdf"
    assert service._extract_object_name("api/file/download/attachments/u/a.pdf?x=1") == "attachments/u/a.pdf"
    assert service._extract_object_name("attachments/u/a.pdf") == "attachments/u/a.pdf"
    assert (
        service._extract_object_name("https://host/api/file/download/knowledge_base/doc.md")
        == "knowledge_base/doc.md"
    )
    assert service._extract_object_name("https://host/no-supported-path/doc.md") is None
    assert service._extract_object_name("") is None
    assert service._extract_object_name({"url": "attachments/u/a.pdf"}) is None


def test_select_message_pairs_keeps_selected_user_and_following_assistant():
    messages = [
        {"message_id": 1, "role": "user", "message": "u1"},
        {"message_id": 2, "role": "assistant", "message": "a1"},
        {"message_id": 3, "role": "user", "message": "u2"},
        {"message_id": 4, "role": "assistant", "message": "a2"},
        {"message_id": 5, "role": "assistant", "message": "orphan"},
    ]

    selected = service._select_message_pairs(messages, [3])

    assert selected == [
        {"message_id": 3, "role": "user", "message": "u2"},
        {"message_id": 4, "role": "assistant", "message": "a2"},
    ]


def test_select_message_pairs_without_selection_returns_all_messages():
    messages = [{"message_id": 1, "role": "user"}]

    assert service._select_message_pairs(messages, None) is messages
    assert service._select_message_pairs(messages, []) is messages


def test_rewrite_message_assets_registers_and_reuses_assets(mocker):
    mocker.patch("services.conversation_share_service.get_content_type", return_value="application/pdf")
    mocker.patch("services.conversation_share_service.get_file_size_from_minio", return_value=123)
    snapshot = {
        "message": [
            {
                "message_id": 1,
                "role": "user",
                "minio_files": [
                    {"object_name": "attachments/u/report.pdf", "name": "report.pdf"}
                ],
                "picture": ["s3://bucket/attachments/u/report.pdf"],
                "message": [
                    {
                        "type": "text",
                        "content": "See s3://bucket/knowledge_base/manual.md",
                    }
                ],
            },
            {
                "message_id": 2,
                "role": "assistant",
                "search": [
                    {
                        "source_type": "file",
                        "filename": "manual.md",
                        "url": "/api/file/download/knowledge_base/manual.md",
                    }
                ],
            },
        ]
    }

    asset_map = {}
    rewritten = service._rewrite_message_assets("share_token", snapshot, asset_map)

    attachment = rewritten["message"][0]["minio_files"][0]
    assert attachment["asset_id"] == "asset_1"
    assert attachment["preview_url"] == "/api/share/share_token/assets/asset_1/preview"
    assert attachment["download_url"] == "/api/share/share_token/assets/asset_1/download"
    assert rewritten["message"][0]["picture"] == [
        "/api/share/share_token/assets/asset_1/preview"
    ]
    assert "/api/share/share_token/assets/asset_2/preview" in rewritten["message"][0]["message"][0]["content"]
    assert rewritten["message"][1]["search"][0]["asset_id"] == "asset_2"
    assert rewritten["message"][1]["search"][0]["url"] == "/api/share/share_token/assets/asset_2/download"
    assert set(asset_map) == {"attachments/u/report.pdf", "knowledge_base/manual.md"}
    assert asset_map["attachments/u/report.pdf"]["size"] == 123
    assert asset_map["attachments/u/report.pdf"]["content_type"] == "application/pdf"


def test_register_asset_falls_back_when_metadata_lookup_fails(mocker):
    mocker.patch("services.conversation_share_service.get_content_type", side_effect=RuntimeError("minio error"))
    mocker.patch("services.conversation_share_service.get_file_size_from_minio", side_effect=RuntimeError("minio error"))

    asset_map = {}
    asset = service._register_asset(
        "share_token",
        "attachments/u/file.bin",
        {},
        "attachment",
        asset_map,
    )

    assert asset["content_type"] == "application/octet-stream"
    assert asset["size"] == 0
    assert asset["filename"] == "file.bin"
    assert asset_map["attachments/u/file.bin"] is asset


def test_create_share_snapshot_service_selected_messages_and_assets(mocker):
    expire_time = datetime(2030, 1, 1)
    mock_authorize = mocker.patch(
        "services.conversation_share_service.authorize_conversation_owner",
        return_value={"conversation_id": 7, "conversation_title": "Conversation title"},
    )
    mock_get_history = mocker.patch(
        "services.conversation_share_service.get_conversation_history_service",
        return_value=[
            {
                "conversation_id": 7,
                "message": [
                    {
                        "message_id": 1,
                        "role": "user",
                        "message": "u1",
                        "minio_files": [
                            {"object_name": "attachments/u/report.pdf", "name": "report.pdf"}
                        ],
                    },
                    {"message_id": 2, "role": "assistant", "message": "a1"},
                    {"message_id": 3, "role": "user", "message": "u2"},
                    {"message_id": 4, "role": "assistant", "message": "a2"},
                ],
            }
        ],
    )
    mocker.patch("services.conversation_share_service.get_content_type", return_value="application/pdf")
    mocker.patch("services.conversation_share_service.get_file_size_from_minio", return_value=10)
    mock_create_share = mocker.patch(
        "services.conversation_share_service.create_conversation_share",
        return_value={"title": "Conversation title"},
    )
    mock_create_assets = mocker.patch(
        "services.conversation_share_service.create_conversation_share_assets",
        return_value=[{"asset_id": "asset_1"}],
    )

    result = service.create_share_snapshot_service(
        conversation_id=7,
        user_id="user_1",
        tenant_id="tenant_1",
        mode="selected",
        selected_user_message_ids=[1],
        expire_time=expire_time,
    )

    assert result == {
        "share_id": "share_token",
        "share_token": "share_token",
        "conversation_id": 7,
        "title": "Conversation title",
        "asset_count": 1,
    }
    share_payload = mock_create_share.call_args.args[0]
    assert share_payload["share_token"] == "share_token"
    assert share_payload["conversation_id"] == 7
    assert share_payload["tenant_id"] == "tenant_1"
    assert share_payload["mode"] == "selected"
    assert share_payload["selected_message_ids"] == [1]
    assert share_payload["expire_time"] == expire_time
    assert share_payload["snapshot_json"]["conversation_title"] == "Conversation title"
    assert [msg["message_id"] for msg in share_payload["snapshot_json"]["message"]] == [1, 2]
    assert (
        share_payload["snapshot_json"]["message"][0]["minio_files"][0]["preview_url"]
        == "/api/share/share_token/assets/asset_1/preview"
    )
    mock_authorize.assert_called_once_with(
        conversation_id=7,
        user_id="user_1",
        tenant_id="tenant_1",
        operation="conversation.share.create",
    )
    mock_get_history.assert_called_once_with(7, "user_1", "tenant_1")
    mock_create_share.assert_called_once()
    mock_create_assets.assert_called_once_with(
        "share_token",
        [
            {
                "asset_id": "asset_1",
                "share_token": "share_token",
                "object_name": "attachments/u/report.pdf",
                "filename": "report.pdf",
                "content_type": "application/pdf",
                "size": 10,
                "source_kind": "attachment",
                "metadata_json": {
                    "object_name": "attachments/u/report.pdf",
                    "name": "report.pdf",
                },
            }
        ],
        "user_1",
    )


def test_create_share_snapshot_service_all_messages_without_assets(mocker):
    mock_authorize = mocker.patch(
        "services.conversation_share_service.authorize_conversation_owner",
        return_value={"conversation_id": 8, "conversation_title": "All messages"},
    )
    mock_get_history = mocker.patch(
        "services.conversation_share_service.get_conversation_history_service",
        return_value=[
            {
                "conversation_id": 8,
                "message": [
                    {"message_id": 1, "role": "user", "message": "u1"},
                    {"message_id": 2, "role": "assistant", "message": "a1"},
                    {"message_id": 3, "role": "user", "message": "u2"},
                ],
            }
        ],
    )
    mock_create_share = mocker.patch(
        "services.conversation_share_service.create_conversation_share",
        return_value={"title": "All messages"},
    )
    mock_create_assets = mocker.patch(
        "services.conversation_share_service.create_conversation_share_assets",
        return_value=[],
    )

    result = service.create_share_snapshot_service(
        conversation_id=8,
        user_id="user_1",
        tenant_id="tenant_1",
        mode="all",
        selected_user_message_ids=[1],
    )

    assert result["asset_count"] == 0
    share_payload = mock_create_share.call_args.args[0]
    assert share_payload["mode"] == "all"
    assert [msg["message_id"] for msg in share_payload["snapshot_json"]["message"]] == [1, 2, 3]
    mock_authorize.assert_called_once_with(
        conversation_id=8,
        user_id="user_1",
        tenant_id="tenant_1",
        operation="conversation.share.create",
    )
    mock_get_history.assert_called_once_with(8, "user_1", "tenant_1")
    mock_create_assets.assert_called_once_with("share_token", [], "user_1")


def test_create_share_snapshot_service_rejects_missing_conversation(mocker):
    mock_authorize = mocker.patch(
        "services.conversation_share_service.authorize_conversation_owner",
        side_effect=ValueError("Conversation 404 does not exist or is not accessible"),
    )

    with pytest.raises(ValueError, match="does not exist or is not accessible"):
        service.create_share_snapshot_service(
            conversation_id=404,
            user_id="user_1",
            tenant_id="tenant_1",
        )
    mock_authorize.assert_called_once_with(
        conversation_id=404,
        user_id="user_1",
        tenant_id="tenant_1",
        operation="conversation.share.create",
    )


def test_create_share_snapshot_service_rejects_empty_history(mocker):
    mocker.patch(
        "services.conversation_share_service.authorize_conversation_owner",
        return_value={"conversation_id": 7, "conversation_title": "Conversation title"},
    )
    mock_get_history = mocker.patch(
        "services.conversation_share_service.get_conversation_history_service",
        return_value=[],
    )

    with pytest.raises(ValueError, match="No history data found"):
        service.create_share_snapshot_service(
            conversation_id=7,
            user_id="user_1",
            tenant_id="tenant_1",
        )
    mock_get_history.assert_called_once_with(7, "user_1", "tenant_1")


def test_authorize_conversation_owner_checks_tenant_and_user(mocker):
    conversation = {"conversation_id": 7, "conversation_title": "Conversation title"}
    mock_get_conversation = mocker.patch(
        "database.conversation_db.get_conversation",
        return_value=conversation,
    )
    mock_authorize = mocker.patch("services.context_identity_service.authorize_context_operation")

    result = service.authorize_conversation_owner(
        conversation_id=7,
        user_id="user_1",
        tenant_id="tenant_1",
        operation="conversation.share.create",
    )

    assert result is conversation
    mock_get_conversation.assert_called_once_with(7, "user_1", tenant_id="tenant_1")
    mock_authorize.assert_called_once()
    assert mock_authorize.call_args.kwargs["allowed"] is True


def test_authorize_conversation_owner_rejects_unowned_conversation(mocker):
    mock_get_conversation = mocker.patch(
        "database.conversation_db.get_conversation",
        return_value=None,
    )
    mock_authorize = mocker.patch("services.context_identity_service.authorize_context_operation")

    with pytest.raises(ValueError, match="does not exist or is not accessible"):
        service.authorize_conversation_owner(
            conversation_id=404,
            user_id="user_1",
            tenant_id="tenant_1",
            operation="conversation.share.create",
        )

    mock_get_conversation.assert_called_once_with(404, "user_1", tenant_id="tenant_1")
    mock_authorize.assert_called_once()
    assert mock_authorize.call_args.kwargs["allowed"] is False
    assert mock_authorize.call_args.kwargs["reason_code"] == "conversation_not_owned"


def test_get_share_snapshot_service_success(mocker):
    create_time = datetime(2026, 1, 1)
    mocker.patch(
        "services.conversation_share_service.get_active_conversation_share",
        return_value={
            "title": "Shared",
            "conversation_id": 7,
            "create_time": create_time,
            "snapshot_json": {"message": []},
        },
    )

    result = service.get_share_snapshot_service("share_token")

    assert result == {
        "share_id": "share_token",
        "title": "Shared",
        "conversation_id": 7,
        "create_time": create_time,
        "snapshot": {"message": []},
    }


def test_get_share_snapshot_service_not_found(mocker):
    mocker.patch(
        "services.conversation_share_service.get_active_conversation_share",
        return_value=None,
    )

    with pytest.raises(ValueError, match="Share not found or expired"):
        service.get_share_snapshot_service("missing")


def test_get_share_asset_service_success(mocker):
    mock_get_share = mocker.patch(
        "services.conversation_share_service.get_active_conversation_share",
        return_value={"share_token": "share_token"},
    )
    mock_get_asset = mocker.patch(
        "services.conversation_share_service.get_share_asset",
        return_value={"asset_id": "asset_1", "object_name": "attachments/u/report.pdf"},
    )

    result = service.get_share_asset_service("share_token", "asset_1")

    assert result["asset_id"] == "asset_1"
    mock_get_share.assert_called_once_with("share_token")
    mock_get_asset.assert_called_once_with("share_token", "asset_1")


def test_get_share_asset_service_rejects_missing_share_or_asset(mocker):
    mock_get_share = mocker.patch(
        "services.conversation_share_service.get_active_conversation_share",
        return_value=None,
    )
    mock_get_asset = mocker.patch("services.conversation_share_service.get_share_asset")

    with pytest.raises(ValueError, match="Share not found or expired"):
        service.get_share_asset_service("missing", "asset_1")

    mock_get_asset.assert_not_called()

    mock_get_share.return_value = {"share_token": "share_token"}
    mock_get_asset.return_value = None
    with pytest.raises(ValueError, match="Share asset not found"):
        service.get_share_asset_service("share_token", "missing")

    assert mock_get_share.mock_calls == [call("missing"), call("share_token")]
