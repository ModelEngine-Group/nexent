# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Reuse the owned file-assistant fixture and change only its root Core."""
import importlib.util
import json
import sys
from pathlib import Path

import httpx


mode, filename, helper_path = sys.argv[1:4]
if mode == "select-core":
    state = json.loads(Path(filename).read_text())
    core = sys.argv[4]
    assert core in {"smolagents", "jiuwen"}
    assert state["agent_id"] in state["owned_agents"] and state["agent_id"] != state["source"]
    with httpx.Client(base_url="http://nexent-config:5010", trust_env=False, timeout=90,
                      headers={"Authorization": "Bearer " + state["access_token"]}) as client:
        response = client.post("/agent/update", json={"agent_id": state["agent_id"],
                               **state["copied_fields"], "agent_core": core})
        assert response.status_code == 200
        response = client.post(f"/agent/{state['agent_id']}/publish", json={"version_name": "Retry history " + core})
        assert response.status_code == 200
    print(json.dumps({"configured_core": core}))
else:
    spec = importlib.util.spec_from_file_location("owned_file_fixture", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    sys.argv = [sys.argv[0], mode, filename, *sys.argv[4:]]
    helper.main()
