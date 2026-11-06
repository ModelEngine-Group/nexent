# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""CS-01/02 effective request comparison uses the real production adapter."""

from unittest.mock import MagicMock

import pytest
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
from nexent.core.model_service.registry import model_service_references

from test.backend.database.model_outlet_helpers import database, statement  # noqa: F401
from test.sdk.core.model_service.conftest import openai_profile as base_openai_profile  # noqa: F401


@pytest.fixture
def openai_profile(base_openai_profile):
    from nexent.core.model_service.profiles.thinking_configuration import configure_outlet_policy
    data = base_openai_profile.model_dump()
    refs = model_service_references()
    for key in ("auth", "code_converter", "native_converter"):
        data["bindings"][key] = refs[key][0].model_dump()
    return configure_outlet_policy(ResolvedModelProfile.model_validate(data))


def changed(db, current, proposed=None, **kwargs):
    return db._connectivity_changed(current, proposed or current,
        {"api_key": "existing", "http_headers": {"X-Gateway": "token"}},
        api_key=kwargs.get("api_key", db._UNSET),
        http_headers=kwargs.get("http_headers", db._UNSET))


@pytest.mark.parametrize("key", ["existing", None, "", "replacement"])
def test_cs01_credentials_reset_only_on_real_change(database, openai_profile, key):
    db, _, _ = database
    assert changed(db, openai_profile, api_key=key) is (key != "existing")


def test_cs01_header_case_order_and_omitted_values_preserve_status(database, openai_profile):
    db, _, _ = database
    assert not changed(db, openai_profile)
    assert not changed(db, openai_profile, http_headers={"x-gateway": "token"})
    assert changed(db, openai_profile, http_headers={})
    assert changed(db, openai_profile, http_headers={"x-gateway": "new"})


@pytest.mark.parametrize("field,value", [("base_url", "https://new.test/v1"),
    ("timeout_seconds", 99), ("ssl_verify", False)])
def test_cs02_connection_changes_reset(database, openai_profile, field, value):
    db, _, _ = database
    data = openai_profile.model_dump()
    data["connection"][field] = value
    assert changed(db, openai_profile, ResolvedModelProfile.model_validate(data))


def test_cs01_metadata_and_context_preserve_status(database, openai_profile):
    db, _, _ = database
    data = openai_profile.model_dump()
    data["identity"]["display_name"] = "renamed"
    data["context_configuration"]["output_reserve_tokens"] = 512
    assert not changed(db, openai_profile, ResolvedModelProfile.model_validate(data))


@pytest.mark.parametrize("parameter,value", [("temperature", 0.3), ("top_p", 0.8),
    ("enable_thinking", True), ("max_output_tokens", 1024)])
def test_cs02_sent_parameters_reset(database, openai_profile, parameter, value):
    db, _, _ = database
    data = openai_profile.model_dump()
    data["parameter_values"][parameter] = value
    if not any(r["key"] == parameter for r in data["parameter_rules"]):
        data["parameter_rules"].append({"key": parameter, "schema": {}, "visible": True,
            "editable": True, "required": False, "allowed_scopes": ["outlet"], "ui_group": "common",
            "owner": "provider", "source": {}, "api_binding": {"path": "/" + parameter,
            "transform_ref": "identity_v1", "transform_version": 1}})
    assert changed(db, openai_profile, ResolvedModelProfile.model_validate(data))


def test_cs01_unsupported_sampling_change_is_not_a_wire_change(database, openai_profile):
    db, _, _ = database
    data = openai_profile.model_dump()
    data["capabilities"]["sampling"]["temperature"]["status"] = "unsupported"
    data["parameter_values"]["temperature"] = 0.2
    current = ResolvedModelProfile.model_validate(data)
    data["parameter_values"]["temperature"] = 0.8
    assert not changed(db, current, ResolvedModelProfile.model_validate(data))


@pytest.mark.parametrize("value,reset", [(0.7, False), (0.4, True)])
def test_cs02_atomic_update_preserves_or_resets_only_status(database, openai_profile, value, reset):
    db, _, _ = database
    data = openai_profile.model_dump()
    data["outlet_id"] = data["connection"]["credential_ref"]["model_id"] = 12
    data["parameter_values"]["temperature"] = 0.7
    current = ResolvedModelProfile.model_validate(data)
    stored = encode_resolved_model_profile(current, registered_references=model_service_references())
    stored.update(api_key="existing", http_headers={"x-gateway": "token"}, connect_status="available")
    session = MagicMock()
    read, write = MagicMock(), MagicMock()
    read.mappings.return_value.first.return_value = stored
    write.scalar_one_or_none.return_value = 2
    session.execute.side_effect = [read, write]
    data["parameter_values"]["temperature"] = value
    proposed = ResolvedModelProfile.model_validate(data)
    db.update_resolved_model_record(proposed, 1, "actor", "tenant",
        registered_references=model_service_references(), http_headers={"X-GATEWAY": "token"},
        api_key="existing", db_session=session)
    params = statement(session, 1).params
    assert params.get("connect_status") == ("not_detected" if reset else None)
    assert params["config_revision"] == 2


def test_cs02_custom_body_boolean_and_number_are_different(database, openai_profile):
    db, _, _ = database
    data = openai_profile.model_dump()
    data["extra_api_parameters"] = [{"path": "/custom_flag", "value": False}]
    current = ResolvedModelProfile.model_validate(data)
    data["extra_api_parameters"][0]["value"] = 0
    assert changed(db, current, ResolvedModelProfile.model_validate(data))
