# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read the case-owned Run attachment from the actual Runtime mount."""

from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import UUID, uuid5

from contracts.constants.environment import AGENT_WORKSPACE_ROOT


def workspace_digest(token):
    owner = str(uuid5(token, "owner:user"))
    base = Path(AGENT_WORKSPACE_ROOT)
    mount = Path("/mnt/nexent")
    mountpoints = {line.split()[4] for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()}
    if str(mount) not in mountpoints or not base.is_relative_to(mount) or base.resolve() != base:
        raise RuntimeError("The workspace probe requires the test's shared mount")
    records = []
    for attachment in (base / owner).glob("*/inputs/000_peer-restart-input.txt"):
        run_id = attachment.parents[1].name
        if attachment.resolve() != attachment or not attachment.is_file() or UUID(hex=run_id).hex != run_id:
            raise RuntimeError("The workspace probe only reads regular fixture run paths")
        data = f"runtime-peer-restart:{token.hex}\n".encode()
        with attachment.open("rb") as stream:
            actual = stream.read(len(data) + 1)
        assert actual == data, "The live attachment workspace content changed"
        records.append({"run_id": run_id, "sha256": sha256(actual).hexdigest()})
    if not records:
        return None
    record, = records
    return record


if __name__ == "__main__":
    raw_token, = sys.argv[1:]
    token = UUID(hex=raw_token)
    if token.hex != raw_token:
        raise ValueError("Expected a case-owned run token")
    print("SCALING_PEER_WORKSPACE " + json.dumps(workspace_digest(token)))
