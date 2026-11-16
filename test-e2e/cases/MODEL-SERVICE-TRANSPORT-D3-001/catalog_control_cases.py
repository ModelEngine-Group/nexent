# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise every selected model and hosted-model control through real HTTP."""
import json

import pytest

from contracts.errors.exceptions import ModelOutletValidationError
from contracts.model import ModelOutletCreateRequest
from management.services.model.profiles import build_outlet_draft, get_model_profile_catalog


def _exercise(peer, request, entries):
    main = request.module
    service, call, _, limiter, journal, _ = main.setup(peer, "normal")
    catalog = get_model_profile_catalog()
    root, _ = peer
    results = []
    for kind, key, model_id, model_selection, provider_selection in entries:
        draft = dict(selection_mode="manual", request_model_id=model_id,
            model_profile=model_selection, provider_profile=provider_selection,
            provider_info={"base_url": root+"/v1?scenario=normal"}, api_key="dummy-loopback")
        profile, _ = build_outlet_draft(ModelOutletCreateRequest(**draft), "loopback-tenant")
        toggle = next((r for r in profile.parameter_rules if r["key"] == "enable_thinking"), None)
        off_effort = next((r for r in profile.parameter_rules if r["key"] == "reasoning_effort"
                           and "none" in r["schema"].get("enum", [])), None)
        can_toggle = bool(toggle and toggle["editable"] and "fixed_value" not in toggle
                          and profile.capabilities.reasoning.can_disable is not False)
        choices = [False, True] if can_toggle else [None]
        for enabled in choices:
            values = {"enable_thinking": enabled} if enabled is not None else {}
            if enabled is None and off_effort:
                values = {"reasoning_effort": "none"}
            actual_profile, _ = build_outlet_draft(ModelOutletCreateRequest(
                **draft, parameter_values=values), "loopback-tenant")
            before = len(main.records(journal))
            result = service.invoke(call, actual_profile)
            captured = main.records(journal)[before:]
            assert result.content_parts == [{"type": "text", "text": "answer"}]
            assert len(captured) == 1 and captured[0]["body"]["model"] == model_id
            body = captured[0]["body"]
            if enabled is not None:
                provider = provider_selection["key"] if provider_selection else None
                if provider in {"deepseek", "volcengine", "volcengine-coding-plan"}:
                    assert body["thinking"]["type"] == ("enabled" if enabled else "disabled")
                else:
                    assert body["enable_thinking"] is enabled
            elif off_effort:
                assert body["reasoning_effort"] == "none"
            results.append({"kind": kind, "key": key, "enabled": enabled,
                            "declared_shutdown": actual_profile.capabilities.reasoning.can_disable,
                            "status": "PASS"})
        if not can_toggle:
            with pytest.raises(ModelOutletValidationError):
                build_outlet_draft(ModelOutletCreateRequest(
                    **draft, parameter_values={"enable_thinking": False}), "loopback-tenant")
        assert not limiter._entries
    assert len({(r["kind"], r["key"]) for r in results}) == len(entries)
    return results


def test_all_selected_custom_model_controls_reach_real_peer(peer, request, tmp_path):
    catalog = get_model_profile_catalog()
    entries = [("model", key, key.rsplit("/", 1)[-1],
                {"key": key, "revision": atom.revision}, None)
               for key, atom in sorted(catalog.models.items())]
    results = _exercise(peer, request, entries)
    (tmp_path / "custom-model-control-matrix.json").write_text(json.dumps(results, indent=2))


def test_all_selected_hosted_model_controls_reach_real_peer(peer, request, tmp_path):
    catalog = get_model_profile_catalog()
    entries = []
    for key, atom in sorted(catalog.provider_models.items()):
        provider, model_id = key.split("/", 1)
        selected = catalog.providers[provider]
        entries.append(("provider_model", key, model_id,
                        {"key": atom.model_profile_key, "revision": catalog.models[atom.model_profile_key].revision}
                        if atom.model_profile_key else None,
                        {"key": provider, "revision": selected.revision}))
    results = _exercise(peer, request, entries)
    (tmp_path / "hosted-model-control-matrix.json").write_text(json.dumps(results, indent=2))
