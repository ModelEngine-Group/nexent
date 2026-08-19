"""Adapter for listing and downloading public ModelScope Skills."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from consts.exceptions import ModelScopeSkillError, ModelScopeSkillNotFoundError
from modelscope.hub.api import HubApi
from modelscope_hub.errors import NotExistError, NotFoundError

MODELSCOPE_SKILL_SOURCE = "modelscope"
MODELSCOPE_MAX_RESULT_WINDOW = 2_400
_CATEGORY_PREFIX = "category:"
_CUSTOM_TAG_PREFIX = "custom_tag:"


def _serialize_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    text = str(value).strip()
    return text or None


def _prefixed_value(text: str, prefix: str) -> str | None:
    if not text.lower().startswith(prefix):
        return None
    return text[len(prefix) :].strip()


def _parse_raw_tags(raw_tags: Any) -> tuple[list[str], str]:
    """Split ModelScope Hub tags into display tags and a category.

    API contract for GET /skills/market/list and adapter get_skill:
    - ``category:`` -> ``category`` (first non-empty value, hyphens preserved)
    - ``custom_tag:`` -> ``tags`` (unique, case-insensitive)
    - ``license:``, ``developer:``, unknown prefixes, and unprefixed values are dropped
    - ``license`` continues to come from the SDK repo.license field
    """
    if not isinstance(raw_tags, (list, tuple)):
        return [], ""

    tags: list[str] = []
    seen_tags: set[str] = set()
    category = ""

    for raw_tag in raw_tags:
        text = str(raw_tag).strip()
        if not text:
            continue

        category_value = _prefixed_value(text, _CATEGORY_PREFIX)
        if category_value is not None:
            if category_value and not category:
                category = category_value
            continue

        custom_tag = _prefixed_value(text, _CUSTOM_TAG_PREFIX)
        if custom_tag is not None:
            dedupe_key = custom_tag.lower()
            if custom_tag and dedupe_key not in seen_tags:
                tags.append(custom_tag)
                seen_tags.add(dedupe_key)

    return tags, category


def _normalize_repo(repo: Any) -> dict[str, Any]:
    skill_id = str(getattr(repo, "repo_id", None) or getattr(repo, "id", "")).strip()
    if not skill_id:
        raise ModelScopeSkillError("ModelScope returned a Skill without an id")

    tags, category = _parse_raw_tags(getattr(repo, "tags", None))
    display_name = str(getattr(repo, "display_name", None) or getattr(repo, "name", "")).strip()
    if not display_name:
        display_name = skill_id.rsplit("/", 1)[-1]

    try:
        downloads = int(getattr(repo, "downloads", 0) or 0)
        likes = int(getattr(repo, "likes", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise ModelScopeSkillError(
            "ModelScope returned invalid Skill statistics"
        ) from exc

    return {
        "skill_id": skill_id,
        "name": display_name,
        "description": str(getattr(repo, "description", None) or ""),
        "tags": tags,
        "category": category,
        "downloads": downloads,
        "likes": likes,
        "license": str(getattr(repo, "license", None) or ""),
        "last_modified": _serialize_datetime(getattr(repo, "last_modified", None)),
        "private": bool(getattr(repo, "private", False)),
    }


class ModelScopeSkillAdapter:
    """Small, testable wrapper around the ModelScope Hub SDK."""

    def __init__(self, api: HubApi | None = None) -> None:
        self._api = api or HubApi()

    def list_skills(
        self,
        *,
        search: str | None,
        page_number: int,
        page_size: int,
    ) -> dict[str, Any]:
        try:
            page = self._api.list_repos(
                repo_type="skill",
                search=search or None,
                page_number=page_number,
                page_size=page_size,
            )
        except Exception as exc:
            raise ModelScopeSkillError("Failed to query ModelScope Skills") from exc

        try:
            items = [_normalize_repo(repo) for repo in page.items]
            response_page_number = int(page.page_number or page_number)
            response_page_size = int(page.page_size or page_size)
            has_accessible_next_page = (
                response_page_number + 1
            ) * response_page_size <= MODELSCOPE_MAX_RESULT_WINDOW
            return {
                "items": [item for item in items if not item["private"]],
                "total_count": int(page.total_count or 0),
                "page_number": response_page_number,
                "page_size": response_page_size,
                "has_next": bool(page.has_next) and has_accessible_next_page,
            }
        except ModelScopeSkillError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise ModelScopeSkillError(
                "ModelScope returned an invalid Skill list response"
            ) from exc

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        try:
            repo = self._api.get_repo(skill_id, repo_type="skill")
        except (NotExistError, NotFoundError) as exc:
            raise ModelScopeSkillNotFoundError(
                f"ModelScope Skill not found: {skill_id}"
            ) from exc
        except Exception as exc:
            raise ModelScopeSkillError("Failed to query ModelScope Skill details") from exc

        item = _normalize_repo(repo)
        if item["private"]:
            raise ModelScopeSkillNotFoundError(
                f"ModelScope Skill is not public: {skill_id}"
            )
        return item

    def download_skill(self, skill_id: str, local_dir: Path) -> Path:
        target_root = local_dir.resolve()
        target_root.mkdir(parents=True, exist_ok=True)
        try:
            downloaded = Path(
                self._api.download_skill(skill_id=skill_id, local_dir=str(target_root))
            ).resolve()
        except (NotExistError, NotFoundError) as exc:
            raise ModelScopeSkillNotFoundError(
                f"ModelScope Skill not found: {skill_id}"
            ) from exc
        except Exception as exc:
            raise ModelScopeSkillError("Failed to download ModelScope Skill") from exc

        if not downloaded.is_dir() or not downloaded.is_relative_to(target_root):
            raise ModelScopeSkillError("ModelScope returned an invalid Skill directory")
        return downloaded
