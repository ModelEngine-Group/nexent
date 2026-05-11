import importlib
import os
import sys
import types

import pytest


BACKEND_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../backend")
)


@pytest.fixture(autouse=True)
def _reset_prompt_template_service_modules():
    yield
    sys.modules.pop("services.prompt_template_service", None)
    sys.modules.pop("database.prompt_template_db", None)


@pytest.fixture
def prompt_template_models(monkeypatch):
    if BACKEND_PATH not in sys.path:
        sys.path.insert(0, BACKEND_PATH)

    nexent_module = types.ModuleType("nexent")
    nexent_core_module = types.ModuleType("nexent.core")
    nexent_agents_module = types.ModuleType("nexent.core.agents")
    agent_model_module = types.ModuleType("nexent.core.agents.agent_model")
    agent_model_module.ToolConfig = type("ToolConfig", (), {})

    monkeypatch.setitem(sys.modules, "nexent", nexent_module)
    monkeypatch.setitem(sys.modules, "nexent.core", nexent_core_module)
    monkeypatch.setitem(sys.modules, "nexent.core.agents", nexent_agents_module)
    monkeypatch.setitem(sys.modules, "nexent.core.agents.agent_model", agent_model_module)

    consts_model = importlib.import_module("consts.model")
    consts_exceptions = importlib.import_module("consts.exceptions")
    return consts_model, consts_exceptions


@pytest.fixture
def prompt_template_service_module(monkeypatch):
    if BACKEND_PATH not in sys.path:
        sys.path.insert(0, BACKEND_PATH)

    db_module = types.ModuleType("database.prompt_template_db")
    for name in [
        "create_prompt_template",
        "delete_prompt_template",
        "get_prompt_template_by_id",
        "get_prompt_template_by_name",
        "get_prompt_template_by_template_id",
        "query_prompt_templates_by_user",
        "upsert_prompt_template_by_id",
        "update_prompt_template",
    ]:
        setattr(db_module, name, lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "database.prompt_template_db", db_module)

    sys.modules.pop("services.prompt_template_service", None)
    module = importlib.import_module("services.prompt_template_service")
    return importlib.reload(module)


@pytest.fixture
def template_content_factory():
    def _build(seed: str = "value", **overrides):
        content = {
            "duty_system_prompt": f"{seed}-duty",
            "constraint_system_prompt": f"{seed}-constraint",
            "few_shots_system_prompt": f"{seed}-few-shots",
            "agent_variable_name_system_prompt": f"{seed}-agent-name",
            "agent_display_name_system_prompt": f"{seed}-display-name",
            "agent_description_system_prompt": f"{seed}-description",
            "user_prompt": f"{seed}-user",
            "agent_name_regenerate_system_prompt": f"{seed}-regen-name-system",
            "agent_name_regenerate_user_prompt": f"{seed}-regen-name-user",
            "agent_display_name_regenerate_system_prompt": f"{seed}-regen-display-system",
            "agent_display_name_regenerate_user_prompt": f"{seed}-regen-display-user",
        }
        content.update(overrides)
        return content

    return _build


@pytest.fixture
def prompt_template_request_factory(template_content_factory, prompt_template_models):
    consts_model, _ = prompt_template_models

    def _build(
        template_name: str = "template-a",
        description: str | None = "template description",
        template_type: str = "agent_generate",
        template_content_zh: dict | None = None,
        template_content_en: dict | None = None,
    ):
        return consts_model.PromptTemplateRequest(
            template_name=template_name,
            description=description,
            template_type=template_type,
            template_content_zh=consts_model.PromptTemplateContentRequest(
                **(template_content_zh or template_content_factory("zh"))
            ),
            template_content_en=(
                consts_model.PromptTemplateContentRequest(
                    **(template_content_en or template_content_factory("en"))
                )
                if template_content_en is not None
                else None
            ),
        )

    return _build


