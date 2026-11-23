# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Check a registered MCP image pair with an operator-selected trusted Nexent Management image."""

import argparse
from contextlib import ExitStack
import io
import json
import tarfile
from time import time
from uuid import uuid4

import docker
from pydantic import TypeAdapter

from contracts.tool_repair import ImageId
from management.db.evaluation import tool_builds as db
from management.services.evaluation.tool_builds import verification_plan
from nexent.core.agents.resources.replay_tools import argument_digest


def _case_archive(request):
    data = json.dumps(request, ensure_ascii=False, allow_nan=False).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as archive:
        info = tarfile.TarInfo("nexent-tool-case.json")
        info.size, info.mode = len(data), 0o444
        archive.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _remove(container):
    try:
        container.remove(force=True, v=True)
    except docker.errors.NotFound:
        pass


_LABEL = "nexent.evolution.tool-check"
_EXPIRES = "nexent.evolution.tool-check-expires"


def _clear_expired(client):
    now = int(time())
    expired = []
    for container in client.containers.list(all=True, filters={"label": _LABEL + "=isolated-v1"}):
        deadline = container.labels.get(_EXPIRES, "")
        if deadline.isascii() and deadline.isdigit() and len(deadline) <= 12 and int(deadline) <= now:
            expired.append(container)
    # Detach the sidecar before removing the service that owns its network namespace.
    for container in sorted(expired, key=lambda c: c.attrs.get("HostConfig", {}).get("NetworkMode") == "none"):
        _remove(container)


def _owned(stack, client, image, **options):
    container = client.containers.create(
        image,
        detach=True,
        cap_drop=["ALL"],
        security_opt=["no-new-privileges"],
        pids_limit=128,
        mem_limit="512m",
        nano_cpus=1_000_000_000,
        labels={_LABEL: "isolated-v1", _EXPIRES: str(int(time()) + 900)},
        **options,
    )
    stack.callback(_remove, container)
    return container


def _observe(client, verifier, image, manifest, rule):
    # Images are selected by content ID. Never pull an unreviewed tag, use a host mount or publish a port.
    local = client.images.get(image)
    if local.id != image:
        raise ValueError("Fixture image ID mismatch")
    initial = json.dumps(rule["expected_mcp_reply"]["fixture"]["initial"], ensure_ascii=False)
    request = {k: manifest[k] for k in ("port", "path", "transport")}
    request.update(nonce=uuid4().hex, rule=rule)
    with ExitStack() as stack:
        fixture = _owned(
            stack,
            client,
            image,
            network_mode="none",
            read_only=True,
            tmpfs={"/tmp": "rw,nosuid,nodev,size=64m"},
            environment={"NEXENT_EVAL_FIXTURE_INITIAL": initial},
            user="65534:65534",
        )
        fixture.start()
        fixture.reload()
        if fixture.attrs["Image"] != image or fixture.attrs["HostConfig"]["NetworkMode"] != "none":
            raise ValueError("Fixture image or isolation mismatch")
        # The candidate and the judge share only loopback. Expected results are written only to the judge.
        probe = _owned(
            stack,
            client,
            verifier,
            network_mode="container:" + fixture.id,
            entrypoint=["python", "-m", "management.cli.tool_build_probe"],
            command=[],
            user="65534:65534",
        )
        if not probe.put_archive("/tmp", _case_archive(request)):
            raise RuntimeError("Could not stage the approved case")
        probe.start()
        finished = probe.wait(timeout=55)
        probe.reload()
        fixture.reload()
        if (
            finished["StatusCode"] != 0
            or probe.attrs["Image"] != verifier
            or fixture.attrs["Image"] != image
            or fixture.attrs["RestartCount"]
            or not fixture.attrs["State"]["Running"]
        ):
            raise RuntimeError("The verified fixture or its judge did not complete")
        lines = probe.logs(stdout=True, stderr=False, tail=1).splitlines()
        if len(lines) != 1 or len(lines[0]) > 16384:
            raise ValueError("The trusted judge did not return a bounded observation")
        report = json.loads(lines[0])
        if report.get("nonce") != request["nonce"] or report.get("rule_digest") != argument_digest(rule):
            raise ValueError("The trusted judge observed a different case")
        return {**report["result"], "image": image}


def compare(check, base, result):
    """Require the image at baseline to reproduce the original wire result and business state."""
    original = check["original"]
    old = base.get("observation") or {}
    expected_old = "fail" if check["label"] == "failure" else "pass"
    if base["status"] == "missing_evidence":
        return "missing_evidence"
    if (
        not old.get("input_matches")
        or base["status"] != expected_old
        or any(old.get(k) != v for k, v in original.items())
    ):
        return "baseline_mismatch"
    if result["status"] == "missing_evidence":
        return "missing_evidence"
    if result["status"] != "pass":
        return "regression" if expected_old == "pass" else "unfixed"
    new = result.get("observation") or {}
    if (
        not all(new.get(k) == old[k] for k in ("remote", "kind", "inputs", "before"))
        or not new.get("input_matches")
        or not new.get("reply_matches")
        or not new.get("state_matches")
    ):
        return "missing_evidence"
    return "corrected" if expected_old == "fail" else "protected"


def verify_registered_build(tenant, bid, verifier, client):
    verifier = TypeAdapter(ImageId).validate_python(verifier)
    manifest, plan, digest = verification_plan(tenant, bid)
    if (
        verifier in (manifest["base_image"], manifest["result_image"])
        or client.images.get(verifier).id != verifier
    ):
        raise ValueError("Choose a separate trusted verifier image installed on this Docker host")
    _clear_expired(client)
    rows = []
    for check in plan["checks"]:
        arms = {}
        for arm in ("base", "result"):
            if verification_plan(tenant, bid)[2] != digest:
                raise ValueError("Caller approvals or the verification plan changed")
            image = manifest[arm + "_image"]
            try:
                arms[arm] = _observe(client, verifier, image, manifest, check["rule"])
            except Exception as exc:
                arms[arm] = {"status": "missing_evidence", "reasons": [type(exc).__name__], "image": image}
        rows.append(
            {
                "label": check["label"],
                "rule_digest": argument_digest(check["rule"]),
                "arms": arms,
                "outcome": compare(check, arms["base"], arms["result"]),
            }
        )
    if verification_plan(tenant, bid)[2] != digest:
        raise ValueError("The verification plan or its approvals changed before recording results")
    outcomes = {r["outcome"] for r in rows}
    status = "passed"
    if plan["uncovered"] or outcomes.intersection({"missing_evidence", "baseline_mismatch"}):
        status = "insufficient"
    if outcomes.intersection({"unfixed", "regression"}):
        status = "failed"
    report = {
        "status": status,
        "verifier_image": verifier,
        "plan_digest": digest,
        "missing_caller_count": len(plan["uncovered"]),
        "cases": rows,
    }
    run_id = db.save_run(tenant, bid, digest, report)
    return {"run_id": run_id, **report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--build", type=int, required=True)
    parser.add_argument("--verifier-image", required=True)
    args = parser.parse_args()
    client = docker.from_env()
    try:
        report = verify_registered_build(args.tenant, args.build, args.verifier_image, client)
    finally:
        client.close()
    print(json.dumps({k: report[k] for k in ("run_id", "status", "plan_digest", "missing_caller_count")}))
    return {"passed": 0, "failed": 1, "insufficient": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
