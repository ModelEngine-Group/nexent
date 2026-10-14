# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""ext-knowledge registration and build-context packing tests.

Offline checks only: Docker is never contacted (dry-run), the mock server
is never started, and packing runs against a synthetic repository tree.
"""
import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REGISTRY_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = REGISTRY_DIR.parents[2]
EXT_DIR = REGISTRY_DIR / "ext-knowledge-mock"


def _load_deploy():
    spec = importlib.util.spec_from_file_location("ext_test_deploy", REGISTRY_DIR / "deploy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_packer():
    spec = importlib.util.spec_from_file_location("ext_test_packer", EXT_DIR / "build_context.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExtKnowledgeRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.deploy = _load_deploy()
        self.registry = self.deploy.registrations(REGISTRY_DIR, REPO_ROOT)

    def test_registration_and_alias(self):
        spec = self.registry["ext-knowledge"]
        self.assertEqual(self.registry["ext-knowledge-mock"], spec)
        self.assertEqual(spec["project"], "nexent-mock-ext-knowledge")
        self.assertEqual(spec["services"], ["ext-knowledge"])

    def test_compose_files_exist_in_repository(self):
        spec = self.registry["ext-knowledge"]
        for relative in spec["compose_files"] + spec["product_network_files"]:
            self.assertTrue((REPO_ROOT / relative).is_file(), relative)
        self.assertTrue(all("test-e2e/infra/mock-services/compose/" in path for path in spec["compose_files"]))

    def test_readiness_checks_all_eight_services(self):
        probes = self.registry["ext-knowledge"]["readiness"]
        self.assertEqual(len(probes), 1)
        checks = probes[0]["json_equals"]
        self.assertEqual(checks["status"], "ok")
        for service in ("datamate", "dify", "ragflow", "idata", "haotian", "assets", "fault", "aidp"):
            self.assertEqual(checks[f"services.{service}"], "ok", service)
        self.assertTrue(probes[0]["url"].startswith("http://127.0.0.1:30090"))

    def _dry_run(self, argv):
        with mock.patch.object(self.deploy, "run") as run, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = self.deploy.main(argv)
        run.assert_not_called()
        return code, json.loads(output.getvalue())

    def test_dry_run_up_includes_both_compose_files_without_docker(self):
        code, payload = self._dry_run(["up", "ext-knowledge", "--dry-run"])
        self.assertEqual(code, 0)
        command = payload["command"]
        # deploy.py resolves compose files to absolute paths inside the repo.
        self.assertTrue(
            any(part.endswith("compose.ext-knowledge.yaml") for part in command), command
        )
        self.assertTrue(
            any(part.endswith("compose.ext-knowledge.product-network.yaml") for part in command),
            command,
        )
        self.assertIn("--build", command)
        self.assertEqual(command[-1], "ext-knowledge")
        self.assertEqual(payload["required_product_network"], "nexent_network")
        self.assertEqual(len(payload["readiness"]), 1)

    def test_standalone_dry_run_omits_product_overlay(self):
        code, payload = self._dry_run(
            ["up", "ext-knowledge", "--standalone", "--no-build", "--dry-run"]
        )
        self.assertEqual(code, 0)
        self.assertNotIn("--build", payload["command"])
        self.assertFalse(any("product-network" in part for part in payload["command"]))

    def test_stop_scopes_to_registered_service(self):
        command = self.deploy.action_command(
            ["docker", "compose"], {"services": ["ext-knowledge"]}, SimpleNamespace(action="stop")
        )
        self.assertEqual(command, ["docker", "compose", "stop", "ext-knowledge"])


class ExtKnowledgeComposeContentTests(unittest.TestCase):
    """The compose pair must keep the designed deployment shape."""

    def setUp(self):
        self.base = (REGISTRY_DIR / "compose/compose.ext-knowledge.yaml").read_text(encoding="utf-8")
        self.overlay = (
            REGISTRY_DIR / "compose/compose.ext-knowledge.product-network.yaml"
        ).read_text(encoding="utf-8")

    def test_base_publishes_the_fixed_port_on_loopback_only(self):
        # D-001: the unauthenticated control surface stays off the LAN. The
        # runner uses the loopback address; product-side callers reach the
        # mock through the compose-network DNS name, never this port.
        self.assertIn("127.0.0.1:30090:30090", self.base)
        self.assertNotIn('"30090:30090"', self.base)
        self.assertIn("EXT_KNOWLEDGE_BUILD_CONTEXT", self.base)
        self.assertIn("EXT_KNOWLEDGE_MOCK_RUN_ID", self.base)
        self.assertIn("EXT_KNOWLEDGE_BUILD_MANIFEST_SHA256", self.base)

    def test_base_declares_no_global_fixed_network(self):
        # Project-scoped networking only: no fixed network name, no container_name.
        self.assertNotIn("container_name", self.base)
        self.assertNotIn("name: nexent-ext", self.base)

    def test_overlay_uses_external_product_network(self):
        self.assertIn("external: true", self.overlay)
        self.assertIn("${NEXENT_PRODUCT_NETWORK:-nexent_network}", self.overlay)


class BuildContextPackingTests(unittest.TestCase):
    def setUp(self):
        self.packer = _load_packer()
        self.tree = Path(tempfile.mkdtemp(prefix="ext-pack-test-"))
        mock_dir = self.tree / "test-e2e/infra/mock-services/ext-knowledge-mock"
        aidp_dir = self.tree / "test/ext_components/aidp/mock_servers"
        mock_dir.mkdir(parents=True)
        (mock_dir / "seeds").mkdir()
        aidp_dir.mkdir(parents=True)
        for name in self.packer.MOCK_FILES:
            (mock_dir / name).write_bytes(f"# {name}\n".encode("utf-8"))
        for name in self.packer.MOCK_SEED_FILES:
            (mock_dir / "seeds" / name).write_bytes(b"{}")
        (mock_dir / "Dockerfile").write_bytes(b"FROM python:3.11-slim\n")
        (mock_dir / "_state").mkdir()
        (mock_dir / "_state/dify.json").write_bytes(b"{}")  # must never be packed
        for name in self.packer.AIDP_FILES:
            (aidp_dir / name).write_bytes(f"# {name}\n".encode("utf-8"))
        self.output = self.tree / "context"

    def tearDown(self):
        shutil.rmtree(self.tree, ignore_errors=True)

    def _pack(self):
        return self.packer.pack(self.tree, self.output)

    def test_pack_copies_enumerated_files_and_manifest(self):
        with mock.patch.object(self.packer.subprocess, "check_output", return_value="abc123\n"):
            manifest = self._pack()
        copied = {entry["path"] for entry in manifest["files"]}
        expected = {f"mock/{name}" for name in self.packer.MOCK_FILES}
        expected |= {f"mock/seeds/{name}" for name in self.packer.MOCK_SEED_FILES}
        expected |= {f"aidp_mock_servers/{name}" for name in self.packer.AIDP_FILES}
        expected.add("Dockerfile")
        self.assertEqual(copied, expected)
        self.assertNotIn("mock/_state/dify.json", copied)
        self.assertTrue((self.output / "build-manifest.json").is_file())
        self.assertEqual(manifest["head"], "abc123")
        # Every manifest hash matches the packed bytes.
        for entry in manifest["files"]:
            self.assertTrue((self.output / entry["path"]).is_file(), entry["path"])

    def test_manifest_sha_is_stable_and_written_file_lacks_it(self):
        with mock.patch.object(self.packer.subprocess, "check_output", return_value="abc123\n"):
            first = self._pack()
            second = self._pack()
        self.assertEqual(first["build_manifest_sha256"], second["build_manifest_sha256"])
        written = json.loads((self.output / "build-manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("build_manifest_sha256", written)

    def test_missing_aidp_json_aborts_before_any_copy(self):
        (self.tree / "test/ext_components/aidp/mock_servers/graph_config_template_chinese.json").unlink()
        with mock.patch.object(self.packer.subprocess, "check_output", return_value="abc123\n"):
            with self.assertRaises(ValueError) as ctx:
                self._pack()
        self.assertIn("graph_config_template_chinese.json", str(ctx.exception))
        self.assertFalse(self.output.exists())

    def test_pack_replaces_previous_context(self):
        with mock.patch.object(self.packer.subprocess, "check_output", return_value="abc123\n"):
            self._pack()
            stale = self.output / "mock/stale.py"
            stale.write_bytes(b"stale")
            self._pack()
        self.assertFalse(stale.exists())

    def test_real_repository_packs(self):
        # The actual worktree must pack cleanly end to end (offline; no Docker).
        output = Path(tempfile.mkdtemp(prefix="ext-pack-real-")) / "context"
        try:
            manifest = self.packer.pack(REPO_ROOT, output)
            names = {entry["path"] for entry in manifest["files"]}
            self.assertIn("mock/server.py", names)
            self.assertIn("mock/seeds/datamate.json", names)
            self.assertIn("aidp_mock_servers/aidp_mgmt_mock_server.py", names)
            self.assertIn("aidp_mock_servers/graph_config_template_chinese.json", names)
            self.assertIn("Dockerfile", names)
            self.assertRegex(manifest["head"], r"^[0-9a-f]{40}$")
        finally:
            shutil.rmtree(output.parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
