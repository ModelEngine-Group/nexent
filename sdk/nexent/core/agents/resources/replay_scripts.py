# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Correlate an opted-in replay tool call with its bundled script process."""
import hashlib
import json
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


# This constant runs under the sandbox user in an isolated interpreter. Only hashes
# and metadata cross the container boundary, including for files outside the rubric.
_OUTPUT_SNAPSHOT = """
import hashlib, json, os, stat, sys
directory = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
seen = {}
total = 0
with os.scandir(directory) as entries:
    for entry in entries:
        if len(seen) >= 32:
            sys.exit(2)
        descriptor = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            total += info.st_size
            if not stat.S_ISREG(info.st_mode) or total > 8 * 1024 * 1024 or info.st_nlink != 1:
                sys.exit(2)
            data = stream.read(info.st_size + 1)
            final = os.fstat(stream.fileno())
            if len(data) != info.st_size or final.st_ctime_ns != info.st_ctime_ns:
                sys.exit(2)
        key = hashlib.sha256(os.fsencode(entry.name)).hexdigest()
        seen[key] = [hashlib.sha256(data).hexdigest(), info.st_ctime_ns, info.st_ino, info.st_mode]
print(json.dumps([os.fstat(directory).st_mtime_ns, seen]))
"""


def output_snapshot(container, directory):
    result = container.exec_run(["python", "-I", "-S", "-c", _OUTPUT_SNAPSHOT, directory], user="sandbox")
    if result.exit_code != 0:
        return None
    return json.loads(result.output)


def file_changes(before, after):
    if before is None or after is None:
        return None
    old_time, old = before
    new_time, new = after
    changes = {k: new[k][0] if k in new else None for k in old.keys() | new.keys() if old.get(k) != new.get(k)}
    # A changed directory with identical membership and no visible file changes
    # may have had transient writes. Its final contents cannot prove a clean run.
    if old_time != new_time and not changes:
        return None
    initial = argument_digest({k: [v[0], v[3]] for k, v in old.items()})
    return {"initial": initial, "changes": changes}


def record_script_exit(identity, name, path, argv, code, stdout, files=None):
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
        "stdout": hashlib.sha256(stdout).hexdigest(), **({"files": files} if files is not None else {}),
    }
