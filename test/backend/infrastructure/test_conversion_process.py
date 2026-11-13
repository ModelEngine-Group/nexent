# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Conversion subprocess ownership, deadlines and process-tree shutdown."""

import os
import subprocess
from threading import Event
from unittest.mock import MagicMock

import pytest
from nexent.storage.errors import OperationCancelled

from infrastructure.file_processing import process as module


@pytest.fixture
def child(mocker):
    process = MagicMock(pid=12345, returncode=0)
    process.communicate.return_value = ("output", "")
    popen = mocker.patch.object(module.subprocess, "Popen", return_value=process)
    mocker.patch.object(module.subprocess, "run")
    mocker.patch.object(module.os, "killpg", create=True)
    return process, popen


def test_success_returns_completed_process(child):
    process, popen = child
    result = module.run_conversion_process(["soffice", "fixture"], timeout=1)
    assert result.returncode == 0 and result.stdout == "output"
    assert popen.call_args.kwargs.get(
        "start_new_session", False
    ) or popen.call_args.kwargs.get("creationflags")
    assert process.communicate.call_args.kwargs["timeout"] > 0


def test_timeout_reclaims_entire_tree_with_bounded_join(child, mocker):
    process, _ = child
    process.communicate.side_effect = [
        subprocess.TimeoutExpired("soffice", 1),
        ("", ""),
    ]
    mocker.patch.object(module, "monotonic", side_effect=[0, 0.1, 2])
    with pytest.raises(subprocess.TimeoutExpired):
        module.run_conversion_process(["soffice"], timeout=1)
    assert process.communicate.call_args.kwargs["timeout"] == 5
    if os.name == "nt":
        assert module.subprocess.run.call_args.args[0] == [
            "taskkill",
            "/PID",
            "12345",
            "/T",
            "/F",
        ]
    else:
        module.os.killpg.assert_called_once_with(12345, module.signal.SIGKILL)


def test_cancelled_before_start_never_launches(child):
    _, popen = child
    cancelled = Event()
    cancelled.set()
    with pytest.raises(OperationCancelled):
        module.run_conversion_process(["soffice"], timeout=1, cancelled=cancelled)
    popen.assert_not_called()


def test_cancel_after_start_reclaims_process(child):
    process, _ = child
    cancelled = Event()

    def communicate(**kwargs):
        if not cancelled.is_set():
            cancelled.set()
            raise subprocess.TimeoutExpired("soffice", 0.1)
        return "", ""

    process.communicate.side_effect = communicate
    with pytest.raises(OperationCancelled):
        module.run_conversion_process(["soffice"], timeout=1, cancelled=cancelled)
    assert process.communicate.call_count == 2
    assert process.communicate.call_args.kwargs["timeout"] == 5


def test_expired_deadline_never_launches(child):
    _, popen = child
    with pytest.raises(subprocess.TimeoutExpired):
        module.run_conversion_process(["soffice"], timeout=0)
    popen.assert_not_called()
