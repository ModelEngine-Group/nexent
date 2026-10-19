# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Offline ext-attach tests: fakes only, no product, Docker or listeners.

The control plane is faked through ``ext_attach._request``; preparation
failure receipts are written into a temporary RESULT_DIR. Profile-selection
tests read the real PW-KB-AIDP-01 case contract and the repository schema.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ext_attach

# Product-side reachability probes must never touch the network here.
REACHABLE = patch.object(ext_attach, "_reachable", lambda url, timeout=10.0: True)

REPO = ext_attach.repo_root()


def _write_config(home: Path, lock_dir: Path, **overrides) -> None:
    payload = {
        "schema_version": 1,
        "runner_url": "http://127.0.0.1:30090",
        "product_url": "http://ext-knowledge:30090",
        "compose_project": "nexent-mock-ext-knowledge",
        "product_network": "nexent_network",
        "owner_run_id": "run-1",
        "source_revision": "rev-1",
        "build_manifest_sha256": "a" * 64,
        "lock_directory": str(lock_dir),
        "logical_services": ["knowledge-provider", "http-fixture", "model-provider"],
    }
    payload.update(overrides)
    (home / "config").mkdir(parents=True, exist_ok=True)
    lines = ["schema_version: 1"]
    for key, value in payload.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{key}: {json.dumps(value)}")
    (home / "config" / "ext-knowledge.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


class _FakeControl:
    """Record control-plane calls and answer from a scripted route table."""

    def __init__(self, routes=None):
        # routes: {url substring: (status, body) | callable(url, method)}
        self.routes = routes or {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, url, method="GET", payload=None, timeout=10.0):
        self.calls.append((method, url))
        for fragment, result in self.routes.items():
            if fragment in url:
                if callable(result):
                    return result(url, method)
                return result
        raise AssertionError(f"unexpected control-plane call: {method} {url}")

    def posted(self, fragment):
        return [url for method, url in self.calls if method == "POST" and fragment in url]


def _identity(run_id="run-1", revision="rev-1", manifest=None):
    return 200, {
        "service": "ext-knowledge", "run_id": run_id,
        "source_revision": revision,
        "build_manifest_sha256": manifest or "a" * 64,
    }


def _healthy():
    return 200, {
        "status": "ok",
        "services": {name: "ok" for name in ext_attach.ALL_HEALTH_SERVICES},
    }


def _attach_routes(**overrides):
    """Standard attach route table, including the product-side probes."""
    routes = {
        "/_mock/identity": _identity(),
        "/health": _healthy(),
        "/_reset": (200, {"reset": []}),
        "/_wire-log/clear": (200, {"cleared": True}),
        "127.0.0.1:5010": (404, {"detail": "not found"}),
        "127.0.0.1:5014": (404, {"detail": "not found"}),
    }
    routes.update(overrides)
    return routes


class AttachTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ext-attach-test-")
        self.home = Path(self._tmp.name) / "home"
        self.lock_dir = Path(self._tmp.name) / "locks"
        self.result_dir = Path(self._tmp.name) / "result"
        self.result_dir.mkdir(parents=True)
        self._previous_result_dir = os.environ.get("RESULT_DIR")
        os.environ["RESULT_DIR"] = str(self.result_dir)
        _write_config(self.home, self.lock_dir)

    def tearDown(self):
        if self._previous_result_dir is None:
            os.environ.pop("RESULT_DIR", None)
        else:
            os.environ["RESULT_DIR"] = self._previous_result_dir
        self._tmp.cleanup()

    def _attach(self, required=("knowledge-provider",), case_id="CTR-046", record=None):
        record = record or {
            "case_id": case_id,
            "execution": {"required_mock_services": list(required)},
        }
        directory = self.result_dir
        env = {"NEXENT_CONFIG_URL": "http://127.0.0.1:5010",
               "NEXENT_RUNTIME_URL": "http://127.0.0.1:5014"}
        attach = ext_attach.ExtKnowledgeAttach(
            REPO, self.home, directory, env, list(required), case_id, record
        )
        return attach, env

    def _receipt(self):
        path = self.result_dir / "runtime" / "preparation-failure.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def _lock_paths(self):
        return ext_attach.endpoint_lock_paths(ext_attach.load_config(self.home, REPO))


class ConfigValidationTests(AttachTestCase):
    def test_valid_config_loads(self):
        config = ext_attach.load_config(self.home, REPO)
        self.assertEqual(config["owner_run_id"], "run-1")

    def test_url_rules(self):
        for bad in (
            "http://127.0.0.1:30090/",            # trailing slash
            "http://user:pass@127.0.0.1:30090",   # credentials
            "http://127.0.0.1:30090/datamate",    # service path
            "ftp://127.0.0.1:30090",              # scheme
            "http://127.0.0.1:30090?q=1",         # query
        ):
            with self.subTest(bad=bad):
                _write_config(self.home, self.lock_dir, runner_url=bad)
                with self.assertRaises(ext_attach.AttachError):
                    ext_attach.load_config(self.home, REPO)

    def test_host_mode_equal_addresses_are_allowed(self):
        # A host-mode product (backend outside the compose network) reaches the
        # mock through the same published loopback port as the runner.
        _write_config(self.home, self.lock_dir, product_url="http://127.0.0.1:30090")
        config = ext_attach.load_config(self.home, REPO)
        self.assertEqual(config["runner_url"], config["product_url"])

    def test_lock_directory_must_be_absolute_and_outside_home(self):
        _write_config(self.home, self.lock_dir, lock_directory="relative/locks")
        with self.assertRaises(ext_attach.AttachError):
            ext_attach.load_config(self.home, REPO)
        _write_config(self.home, self.lock_dir, lock_directory=str(self.home / "locks"))
        with self.assertRaises(ext_attach.AttachError):
            ext_attach.load_config(self.home, REPO)

    def test_unknown_logical_service_rejected_by_schema(self):
        _write_config(self.home, self.lock_dir, logical_services=["not-a-service"])
        with self.assertRaises(ext_attach.AttachError):
            ext_attach.load_config(self.home, REPO)

    def test_missing_config_is_reported(self):
        problems = ext_attach.config_problems(self.home, REPO)
        self.assertEqual(problems, [])
        (self.home / "config" / "ext-knowledge.yaml").unlink()
        self.assertEqual(ext_attach.config_problems(self.home, REPO), [])


class AttachLifecycleTests(AttachTestCase):
    def test_attach_success_resets_locks_and_exports_env(self):
        attach, env = self._attach()
        fake = _FakeControl(_attach_routes())
        with REACHABLE, patch.object(ext_attach, "_request", fake):
            attach.attach()
            self.assertEqual(attach.release(), 0)
        self.assertEqual(env["NEXENT_EXT_KNOWLEDGE_RUNNER_URL"], "http://127.0.0.1:30090")
        self.assertEqual(env["NEXENT_EXT_KNOWLEDGE_PRODUCT_URL"], "http://ext-knowledge:30090")
        # Baseline reset at attach AND restore reset at release.
        self.assertEqual(len(fake.posted("/_reset")), 2)
        _, state_path = self._lock_paths()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertTrue(state["released"])
        evidence = json.loads((self.result_dir / "runtime" / "ext-knowledge-attach.json").read_text(encoding="utf-8"))
        self.assertTrue(evidence["attached"])
        self.assertEqual(evidence["served_services"], ["knowledge-provider"])
        self.assertEqual(evidence["identity"]["run_id"], "run-1")

    def test_foreign_identity_blocks_without_reset(self):
        attach, _ = self._attach()
        fake = _FakeControl({"/_mock/identity": _identity(run_id="someone-else")})
        with REACHABLE, patch.object(ext_attach, "_request", fake):
            with self.assertRaises(RuntimeError) as ctx:
                attach.attach()
        self.assertIn("foreign", str(ctx.exception))
        self.assertEqual(fake.posted("/_reset"), [])
        receipt = self._receipt()
        self.assertEqual(receipt["result"], "BLOCKED_BY_DEPENDENCY")
        _, state_path = self._lock_paths()
        self.assertFalse(state_path.exists())

    def test_missing_run_id_blocks(self):
        attach, _ = self._attach()
        fake = _FakeControl({"/_mock/identity": _identity(run_id="")})
        with REACHABLE, patch.object(ext_attach, "_request", fake):
            with self.assertRaises(RuntimeError):
                attach.attach()
        self.assertEqual(self._receipt()["result"], "BLOCKED_BY_DEPENDENCY")

    def test_unhealthy_route_set_blocks(self):
        attach, _ = self._attach()
        degraded = _healthy()[1]
        degraded["services"]["fault"] = "error"
        fake = _FakeControl({
            "/_mock/identity": _identity(),
            "/health": (200, degraded),
        })
        with REACHABLE, patch.object(ext_attach, "_request", fake):
            with self.assertRaises(RuntimeError) as ctx:
                attach.attach()
        self.assertIn("fault", str(ctx.exception))
        # No mutations were attempted: the state file is marked released so
        # the next attach is not blocked by a phantom unknown state.
        self.assertEqual(fake.posted("/_reset"), [])
        _, state_path = self._lock_paths()
        self.assertTrue(json.loads(state_path.read_text(encoding="utf-8"))["released"])

    def _state_at_lock_release(self, attach_callable):
        """Run a failing attach and snapshot the state file at unlock time."""
        _, state_path = self._lock_paths()
        observed = {}
        original_release = ext_attach._FileLock.release

        def release_with_snapshot(lock):
            observed["state"] = json.loads(state_path.read_text(encoding="utf-8"))
            return original_release(lock)

        with patch.object(ext_attach._FileLock, "release", release_with_snapshot):
            with self.assertRaises(RuntimeError):
                attach_callable()
        self.assertIn("state", observed)
        return observed["state"]

    def test_failure_before_mutations_marks_released_before_unlock(self):
        attach, _ = self._attach()
        degraded = _healthy()[1]
        degraded["services"]["fault"] = "error"
        fake = _FakeControl({"/_mock/identity": _identity(), "/health": (200, degraded)})
        with REACHABLE, patch.object(ext_attach, "_request", fake):
            state = self._state_at_lock_release(attach.attach)
        # The rewrite must land while the lock is still held: a concurrent
        # attacher can then never read the pre-failure released=False
        # between the unlock and the rewrite.
        self.assertTrue(state["released"])
        self.assertEqual(self._receipt()["result"], "BLOCKED_BY_DEPENDENCY")

    def test_failure_after_mutations_keeps_unknown_state_before_unlock(self):
        attach, _ = self._attach()
        fake = _FakeControl(_attach_routes(**{"/_reset": (500, {"detail": "boom"})}))
        with REACHABLE, patch.object(ext_attach, "_request", fake):
            state = self._state_at_lock_release(attach.attach)
        # A failed reset means the instance state is unknown: the next
        # runner must be blocked by the state file, never by a phantom
        # clean state.
        self.assertFalse(state["released"])
        self.assertEqual(self._receipt()["result"], "BLOCKED_BY_DEPENDENCY")

    def test_unreachable_product_stack_blocks(self):
        attach, _ = self._attach()
        routes = {
            "/_mock/identity": _identity(),
            "/health": _healthy(),
        }
        with patch.object(ext_attach, "_request", _FakeControl(routes)),                 patch.object(ext_attach, "_reachable", lambda url, timeout=10.0: False):
            with self.assertRaises(RuntimeError) as ctx:
                attach.attach()
        self.assertIn("not reachable", str(ctx.exception))
        self.assertEqual(self._receipt()["result"], "BLOCKED_BY_DEPENDENCY")

    def test_unreachable_runner_blocks(self):
        attach, _ = self._attach()

        def unreachable(url, method="GET", payload=None, timeout=10.0):
            raise ext_attach.AttachError(f"GET {url} failed: URLError")

        with REACHABLE, patch.object(ext_attach, "_request", unreachable):
            with self.assertRaises(RuntimeError):
                attach.attach()
        self.assertEqual(self._receipt()["result"], "BLOCKED_BY_DEPENDENCY")

    def test_unserved_logical_service_blocks(self):
        attach, _ = self._attach(required=("model-provider",))
        _write_config(self.home, self.lock_dir, logical_services=["knowledge-provider"])
        with REACHABLE, patch.object(ext_attach, "_request", _FakeControl()):
            with self.assertRaises(RuntimeError) as ctx:
                attach.attach()
        self.assertIn("does not serve", str(ctx.exception))
        self.assertEqual(self._receipt()["result"], "BLOCKED_BY_DEPENDENCY")

    def test_lock_contention_blocks(self):
        attach, _ = self._attach()
        fake = _FakeControl({
            "/_mock/identity": _identity(),
            "/health": _healthy(),
        })

        def busy_acquire(self):
            raise ext_attach.AttachError("the ext-knowledge instance is locked by another runner")

        with REACHABLE, patch.object(ext_attach, "_request", fake), \
                patch.object(ext_attach._FileLock, "acquire", busy_acquire):
            with self.assertRaises(RuntimeError) as ctx:
                attach.attach()
        self.assertIn("locked by another runner", str(ctx.exception))

    def test_unclean_previous_state_blocks_until_recovery(self):
        attach, _ = self._attach()
        _, state_path = self._lock_paths()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"run_id": "run-0", "case_id": "OTHER", "released": False}), encoding="utf-8")
        fake = _FakeControl({"/_mock/identity": _identity()})
        with REACHABLE, patch.object(ext_attach, "_request", fake):
            with self.assertRaises(RuntimeError) as ctx:
                attach.attach()
        self.assertIn("not released cleanly", str(ctx.exception))
        self.assertEqual(fake.posted("/_reset"), [])

    def test_release_failure_marks_unknown_state(self):
        attach, _ = self._attach()
        routes = _attach_routes()
        fake = _FakeControl(routes)
        with REACHABLE, patch.object(ext_attach, "_request", fake):
            attach.attach()
            # The release reset now fails with a server error.
            routes["/_reset"] = (502, {"detail": "AIDP reset incomplete"})
            self.assertEqual(attach.release(), 2)
        _, state_path = self._lock_paths()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertFalse(state["released"])
        problems = json.loads((self.result_dir / "runtime" / "ext-knowledge-release.json").read_text(encoding="utf-8"))
        self.assertTrue(problems["problems"])

    def test_undeclared_case_touches_nothing(self):
        attach, env = self._attach(required=[])
        fake = _FakeControl()
        with REACHABLE, patch.object(ext_attach, "_request", fake):
            attach.attach()
            self.assertEqual(attach.release(), 0)
        self.assertEqual(fake.calls, [])
        self.assertNotIn("NEXENT_EXT_KNOWLEDGE_RUNNER_URL", env)
        evidence = json.loads((self.result_dir / "runtime" / "ext-knowledge-attach.json").read_text(encoding="utf-8"))
        self.assertFalse(evidence["attached"])

    def test_collect_evidence_writes_wire_and_control(self):
        attach, _ = self._attach()
        wire = {"records": [{"service": "datamate", "method": "GET", "path": "/api/knowledge-base/list",
                             "status_code": 200, "duration_ms": 1.2, "request_body": None}],
                "retained": 1, "dropped": 0}
        fake = _FakeControl(_attach_routes(
            **{
                "/_wire-log": (200, wire),
                "/_mock/state": (200, {"faults": {"fail_remaining": {}}, "identity": _identity()[1]}),
            }
        ))
        with REACHABLE, patch.object(ext_attach, "_request", fake):
            attach.attach()
            attach.collect_evidence()
        lines = (self.result_dir / "runtime" / "ext-knowledge-wire.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(lines[0])["type"], "wire-stats")
        self.assertEqual(json.loads(lines[1])["path"], "/api/knowledge-base/list")
        control = json.loads((self.result_dir / "runtime" / "ext-knowledge-control.json").read_text(encoding="utf-8"))
        self.assertEqual(control["identity"]["run_id"], "run-1")


class EndpointLockTests(unittest.TestCase):
    def test_normalized_endpoints_share_one_lock(self):
        first = ext_attach.endpoint_lock_paths({
            "runner_url": "http://127.0.0.1:30090", "lock_directory": str(Path(tempfile.gettempdir()))
        })
        second = ext_attach.endpoint_lock_paths({
            "runner_url": "http://127.0.0.1:30090/", "lock_directory": str(Path(tempfile.gettempdir()))
        })
        # Both normalize to the same endpoint stem (the trailing slash never
        # reaches here — config validation rejects it — but host:port casing
        # and equivalent spellings must collapse to one lock).
        self.assertEqual(first[0].name, second[0].name)

    def test_different_endpoints_use_distinct_locks(self):
        first = ext_attach.endpoint_lock_paths({
            "runner_url": "http://127.0.0.1:30090", "lock_directory": str(Path(tempfile.gettempdir()))
        })
        second = ext_attach.endpoint_lock_paths({
            "runner_url": "http://127.0.0.1:30091", "lock_directory": str(Path(tempfile.gettempdir()))
        })
        self.assertNotEqual(first[0], second[0])


if __name__ == "__main__":
    unittest.main()
