"""Resolve non-secret D4 identity metadata through the shared YAML loader."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.config import load_yaml  # noqa: E402


def user_metadata(identity_id: str) -> dict[str, str]:
    users = load_yaml("users.yaml").get("users")
    if not isinstance(users, list):
        raise ValueError("config/users.yaml must declare users as a list")
    matches = [item for item in users if isinstance(item, dict) and item.get("id") == identity_id]
    if len(matches) != 1:
        raise ValueError("Test user must have exactly one config/users.yaml entry")
    result = {key: matches[0].get(key) for key in ("username", "password_env_key")}
    if any(not isinstance(value, str) or not value.strip() for value in result.values()):
        raise ValueError("Test user requires username and password_env_key")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Exactly one test user ID is required")
    print(json.dumps(user_metadata(sys.argv[1])))
