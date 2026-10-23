# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Deployment defaults for the Agent Workbench and the Home page.

``ENABLE_AGENT_WORKBENCH`` and ``HIDE_HOME_PAGE`` are resolved once at import
time. A fresh deployment must land on the Agent Workbench with the standalone
Home page hidden, while an explicit falsey value still opts out.

Each case runs in a separate interpreter: the constants are bound at import
time, and a neighbouring ``.env`` file must not leak into the assertion.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Neutralise ``load_dotenv`` before the constants module reads the environment
# so the probe observes ``os.environ`` only.
_PROBE = """
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: None
import backend.consts.const as const
print(int(const.ENABLE_AGENT_WORKBENCH), int(const.HIDE_HOME_PAGE))
"""


def _resolve_flags(tmp_path, override):
    """Return ``(ENABLE_AGENT_WORKBENCH, HIDE_HOME_PAGE)`` as ``"0"``/``"1"``."""
    environment = os.environ.copy()
    environment.pop("ENABLE_AGENT_WORKBENCH", None)
    environment.pop("HIDE_HOME_PAGE", None)
    environment.update(override)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT), environment.get("PYTHONPATH", "")]
    )
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.split()


@pytest.mark.parametrize(
    "override,expected",
    [
        # Success: nothing configured -> workbench on, home page hidden.
        ({}, ("1", "1")),
        # Boundary: the two flags stay independent of each other.
        ({"ENABLE_AGENT_WORKBENCH": "false"}, ("0", "1")),
        ({"HIDE_HOME_PAGE": "false"}, ("1", "0")),
        # Opt-out: an explicit falsey value still disables the flag.
        ({"ENABLE_AGENT_WORKBENCH": "false", "HIDE_HOME_PAGE": "false"}, ("0", "0")),
        # Explicit truthy values keep the new defaults.
        ({"ENABLE_AGENT_WORKBENCH": "on", "HIDE_HOME_PAGE": "yes"}, ("1", "1")),
    ],
)
def test_deployment_flag_defaults(tmp_path, override, expected):
    assert tuple(_resolve_flags(tmp_path, override)) == expected
