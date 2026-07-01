from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps import conversation_share_app


app = FastAPI()
app.include_router(conversation_share_app.router)
client = TestClient(app)


def test_parse_range_header():
    assert conversation_share_app._parse_range_header("bytes=10-19", 100) == (10, 19)
    assert conversation_share_app._parse_range_header("bytes=10-", 100) == (10, 99)
    assert conversation_share_app._parse_range_header("bytes=-10", 100) == (90, 99)
    assert conversation_share_app._parse_range_header("bytes=90-120", 100) == (90, 99)
    assert conversation_share_app._parse_range_header(None, 100) is None
    assert conversation_share_app._parse_range_header("items=1-2", 100) is None
    assert conversation_share_app._parse_range_header("bytes=20-10", 100) is None
    assert conversation_share_app._parse_range_header("bytes=100-110", 100) is None
    assert conversation_share_app._parse_range_header("bytes=abc", 100) is None


def test_create_conversation_share_endpoint_success(mocker):
    mock_get_user = mocker.patch(
        "apps.conversation_share_app.get_current_user_id",
        return_value=("user_1", "tenant_1"),
    )
    mock_create = mocker.patch(
        "apps.conversation_share_app.create_share_snapshot_service",
        return_value={
            "share_id": "share_token",
            "conversation_id": 7,
            "title": "Test Conversation",
            "asset_count": 2,
        },
    )

    response = client.post(
        "/share/conversation/7",
        json={
            "mode": "selected",
            "selected_user_message_ids": [11, 13],
            "expire_time": "2030-01-01T00:00:00",
        },
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["url"] == "/share/share_token"
    mock_get_user.assert_called_once_with("Bearer token")
    create_kwargs = mock_create.call_args.kwargs
    assert create_kwargs["conversation_id"] == 7
    assert create_kwargs["user_id"] == "user_1"
    assert create_kwargs["tenant_id"] == "tenant_1"
    assert create_kwargs["mode"] == "selected"
    assert create_kwargs["selected_user_message_ids"] == [11, 13]
    assert create_kwargs["expire_time"].year == 2030


def test_create_conversation_share_endpoint_value_error(mocker):
    mocker.patch(
        "apps.conversation_share_app.get_current_user_id",
        return_value=("user_1", "tenant_1"),
    )
    mocker.patch(
        "apps.conversation_share_app.create_share_snapshot_service",
        side_effect=ValueError("Conversation is not accessible"),
    )

    response = client.post("/share/conversation/7", json={"mode": "all"})

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["detail"] == "Conversation is not accessible"


def test_create_conversation_share_endpoint_unexpected_error(mocker):
    mocker.patch(
        "apps.conversation_share_app.get_current_user_id",
        return_value=("user_1", "tenant_1"),
    )
    mocker.patch(
        "apps.conversation_share_app.create_share_snapshot_service",
        side_effect=RuntimeError("db down"),
    )
    mock_logger = mocker.patch("apps.conversation_share_app.logger")

    response = client.post("/share/conversation/7", json={"mode": "all"})

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == "Failed to create share"
    mock_logger.error.assert_called_once()


def test_get_conversation_share_endpoint_success(mocker):
    mock_get = mocker.patch(
        "apps.conversation_share_app.get_share_snapshot_service",
        return_value={"share_id": "share_token", "snapshot": {"message": []}},
    )

    response = client.get("/share/share_token")

    assert response.status_code == HTTPStatus.OK
    assert response.json()["data"]["share_id"] == "share_token"
    mock_get.assert_called_once_with("share_token")


def test_get_conversation_share_endpoint_not_found(mocker):
    mocker.patch(
        "apps.conversation_share_app.get_share_snapshot_service",
        side_effect=ValueError("Share not found"),
    )

    response = client.get("/share/missing")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["detail"] == "Share not found"


def test_download_share_asset_endpoint_success(mocker):
    mocker.patch(
        "apps.conversation_share_app.get_share_asset_service",
        return_value={
            "object_name": "attachments/user_1/report.pdf",
            "filename": "report.pdf",
        },
    )
    mocker.patch(
        "apps.conversation_share_app.get_file_stream_impl",
        new_callable=AsyncMock,
        return_value=(iter([b"abc"]), "application/pdf"),
    )

    response = client.get("/share/share_token/assets/asset_1/download")

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"abc"
    assert response.headers["content-type"].startswith("application/pdf")
    assert "report.pdf" in response.headers["content-disposition"]
    assert response.headers["etag"] == '"share-share_token-asset_1"'


def test_download_share_asset_endpoint_not_found(mocker):
    mocker.patch(
        "apps.conversation_share_app.get_share_asset_service",
        side_effect=ValueError("Share asset not found"),
    )

    response = client.get("/share/share_token/assets/missing/download")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["detail"] == "Share asset not found"


def test_preview_share_asset_endpoint_full_content(mocker):
    mocker.patch(
        "apps.conversation_share_app.get_share_asset_service",
        return_value={
            "object_name": "attachments/user_1/report.pdf",
            "filename": "report.pdf",
        },
    )
    mocker.patch(
        "apps.conversation_share_app.resolve_preview_file",
        new_callable=AsyncMock,
        return_value=("attachments/user_1/report.pdf", "application/pdf", 6),
    )
    stream = MagicMock()
    stream.iter_chunks.return_value = iter([b"abcdef"])
    stream.close = MagicMock()
    mock_get_stream = mocker.patch(
        "apps.conversation_share_app.get_preview_stream",
        return_value=stream,
    )

    response = client.get("/share/share_token/assets/asset_1/preview")

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"abcdef"
    assert response.headers["content-length"] == "6"
    assert response.headers["accept-ranges"] == "bytes"
    mock_get_stream.assert_called_once_with("attachments/user_1/report.pdf")


def test_preview_share_asset_endpoint_partial_content(mocker):
    mocker.patch(
        "apps.conversation_share_app.get_share_asset_service",
        return_value={"object_name": "attachments/user_1/report.pdf"},
    )
    mocker.patch(
        "apps.conversation_share_app.resolve_preview_file",
        new_callable=AsyncMock,
        return_value=("attachments/user_1/report.pdf", "application/pdf", 10),
    )
    stream = MagicMock()
    stream.iter_chunks.return_value = iter([b"cde"])
    stream.close = MagicMock()
    mock_get_stream = mocker.patch(
        "apps.conversation_share_app.get_preview_stream",
        return_value=stream,
    )

    response = client.get(
        "/share/share_token/assets/asset_1/preview",
        headers={"Range": "bytes=2-4"},
    )

    assert response.status_code == HTTPStatus.PARTIAL_CONTENT
    assert response.content == b"cde"
    assert response.headers["content-range"] == "bytes 2-4/10"
    assert response.headers["content-length"] == "3"
    mock_get_stream.assert_called_once_with("attachments/user_1/report.pdf", 2, 4)


def test_preview_share_asset_endpoint_invalid_range(mocker):
    mocker.patch(
        "apps.conversation_share_app.get_share_asset_service",
        return_value={"object_name": "attachments/user_1/report.pdf"},
    )
    mocker.patch(
        "apps.conversation_share_app.resolve_preview_file",
        new_callable=AsyncMock,
        return_value=("attachments/user_1/report.pdf", "application/pdf", 10),
    )

    response = client.get(
        "/share/share_token/assets/asset_1/preview",
        headers={"Range": "bytes=20-30"},
    )

    assert response.status_code == HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE
    assert response.headers["content-range"] == "bytes */10"


def test_preview_share_asset_endpoint_resolve_file_error(mocker):
    mocker.patch(
        "apps.conversation_share_app.get_share_asset_service",
        return_value={"object_name": "attachments/user_1/report.pdf"},
    )
    mocker.patch(
        "apps.conversation_share_app.resolve_preview_file",
        new_callable=AsyncMock,
        side_effect=conversation_share_app.UnsupportedFileTypeException("unsupported"),
    )

    response = client.get("/share/share_token/assets/asset_1/preview")

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["detail"] == "unsupported"
