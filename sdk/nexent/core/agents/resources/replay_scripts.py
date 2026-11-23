# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Correlate an opted-in replay tool call with its bundled script process."""
import hashlib
import re
from contextvars import ContextVar

from nexent.core.agents.resources.replay_tools import argument_digest


active_script_call = ContextVar("active_replay_script_call", default=None)


def identify_script(container, path):
    """Read only the digest from the same container and user as the script."""
    if active_script_call.get() is None:
        return None
    image = container.attrs.get("Image", "")
    if not isinstance(image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        return None
    result = container.exec_run(["sha256sum", "--", path], user="sandbox")
    if result.exit_code != 0 or not result.output:
        return None
    digest = result.output.split(maxsplit=1)[0].decode("ascii", errors="replace")
    return (image, digest) if re.fullmatch(r"[0-9a-f]{64}", digest) else None


def record_script_exit(identity, name, path, argv, code, stdout):
    call = active_script_call.get()
    if call is None or identity is None or type(code) is not int:
        return
    if stdout is None:
        stdout = b""
    if not isinstance(stdout, bytes):
        return
    if "skill_process" in call:
        call["skill_process"] = None
        return
    call["skill_process"] = {
        "skill": argument_digest(name), "path": argument_digest(path), "argv": argument_digest(argv),
        "image": identity[0], "script": identity[1], "exit_code": code,
        "stdout": hashlib.sha256(stdout).hexdigest(),
    }
