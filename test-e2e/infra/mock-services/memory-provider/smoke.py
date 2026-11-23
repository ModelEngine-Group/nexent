"""Verify the repository's unmodified Mem0Provider against the memory fixture."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import secrets
import sys
import threading
import uuid
from pathlib import Path


def module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


async def verify(repo: Path, url: str, token: str) -> dict:
    import httpx

    sys.path.insert(0, str(repo / "sdk"))
    from nexent.memory.models import MemoryIngestRequest, MemoryIngestUnit, MemorySearchRequest
    from nexent.memory.providers.retry import NonRetryableProviderError, RetryableProviderError

    provider_type = module(repo / "backend/memory_provider_plugins/mem0/provider.py", "mem0_plugin").Mem0Provider
    run_id = uuid.uuid4().hex
    user, marker, org = f"mock-smoke-{run_id}", f"MEMORY-{run_id}", f"org-{run_id}"
    config = {"api_key": token, "base_url": url, "org_id": org, "timeout_seconds": 3}
    provider = provider_type(config)
    headers = {"Authorization": f"Token {token}", "X-Org-Id": org}
    checks = []
    async with httpx.AsyncClient(timeout=5, trust_env=False) as control:
        async def fault(status=200, delay=0):
            response = await control.post(f"{url}/__control/fault", headers=headers, json={
                "user_id": user, "status": status, "delay_seconds": delay,
            })
            response.raise_for_status()

        request = MemorySearchRequest(query=marker, tenant_id=org, user_id=user)
        try:
            assert await provider.search(request) == [], "fixture fabricated a result before ingestion"
            result = await provider.ingest(MemoryIngestRequest(
                tenant_id=org, user_id=user, idempotency_key=run_id,
                units=[MemoryIngestUnit(event_id=run_id, event_type="memory_stored", unit_type="text",
                                        unit_content=f"Test-only memory: {marker}")],
            ))
            assert result.status == "ok" and result.accepted_count == 1 and result.rejected_count == 0
            checks.extend(["empty_search", "ingest_and_event_poll"])
            results = await provider.search(request)
            assert len(results) == 1 and marker in results[0].content and results[0].is_external
            checks.append("search_marker")
            assert await provider.search(request.model_copy(update={"user_id": f"other-{run_id}"})) == []
            other_org = provider_type({**config, "org_id": f"other-{org}"})
            assert await other_org.search(request) == []
            checks.append("user_and_org_isolation")
            fallback = await provider.search(request.model_copy(update={"agent_id": f"agent-{run_id}"}))
            assert len(fallback) == 1 and marker in fallback[0].content
            checks.append("plugin_agent_to_user_fallback")
            wrong = provider_type({**config, "api_key": secrets.token_urlsafe(24)})
            try:
                await wrong.search(request)
                raise AssertionError("incorrect credential was accepted")
            except NonRetryableProviderError as exc:
                assert exc.error.code.value == "unauthorized"
            checks.append("authentication_error_mapping")
            for code, expected in ((403, "forbidden"), (429, "rate_limited"), (503, "provider_error")):
                await fault(code)
                try:
                    await provider.search(request)
                    raise AssertionError(f"injected status {code} was swallowed")
                except (NonRetryableProviderError, RetryableProviderError) as exc:
                    assert exc.error.code.value == expected
                checks.append(f"status_{code}_mapping")
            await fault(delay=2)
            timed = provider_type({**config, "timeout_seconds": 1})
            try:
                await timed.search(request)
                raise AssertionError("injected timeout was swallowed")
            except RetryableProviderError as exc:
                assert exc.error.code.value == "timeout"
            checks.append("timeout_mapping")
            await fault()
            assert marker in (await provider.search(request))[0].content
            checks.append("recovery")
            observed = await control.get(f"{url}/__control/observations", headers=headers, params={"user_id": user})
            observed.raise_for_status()
            assert observed.json()["counts"]["add"] == 1 and observed.json()["counts"]["search"] >= 4
            checks.append("wire_observations")
        finally:
            response = await control.delete(f"{url}/__control/reset", headers=headers, params={"user_id": user})
            response.raise_for_status()
        assert await provider.search(request) == [], "scoped cleanup did not remove the test memory"
        checks.append("cleanup")
    return {"status": "PASS", "profile": "mock", "plugin": "mem0", "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Existing Mock host endpoint; omitted starts an ephemeral loopback server")
    parser.add_argument("--env-file", type=Path, help="Machine-local env file containing the Mock credential")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[4]
    server = thread = None
    try:
        if args.url:
            token = os.environ.get("NEXENT_EXTERNAL_MEMORY_API_KEY", "")
            if args.env_file:
                for raw in args.env_file.read_text(encoding="utf-8").splitlines():
                    if raw.strip().startswith("NEXENT_EXTERNAL_MEMORY_API_KEY="):
                        token = raw.strip().split("=", 1)[1]
            if len(token) < 16:
                raise ValueError("A dedicated Mock credential is required")
            url = args.url.rstrip("/")
        else:
            token = secrets.token_urlsafe(24)
            fixture = module(Path(__file__).with_name("server.py"), "memory_fixture")
            server = fixture.MemoryServer(("127.0.0.1", 0), token)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}"
        print(json.dumps(asyncio.run(verify(repo, url, token))))
        return 0
    except Exception as exc:
        # Avoid printing exceptions containing request URLs, payloads or credentials.
        print(json.dumps({"status": "FAIL", "error_type": type(exc).__name__}))
        return 1
    finally:
        if server:
            server.shutdown()
            server.server_close()
            thread.join(3)


if __name__ == "__main__":
    raise SystemExit(main())
