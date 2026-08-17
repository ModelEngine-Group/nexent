"""Tests for the ModelScope Skill adapter."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from consts.exceptions import ModelScopeSkillError, ModelScopeSkillNotFoundError
from modelscope_hub.errors import NotFoundError

from backend.adapters.modelscope_skill_adapter import (
    ModelScopeSkillAdapter,
    _normalize_repo,
    _serialize_datetime,
)


def _repo(**overrides):
    values = {
        "id": "@anthropics/skill-creator",
        "repo_id": "@anthropics/skill-creator",
        "name": "skill-creator",
        "display_name": "skill-creator",
        "description": "Create and improve skills",
        "tags": ["category:skill-management"],
        "downloads": 10,
        "likes": 2,
        "license": "Apache-2.0",
        "last_modified": datetime(2026, 8, 7, 6, 37, 46, tzinfo=timezone.utc),
        "private": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_normalize_repo_uses_public_sdk_fields():
    result = _normalize_repo(_repo())

    assert result == {
        "skill_id": "@anthropics/skill-creator",
        "name": "skill-creator",
        "description": "Create and improve skills",
        "tags": ["category:skill-management"],
        "downloads": 10,
        "likes": 2,
        "license": "Apache-2.0",
        "last_modified": "2026-08-07T06:37:46Z",
        "private": False,
    }


def test_normalize_repo_rejects_missing_id():
    with pytest.raises(ModelScopeSkillError, match="without an id"):
        _normalize_repo(_repo(id="", repo_id=""))


def test_normalize_repo_falls_back_to_id_name_and_empty_optional_fields():
    result = _normalize_repo(
        _repo(
            repo_id=None,
            display_name="",
            name="",
            tags=None,
            description=None,
            license=None,
            last_modified=None,
        )
    )

    assert result["name"] == "skill-creator"
    assert result["tags"] == []
    assert result["last_modified"] is None
    assert _serialize_datetime(" 2026-01-01 ") == "2026-01-01"


def test_normalize_repo_rejects_invalid_statistics():
    with pytest.raises(ModelScopeSkillError, match="statistics"):
        _normalize_repo(_repo(downloads="not-a-number"))


def test_list_skills_normalizes_page_and_filters_private_items():
    api = MagicMock()
    api.list_repos.return_value = SimpleNamespace(
        items=[_repo(), _repo(id="owner/private", repo_id="owner/private", private=True)],
        total_count=2,
        page_number=1,
        page_size=12,
        has_next=False,
    )

    result = ModelScopeSkillAdapter(api).list_skills(
        search="creator", page_number=1, page_size=12
    )

    assert [item["skill_id"] for item in result["items"]] == [
        "@anthropics/skill-creator"
    ]
    assert result["total_count"] == 2
    api.list_repos.assert_called_once_with(
        repo_type="skill", search="creator", page_number=1, page_size=12
    )


def test_list_skills_maps_sdk_failure():
    api = MagicMock()
    api.list_repos.side_effect = RuntimeError("network")

    with pytest.raises(ModelScopeSkillError, match="Failed to query"):
        ModelScopeSkillAdapter(api).list_skills(
            search=None, page_number=1, page_size=12
        )


def test_list_skills_maps_malformed_page():
    api = MagicMock()
    api.list_repos.return_value = SimpleNamespace(items=[])

    with pytest.raises(ModelScopeSkillError, match="invalid Skill list"):
        ModelScopeSkillAdapter(api).list_skills(
            search=None, page_number=1, page_size=12
        )


def test_get_skill_returns_public_exact_repo():
    api = MagicMock()
    api.get_repo.return_value = _repo()

    result = ModelScopeSkillAdapter(api).get_skill("@anthropics/skill-creator")

    assert result["skill_id"] == "@anthropics/skill-creator"
    api.get_repo.assert_called_once_with(
        "@anthropics/skill-creator", repo_type="skill"
    )


def test_get_skill_rejects_private_repo():
    api = MagicMock()
    api.get_repo.return_value = _repo(private=True)

    with pytest.raises(ModelScopeSkillNotFoundError, match="not public"):
        ModelScopeSkillAdapter(api).get_skill("owner/private")


def test_get_skill_maps_not_found():
    api = MagicMock()
    api.get_repo.side_effect = NotFoundError("missing")

    with pytest.raises(ModelScopeSkillNotFoundError, match="not found"):
        ModelScopeSkillAdapter(api).get_skill("owner/missing")


def test_get_skill_maps_provider_failure():
    api = MagicMock()
    api.get_repo.side_effect = RuntimeError("timeout")

    with pytest.raises(ModelScopeSkillError, match="details"):
        ModelScopeSkillAdapter(api).get_skill("owner/skill")


def test_download_skill_returns_directory_inside_target(tmp_path: Path):
    api = MagicMock()
    downloaded = tmp_path / "skill"
    downloaded.mkdir()
    api.download_skill.return_value = str(downloaded)

    result = ModelScopeSkillAdapter(api).download_skill("owner/skill", tmp_path)

    assert result == downloaded.resolve()


def test_download_skill_rejects_directory_outside_target(tmp_path: Path):
    api = MagicMock()
    outside = tmp_path.parent / "outside-skill"
    outside.mkdir(exist_ok=True)
    api.download_skill.return_value = str(outside)

    with pytest.raises(ModelScopeSkillError, match="invalid Skill directory"):
        ModelScopeSkillAdapter(api).download_skill("owner/skill", tmp_path)


@pytest.mark.parametrize(
    ("sdk_error", "expected_error"),
    [
        (NotFoundError("missing"), ModelScopeSkillNotFoundError),
        (RuntimeError("timeout"), ModelScopeSkillError),
    ],
)
def test_download_skill_maps_sdk_errors(tmp_path, sdk_error, expected_error):
    api = MagicMock()
    api.download_skill.side_effect = sdk_error

    with pytest.raises(expected_error):
        ModelScopeSkillAdapter(api).download_skill("owner/skill", tmp_path)
