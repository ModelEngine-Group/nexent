# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Project public task inputs without exposing injected configuration."""

def runtime_input_contract(resource: dict, injected: set[str]) -> list[dict]:
    """Expose only task inputs. Configuration metadata and defaults stay private."""
    inputs = resource["inputs"]
    properties = inputs.get("properties")
    if not isinstance(properties, dict):
        properties = inputs
    required = inputs.get("required")
    required_names = set(required) if isinstance(required, list) else set()
    private_names = injected | {
        entry["name"] for entry in resource["config"] if isinstance(entry, dict) and "name" in entry
    } | {"kds_list", "index_names", "headers", "authorization"}
    result = []
    for name, spec in properties.items():
        normalized = str(name).casefold().replace("_", "").replace("-", "")
        if name in private_names or any(marker in normalized for marker in ("password", "secret", "token", "apikey")):
            continue
        if isinstance(spec, str):
            spec = {"type": spec}
        if not isinstance(spec, dict) or not isinstance(spec.get("type"), str):
            continue
        result.append({
            "name": name, "type": spec["type"],
            "required": name in required_names or spec.get("required") is True,
            **({"description": spec["description"]} if isinstance(spec.get("description"), str) else {}),
        })
    return result
