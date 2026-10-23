"""Dispatcher tests without Docker mutations or external services."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "deploy.py"
SPEC = importlib.util.spec_from_file_location("mock_deploy", MODULE)
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


class DeploymentTests(unittest.TestCase):
    def test_registration_alias(self):
        registry = deploy.registrations()
        self.assertIs(registry["a2a"], registry["a2a-agent"])

    def test_dry_run_does_not_access_docker(self):
        with patch.object(deploy, "run") as run, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(deploy.main(["up", "A2A", "--dry-run"]), 0)
            run.assert_not_called()
        self.assertIn("--build", json.loads(output.getvalue())["command"])

    def test_standalone(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(deploy.main(["up", "a2a", "--standalone", "--no-build", "--dry-run"]), 0)
        command = json.loads(output.getvalue())["command"]
        self.assertNotIn("--build", command)
        self.assertFalse(any("product-network.yaml" in part for part in command))

    def test_stop_is_scoped(self):
        args = SimpleNamespace(action="stop")
        command = deploy.action_command(["docker", "compose"], {"services": ["only-mock"]}, args)
        self.assertEqual(command, ["docker", "compose", "stop", "only-mock"])

    def test_unknown_service(self):
        with patch.object(deploy, "run") as run, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(deploy.main(["up", "missing"]), 1)
            run.assert_not_called()

    def test_paths_rejected(self):
        for value in ("/tmp/outside", "C:/outside.yaml", "../../outside.yaml"):
            with self.subTest(value=value), self.assertRaises(deploy.DeploymentError):
                deploy.repo_file(value)

    def test_extension_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "sample").mkdir()
            (root / "compose.yaml").touch()
            spec = {"schema_version": 1, "id": "sample", "project": "mock-sample",
                    "compose_files": ["compose.yaml"], "services": ["sample"],
                    "readiness": [{"url": "http://127.0.0.1:18080/readyz"}]}
            (root / "sample/deployment.json").write_text(json.dumps(spec), encoding="utf-8")
            self.assertIn("sample", deploy.registrations(root, root))

    def check_states(self, daemon_running, init_status, init_exit=0):
        objects = [{"Config": {"Labels": {"com.docker.compose.service": "daemon"}},
                    "State": {"Running": daemon_running, "Status": "exited", "ExitCode": 0}},
                   {"Config": {"Labels": {"com.docker.compose.service": "init"}},
                    "State": {"Running": init_status == "running", "Status": init_status, "ExitCode": init_exit}}]
        with patch.object(deploy, "run", side_effect=[SimpleNamespace(stdout="id1 id2"), SimpleNamespace(stdout=json.dumps(objects))]) as run:
            result = deploy.owned_containers_running([], {"services": ["daemon", "init"], "oneshot_services": ["init"]}, {})
            self.assertIn("-a", run.call_args_list[0].args[0])
            return result

    def test_ready_states(self):
        self.assertTrue(self.check_states(True, "exited"))

    def test_exited_daemon_is_not_ready(self):
        self.assertFalse(self.check_states(False, "exited"))

    def test_init_must_finish_successfully(self):
        self.assertFalse(self.check_states(True, "running"))
        self.assertFalse(self.check_states(True, "exited", 1))

    def test_readiness_timeout(self):
        with patch.object(deploy.time, "monotonic", side_effect=[0, 2]):
            with self.assertRaisesRegex(deploy.DeploymentError, "Readiness timeout"):
                deploy.wait_ready([], {}, {}, 1)


if __name__ == "__main__":
    unittest.main()
