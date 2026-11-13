# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded conversion subprocesses with process-tree reclamation."""

import os
import signal
import subprocess
from time import monotonic

from nexent.storage.errors import OperationCancelled


def run_conversion_process(command, *, timeout, cancelled=None):
    """Keep the whole process group owned until exit, cancellation or deadline."""
    if cancelled is not None and cancelled.is_set():
        raise OperationCancelled()
    if timeout <= 0:
        raise subprocess.TimeoutExpired(command, timeout)
    options = (
        {"start_new_session": True}
        if os.name != "nt"
        else {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW,
        }
    )
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **options
    )
    deadline = monotonic() + timeout
    try:
        while True:
            if cancelled is not None and cancelled.is_set():
                raise OperationCancelled()
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(
                    timeout=min(remaining, 0.1) if cancelled is not None else remaining
                )
                return subprocess.CompletedProcess(
                    command, process.returncode, stdout, stderr
                )
            except subprocess.TimeoutExpired:
                if monotonic() >= deadline:
                    raise
    except BaseException:
        # LibreOffice may fork soffice.bin; killing only its launcher leaves it alive.
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.communicate(timeout=5)
        raise
