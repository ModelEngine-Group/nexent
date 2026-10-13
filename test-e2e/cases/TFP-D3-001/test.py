"""Real API/provider/official-tool/Docker/persistence/storage TFP acceptance."""

import time

import pytest
from shared.auth import sign_in
from shared.case_evidence import write_case_evidence
from shared.factories.conversation import _create_conversation
from shared.tool_fastpath_deployed import (
    cleanup_conversation,
    cleanup_fixture,
    control,
    fixture_config,
    history_units,
    responses_for,
    run_agent,
    setup,
    verify_artifact,
    verify_result,
    wait_history,
)
from shared.tool_fastpath_observation import (
    sandbox_events,
    trace_observations,
    verify_sandbox_events,
    verify_warmups,
)


pytestmark = [pytest.mark.case_id("TFP-D3-001"), pytest.mark.stage("D3")]


async def exercise(promoted, *, fail_after_verification=False):
    cfg = fixture_config()
    identity = await sign_in("tenant_a_admin")
    fixture = await setup("TFP-D3-001")
    conversation = None
    primary = None
    started = time.time()
    try:
        responses = responses_for(cfg, fixture["nonce"], promoted)
        await control(fixture["nonce"], "reset", responses=responses)
        conversation = await _create_conversation(identity, "Owned TFP acceptance " + fixture["nonce"])
        events = await run_agent(identity, fixture, conversation)
        persisted = history_units(await wait_history(identity, conversation))
        live = verify_result(events, cfg, fixture["nonce"], promoted)
        assert verify_result(persisted, cfg, fixture["nonce"], promoted) == live
        state = await control(fixture["nonce"], "state")
        assert state["calls"] == len(responses), "Unexpected protocol retry or duplicate model turn"
        observations = await trace_observations(cfg, conversation, live["final"])
        verify_warmups(observations, promoted)
        artifact = (
            await verify_artifact(identity, persisted, cfg, fixture["nonce"], "TFP-D3-001") if promoted else None
        )
        write_case_evidence(
            "tfp-runtime-" + ("promoted" if promoted else "cold"),
            {
                "profile": "mock",
                "source_fingerprints": fixture["fingerprints"],
                "result": live,
                "provider_calls": state["calls"],
                "artifact_verified": artifact is not None,
                "trace_observation_names": [item.get("name") for item in observations],
            },
        )
        if fail_after_verification:
            raise AssertionError("Controlled post-run assertion failure")
    except BaseException as error:
        primary = error
        raise
    finally:
        failures = []
        if conversation is not None:
            try:
                await cleanup_conversation(identity, conversation, fixture["nonce"])
            except Exception as error:
                failures.append(type(error).__name__)
        try:
            records = sandbox_events(cfg, started)
            write_case_evidence("tfp-sandbox-events", records)
            verify_sandbox_events(records, promoted)
        except Exception as error:
            failures.append(type(error).__name__)
        try:
            await cleanup_fixture(fixture, identity=identity)
        except Exception as error:
            failures.append(type(error).__name__)
        if failures:
            if primary is None:
                raise AssertionError("TFP cleanup/observation failed: " + ", ".join(failures))
            primary.add_note("TFP cleanup/observation failed: " + ", ".join(failures))


@pytest.mark.asyncio
async def test_tfp_d3_001_cold():
    await exercise(False)


@pytest.mark.asyncio
async def test_tfp_d3_001_promoted():
    await exercise(True)


@pytest.mark.asyncio
async def test_tfp_d3_001_failed_assertion_cleanup():
    with pytest.raises(AssertionError, match="^Controlled post-run assertion failure$") as caught:
        await exercise(True, fail_after_verification=True)
    # Cleanup errors annotate the primary failure. They must not become an
    # expected-failure pass merely because the controlled assertion was raised.
    assert not getattr(caught.value, "__notes__", []), "Failed-run resource cleanup was incomplete"