def test_build_system_default_prompt_template_payload(
    mocker, prompt_template_service_module, template_content_factory
):
    mocker.patch.object(
        prompt_template_service_module,
        "get_prompt_generate_prompt_template",
        side_effect=[
            template_content_factory("zh"),
            template_content_factory("en"),
        ],
    )

    payload = prompt_template_service_module.build_system_default_prompt_template_payload()

    assert payload["template_id"] == 0
    assert payload["template_name"] == "system_default"
    assert payload["tenant_id"] == prompt_template_service_module.SYSTEM_PROMPT_TEMPLATE_TENANT_ID
    assert payload["user_id"] == prompt_template_service_module.SYSTEM_PROMPT_TEMPLATE_USER_ID
    assert payload["template_content_zh"]["duty_system_prompt"] == "zh-duty"
    assert payload["template_content_en"]["duty_system_prompt"] == "en-duty"


def test_sync_system_default_prompt_template_marks_system_default(
    mocker, prompt_template_service_module
):
    payload = {"template_id": 0, "template_name": "system_default"}
    mocker.patch.object(
        prompt_template_service_module,
        "build_system_default_prompt_template_payload",
        return_value=payload,
    )
    upsert_mock = mocker.patch.object(
        prompt_template_service_module,
        "upsert_prompt_template_by_id",
        return_value={"template_id": 0, "template_name": "system_default"},
    )

    result = prompt_template_service_module.sync_system_default_prompt_template()

    upsert_mock.assert_called_once_with(
        template_id=0,
        template_data=payload,
        user_id=prompt_template_service_module.SYSTEM_PROMPT_TEMPLATE_USER_ID,
    )
    assert result["is_system_default"] is True


def test_get_system_default_prompt_template_syncs_when_missing(
    mocker, prompt_template_service_module
):
    mocker.patch.object(
        prompt_template_service_module,
        "get_prompt_template_by_template_id",
        return_value=None,
    )
    sync_mock = mocker.patch.object(
        prompt_template_service_module,
        "sync_system_default_prompt_template",
        return_value={"template_id": 0, "template_name": "system_default"},
    )

    result = prompt_template_service_module.get_system_default_prompt_template()

    sync_mock.assert_called_once_with()
    assert result["template_id"] == 0
    assert result["is_system_default"] is True


def test_normalize_template_request_trims_and_drops_empty_optional_fields(
    prompt_template_service_module, prompt_template_request_factory, template_content_factory
):
    request = prompt_template_request_factory(
        template_name="  template-a  ",
        description="   ",
        template_content_zh=template_content_factory(
            "zh",
            constraint_system_prompt="",
            few_shots_system_prompt="   ",
        ),
        template_content_en=template_content_factory(
            "en",
            duty_system_prompt="",
            constraint_system_prompt="",
            few_shots_system_prompt="",
            agent_variable_name_system_prompt="",
            agent_display_name_system_prompt="",
            agent_description_system_prompt="",
            user_prompt="",
            agent_name_regenerate_system_prompt="",
            agent_name_regenerate_user_prompt="",
            agent_display_name_regenerate_system_prompt="",
            agent_display_name_regenerate_user_prompt="",
        ),
    )

    result = prompt_template_service_module._normalize_template_request(request)

    assert result["template_name"] == "template-a"
    assert result["description"] is None
    assert "constraint_system_prompt" not in result["template_content_zh"]
    assert result["template_content_en"] is None


def test_normalize_template_request_requires_non_empty_zh_content(
    prompt_template_service_module,
    prompt_template_request_factory,
    template_content_factory,
    prompt_template_models,
):
    _, consts_exceptions = prompt_template_models
    request = prompt_template_request_factory(
        template_content_zh=template_content_factory(
            "zh",
            duty_system_prompt="",
            constraint_system_prompt="",
            few_shots_system_prompt="",
            agent_variable_name_system_prompt="",
            agent_display_name_system_prompt="",
            agent_description_system_prompt="",
            user_prompt="",
            agent_name_regenerate_system_prompt="",
            agent_name_regenerate_user_prompt="",
            agent_display_name_regenerate_system_prompt="",
            agent_display_name_regenerate_user_prompt="",
        )
    )

    with pytest.raises(
        consts_exceptions.ValidationError, match="template_content_zh is required"
    ):
        prompt_template_service_module._normalize_template_request(request)


