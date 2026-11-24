# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Review projections preserve identity, pagination and secret boundaries."""

import base64
import io
import zipfile
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from contracts.errors.exceptions import UnauthorizedError
from contracts.review import ReviewListQuery
from management.services.repository import reviews

from test.backend.management.test_resource_review_submissions import application


@pytest.fixture
def session(mocker):
    value = MagicMock()
    mocker.patch.object(reviews, "get_db_session", return_value=nullcontext(value))
    mocker.patch.object(reviews, "check_role_permission", return_value=True)
    return value


def test_navigation_permission_is_required_before_database_access(session, mocker):
    mocker.patch.object(reviews, "check_role_permission", return_value=False)
    with pytest.raises(UnauthorizedError, match="repository access"):
        reviews.list_repository_reviews("u", "t", "USER", ReviewListQuery())
    session.connection.assert_not_called()


def test_names_keep_email_and_first_cas_identity_without_inventing_users(session):
    assert reviews._names(session, [{"submitted_user_id": None}]) == {}
    session.execute.assert_not_called()
    session.execute.return_value.all.side_effect = [
        [("submitter", "author@example.test")],
        [("submitter", "first"), ("submitter", "second"), ("unknown", "hidden"), ("submitter", "")],
    ]
    assert reviews._names(session, [{"submitted_user_id": "submitter"}]) == {
        "submitter": {"display_name": "author@example.test", "cas_username": "first"}
    }


def test_list_projects_global_pagination_and_submitter(session, mocker):
    record = application()
    operation = mocker.patch.object(reviews, "list_reviews", return_value=([record], 21))
    mocker.patch.object(reviews, "_names", return_value={"submitter": {"display_name": "email"}})
    query = ReviewListQuery(page=2, page_size=10)
    result = reviews.list_repository_reviews("user", "tenant", "ADMIN", query)
    assert result["pagination"] == {"page": 2, "page_size": 10, "total": 21, "total_pages": 3}
    assert result["items"][0]["submitter"]["display_name"] == "email"
    assert result["items"][0]["allowed_actions"] == ["approve", "reject"]
    operation.assert_called_once_with(session, "user", "tenant", "ADMIN", query)
    session.connection.assert_called_once_with(execution_options={"isolation_level": "REPEATABLE READ"})


@pytest.mark.parametrize("repository_id", [None, 19])
def test_detail_reads_frozen_payload_and_current_status_separately(session, mocker, repository_id):
    record = application(
        repository_id=repository_id,
        resource_snapshot={
            "payload": {
                "agent_id": 3,
                "version_no": 1,
                "version_name": "V1",
                "agent_info_json": {
                    "agent_info": {
                        "3": {"name": "root", "system_prompt": "frozen", "tools": [{"name": "search"}, "ignored"]},
                        "invalid": "ignored",
                    }
                },
            }
        },
    )
    mocker.patch.object(reviews, "get_review", return_value=record)
    mocker.patch.object(reviews, "_names", return_value={})
    session.scalar.return_value = "not_shared"
    result = reviews.get_repository_review(11, "u", "tenant", "ADMIN")
    assert result["resource_detail"]["agents"] == [
        {"name": "root", "description": None, "prompt": "frozen", "tools": ["search"]}
    ]
    assert result["current_repository_status"] == ("not_shared" if repository_id else None)
    assert session.scalar.call_count == bool(repository_id)


def test_hidden_detail_is_not_returned(session, mocker):
    mocker.patch.object(reviews, "get_review", return_value=None)
    with pytest.raises(LookupError):
        reviews.get_repository_review(11, "u", "tenant", "DEV")


def test_mcp_detail_never_exposes_credentials_or_config_values():
    result = reviews.resource_detail(
        "mcp",
        SimpleNamespace(
            source_mcp_id=3,
            transport_type="sse",
            mcp_server="https://user:secret@host/sse?token=secret#secret",
            shared_fields={"url": True, "headers": False},
            config_json={"headers": {"Authorization": "secret"}, "empty": "", "zero": 0},
            registry_json=None,
        ),
    )
    assert result["server_url"] == "https://host/sse"
    assert result["shared_fields"] == {"url": True, "headers": False}
    assert result["sensitive_fields"] == [
        {"name": "headers.Authorization", "configured": True, "masked": True},
        {"name": "empty", "configured": False, "masked": True},
        {"name": "zero", "configured": True, "masked": True},
    ]
    assert "secret" not in str(result)
    assert reviews._safe_url(None) is None


@pytest.mark.parametrize("valid", [True, False])
def test_skill_detail_lists_files_without_extracting_archive(valid):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("folder/", "")
        archive.writestr("folder/SKILL.md", "abc")
    result = reviews.resource_detail(
        "skill",
        SimpleNamespace(
            skill_id=3,
            name="helper",
            tags=None,
            description="description",
            icon=None,
            skill_info_json={"skill_content": "readme"},
            skill_zip_base64=base64.b64encode(output.getvalue()).decode() if valid else "invalid",
        ),
    )
    assert result["readme"] == "readme"
    assert result["files_unavailable"] is not valid
    assert result["file_manifest"] == ([{"path": "folder/SKILL.md", "size_bytes": 3}] if valid else [])
    assert result["file_count"] == int(valid)


def test_agent_detail_handles_legacy_non_mapping_tree():
    assert (
        reviews.resource_detail(
            "agent",
            SimpleNamespace(agent_id=3, version_no=1, version_name=None, agent_info_json={"agent_info": ["legacy"]}),
        )["agents"]
        == []
    )


@pytest.mark.parametrize("ids,error", [([], LookupError), ([11, 12], reviews.ReviewConflictError), ([11], None)])
def test_legacy_detail_requires_unique_authorized_mapping(session, mocker, ids, error):
    session.scalars.return_value.all.return_value = ids
    detail = mocker.patch.object(reviews, "get_repository_review", return_value={"review_id": "11"})
    if error:
        with pytest.raises(error):
            reviews.get_legacy_repository_review("agent", 99, "user", "tenant", "DEV")
        detail.assert_not_called()
    else:
        assert reviews.get_legacy_repository_review("agent", 99, "user", "tenant", "DEV") == {"review_id": "11"}
        detail.assert_called_once_with(11, "user", "tenant", "DEV")


def test_empty_latest_review_projection_does_not_query(session):
    reviews.attach_latest_reviews([{}], "agent", "agent_id", "u", "t")
    session.scalars.assert_not_called()
