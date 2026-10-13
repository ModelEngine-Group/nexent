"""Credential-free receipts for the fixed deployed fast-path browser journey."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.asset_registry import register_asset
from shared.auth import sign_in
from shared.case_evidence import write_case_evidence
from shared.tool_fastpath_deployed import (
    cleanup_conversation,
    cleanup_fixture,
    control,
    fixture_config,
    history_units,
    responses_for,
    setup,
    verify_artifact,
    verify_result,
    wait_history,
)


CASE_ID = "TFP-D4-001"


def receipt_path():
    root = os.environ.get("RESULT_DIR")
    if not root:
        raise ValueError("RESULT_DIR is required for owned browser fixtures")
    return Path(root) / "runtime" / "tfp-fixture.json"


def save_receipt(receipt):
    path = receipt_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".next")
    # A receipt contains resource IDs and public fixture data, never tokens.
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as handle:
        json.dump(receipt, handle)
        handle.write("\n")
    temporary.replace(path)


def read_receipt():
    return json.loads(receipt_path().read_text())


async def cleanup_receipt(receipt):
    """Attempt every owned cleanup, retaining failed IDs for a safe retry."""
    errors = []
    try:
        identity = await sign_in("tenant_a_admin")
    except Exception as error:
        identity = None
        errors.append(type(error).__name__)
    for run in receipt["runs"]:
        if run.get("cleaned"):
            continue
        try:
            if identity is None:
                raise RuntimeError("Owned conversation cleanup requires authentication")
            await cleanup_conversation(identity, run["conversation_id"], receipt["fixture"]["nonce"])
            run["cleaned"] = True
            save_receipt(receipt)
        except Exception as error:
            errors.append(type(error).__name__)
    if not receipt.get("fixture_cleaned"):
        try:
            await cleanup_fixture(receipt["fixture"], identity=identity)
            receipt["fixture_cleaned"] = True
            save_receipt(receipt)
        except Exception as error:
            errors.append(type(error).__name__)
    if errors:
        raise RuntimeError("Owned browser fixture cleanup failed: " + ", ".join(errors))
    return {"cleaned": True}


async def operate(operation, *, promoted=False, conversation=None):
    if operation == "setup":
        if receipt_path().exists():
            raise ValueError("Do not overwrite an existing owned TFP receipt")
        cfg = fixture_config()
        fixture = await setup(CASE_ID)
        receipt = {"fixture": fixture, "config": cfg, "runs": []}
        try:
            save_receipt(receipt)
        except BaseException as primary:
            try:
                await cleanup_fixture(fixture)
            except Exception:
                primary.add_note("Fixture cleanup failed after receipt creation failure")
            raise
        return {"display": fixture["display"], "agent_id": fixture["agent_id"], "nonce": fixture["nonce"]}
    if operation == "cleanup" and not receipt_path().exists():
        return {"cleaned": True}
    receipt = read_receipt()
    fixture, cfg = receipt["fixture"], receipt["config"]
    if operation == "cleanup":
        return await cleanup_receipt(receipt)
    if operation == "reset":
        return await control(fixture["nonce"], "reset", responses=responses_for(cfg, fixture["nonce"], promoted))
    if not isinstance(conversation, int) or conversation <= 0:
        raise ValueError("A server-issued owned conversation ID is required")
    if operation == "record":
        if any(run["conversation_id"] == conversation for run in receipt["runs"]):
            raise ValueError("A conversation cannot be reused across fast-path scenarios")
        register_asset(
            "owned_conversations",
            str(conversation),
            conversation,
            owner_case_id=CASE_ID,
            cleanup={
                "service": "runtime",
                "identity": "tenant_a_admin",
                "method": "DELETE",
                "path": f"/conversation/{conversation}",
                "allowed_statuses": [200, 404],
            },
        )
        receipt["runs"].append({"conversation_id": conversation, "promoted": promoted})
        save_receipt(receipt)
        return {"recorded": True}
    matches = [run for run in receipt["runs"] if run["conversation_id"] == conversation]
    assert len(matches) == 1 and matches[0]["promoted"] == promoted, "Run is not owned by this scenario"
    identity = await sign_in("tenant_a_admin")
    units = history_units(await wait_history(identity, conversation))
    result = verify_result(units, cfg, fixture["nonce"], promoted)
    state = await control(fixture["nonce"], "state")
    assert state["calls"] == len(responses_for(cfg, fixture["nonce"], promoted))
    artifact = await verify_artifact(identity, units, cfg, fixture["nonce"], CASE_ID) if promoted else None
    write_case_evidence(
        "tfp-browser-history-" + ("promoted" if promoted else "cold"),
        {
            "conversation_id": conversation,
            "result": result,
            "provider_calls": state["calls"],
            "artifact_verified": artifact is not None,
            "source_fingerprints": fixture["fingerprints"],
        },
    )
    return {"verified": True, **result, "artifact": artifact}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["setup", "reset", "record", "inspect", "cleanup"])
    parser.add_argument("--promoted", action="store_true")
    parser.add_argument("--conversation", type=int)
    args = parser.parse_args()
    print(json.dumps(await operate(args.operation, promoted=args.promoted, conversation=args.conversation)))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        # Auth request bodies and trace keys must never appear in bridge output.
        print(json.dumps({"error_type": type(error).__name__}), file=sys.stderr)
        sys.exit(1)