def test_list_prompt_templates_impl_prepends_system_default_and_filters_duplicate_id(
    mocker, prompt_template_service_module
):
    mocker.patch.object(
        prompt_template_service_module,
        "sync_system_default_prompt_template",
        return_value={"template_id": 0, "template_name": "system_default", "is_system_default": True},
    )
    mocker.patch.object(
        prompt_template_service_module,
        "query_prompt_templates_by_user",
        return_value=[
            {"template_id": 0, "template_name": "system_default"},
            {"template_id": 2, "template_name": "custom-template"},
        ],
    )

    result = prompt_template_service_module.list_prompt_templates_impl("tenant-1", "user-1")

    assert [item["template_id"] for item in result] == [0, 2]
    assert result[0]["is_system_default"] is True
    assert result[1]["is_system_default"] is False


def test_create_prompt_template_impl_rejects_duplicate_name(
    mocker,
    prompt_template_service_module,
    prompt_template_request_factory,
    prompt_template_models,
):
    _, consts_exceptions = prompt_template_models
    mocker.patch.object(
        prompt_template_service_module,
        "get_prompt_template_by_name",
        return_value={"template_id": 1, "template_name": "template-a"},
    )

    with pytest.raises(
        consts_exceptions.DuplicateError, match="Prompt template name already exists"
    ):
        prompt_template_service_module.create_prompt_template_impl(
            prompt_template_request_factory(),
            tenant_id="tenant-1",
            user_id="user-1",
        )


def test_create_prompt_template_impl_persists_user_template(
    mocker, prompt_template_service_module, prompt_template_request_factory
):
    mocker.patch.object(
        prompt_template_service_module,
        "get_prompt_template_by_name",
        return_value=None,
    )
    create_mock = mocker.patch.object(
        prompt_template_service_module,
        "create_prompt_template",
        return_value={"template_id": 9, "template_name": "template-a"},
    )

    result = prompt_template_service_module.create_prompt_template_impl(
        prompt_template_request_factory(),
        tenant_id="tenant-1",
        user_id="user-1",
    )

    create_payload = create_mock.call_args.args[0]
    assert create_payload["tenant_id"] == "tenant-1"
    assert create_payload["user_id"] == "user-1"
    assert create_payload["created_by"] == "user-1"
    assert result["is_system_default"] is False


def test_update_prompt_template_impl_rejects_system_default(
    prompt_template_service_module,
    prompt_template_request_factory,
    prompt_template_models,
):
    _, consts_exceptions = prompt_template_models
    with pytest.raises(
        consts_exceptions.ValidationError,
        match="System default prompt template cannot be updated",
    ):
        prompt_template_service_module.update_prompt_template_impl(
            template_id=0,
            request=prompt_template_request_factory(),
            tenant_id="tenant-1",
            user_id="user-1",
        )


def test_update_prompt_template_impl_updates_existing_template(
    mocker, prompt_template_service_module, prompt_template_request_factory
):
    mocker.patch.object(
        prompt_template_service_module,
        "get_prompt_template_by_id",
        return_value={"template_id": 3, "template_name": "template-a"},
    )
    mocker.patch.object(
        prompt_template_service_module,
        "get_prompt_template_by_name",
        return_value={"template_id": 3, "template_name": "template-a"},
    )
    update_mock = mocker.patch.object(
        prompt_template_service_module,
        "update_prompt_template",
        return_value={"template_id": 3, "template_name": "template-a"},
    )

    result = prompt_template_service_module.update_prompt_template_impl(
        template_id=3,
        request=prompt_template_request_factory(),
        tenant_id="tenant-1",
        user_id="user-1",
    )

    assert update_mock.call_args.kwargs["template_id"] == 3
    assert update_mock.call_args.kwargs["user_id"] == "user-1"
    assert result["is_system_default"] is False


@pytest.mark.parametrize("deleted_count, expected_deleted", [(1, True), (0, False)])
def test_delete_prompt_template_impl_returns_deleted_status(
    mocker, prompt_template_service_module, deleted_count, expected_deleted
):
    mocker.patch.object(
        prompt_template_service_module,
        "get_prompt_template_by_id",
        return_value={"template_id": 5, "template_name": "template-a"},
    )
    mocker.patch.object(
        prompt_template_service_module,
        "delete_prompt_template",
        return_value=deleted_count,
    )

    result = prompt_template_service_module.delete_prompt_template_impl(
        template_id=5,
        tenant_id="tenant-1",
        user_id="user-1",
    )

    assert result == {"template_id": 5, "deleted": expected_deleted}


def test_resolve_prompt_generate_template_falls_back_to_system_default_when_custom_missing(
    mocker, prompt_template_service_module
):
    mocker.patch.object(
        prompt_template_service_module,
        "sync_system_default_prompt_template",
        return_value={
            "template_content_en": {"duty_system_prompt": "system-en-duty"},
            "template_content_zh": {"constraint_system_prompt": "system-zh-constraint"},
        },
    )
    mocker.patch.object(
        prompt_template_service_module,
        "get_prompt_template_by_id",
        return_value=None,
    )

    result = prompt_template_service_module.resolve_prompt_generate_template(
        tenant_id="tenant-1",
        user_id="user-1",
        language=prompt_template_service_module.LANGUAGE["EN"],
        prompt_template_id=8,
    )

    assert result == {
        "duty_system_prompt": "system-en-duty",
        "constraint_system_prompt": "system-zh-constraint",
    }


def test_resolve_prompt_generate_template_merges_custom_and_system_fallbacks(
    mocker, prompt_template_service_module
):
    mocker.patch.object(
        prompt_template_service_module,
        "sync_system_default_prompt_template",
        return_value={
            "template_content_en": {"few_shots_system_prompt": "system-en-few"},
            "template_content_zh": {"user_prompt": "system-zh-user"},
        },
    )
    mocker.patch.object(
        prompt_template_service_module,
        "get_prompt_template_by_id",
        return_value={
            "template_id": 6,
            "template_content_en": {"duty_system_prompt": "custom-en-duty"},
            "template_content_zh": {"constraint_system_prompt": "custom-zh-constraint"},
        },
    )

    result = prompt_template_service_module.resolve_prompt_generate_template(
        tenant_id="tenant-1",
        user_id="user-1",
        language=prompt_template_service_module.LANGUAGE["EN"],
        prompt_template_id=6,
    )

    assert result == {
        "duty_system_prompt": "custom-en-duty",
        "constraint_system_prompt": "custom-zh-constraint",
        "few_shots_system_prompt": "system-en-few",
        "user_prompt": "system-zh-user",
    }


@pytest.mark.parametrize(
    ("template_id", "expected"),
    [
        (None, (None, None)),
        (0, (0, "system_default")),
    ],
)
def test_get_prompt_template_summary_handles_none_and_system_default(
    prompt_template_service_module, template_id, expected
):
    assert (
        prompt_template_service_module.get_prompt_template_summary(
            template_id=template_id,
            tenant_id="tenant-1",
            user_id="user-1",
        )
        == expected
    )


def test_get_prompt_template_summary_raises_when_template_missing(
    mocker, prompt_template_service_module, prompt_template_models
):
    _, consts_exceptions = prompt_template_models
    mocker.patch.object(
        prompt_template_service_module,
        "get_prompt_template_by_id",
        return_value=None,
    )

    with pytest.raises(
        consts_exceptions.NotFoundException, match="Prompt template not found"
    ):
        prompt_template_service_module.get_prompt_template_summary(
            template_id=10,
            tenant_id="tenant-1",
            user_id="user-1",
        )
