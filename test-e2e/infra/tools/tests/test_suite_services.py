"""Offline tests: no product, Docker, real mocks, or network required."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import suite_services as services


class ServiceTests(unittest.TestCase):
    def test_assets_do_not_accept_protocol_error(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch.object(services, "build_opener") as factory, patch.object(services.time, "sleep"):
            factory.return_value.open.side_effect = HTTPError("http://localhost", 400, "bad", {}, None)
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                services.wait_ready("http://localhost/health", process, timeout=0.01)

    def test_mcp_accepts_explicit_protocol_status(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch.object(services, "build_opener") as factory:
            factory.return_value.open.side_effect = HTTPError("http://localhost", 406, "protocol", {}, None)
            services.wait_ready("http://localhost/mcp", process, accepted_statuses=(200, 406))

    def test_dead_service_is_not_ready(self):
        process = MagicMock()
        process.poll.return_value = 1
        with self.assertRaisesRegex(RuntimeError, "exited"):
            services.wait_ready("http://localhost/health", process)

    def test_missing_explicit_host_starts_nothing(self):
        with patch.object(services.subprocess, "Popen") as start:
            with self.assertRaisesRegex(RuntimeError, "explicitly"):
                with services.controlled_services(Path("."), Path("."), {}, True):
                    pass
            start.assert_not_called()

    def test_second_service_readiness_failure_cleans_both(self):
        with tempfile.TemporaryDirectory() as root:
            processes = [MagicMock(), MagicMock()]
            for process in processes:
                process.poll.return_value = None
            env = {"NEXENT_TEST_ASSETS_CONTAINER_HOST": "test-host"}
            with patch.object(services.subprocess, "Popen", side_effect=processes) as start, \
                 patch.object(services, "wait_ready", side_effect=[None, RuntimeError("not ready")]), \
                 patch.object(services, "free_port", side_effect=[10001, 10002]):
                with self.assertRaisesRegex(RuntimeError, "not ready"):
                    with services.controlled_services(Path(root), Path(root), env, True):
                        self.fail("must not run test after failed preparation")
                for process in processes:
                    process.terminate.assert_called_once()
                for call in start.call_args_list:
                    self.assertTrue(call.kwargs["stdout"].closed)
                self.assertTrue((Path(root) / "runtime").is_dir())

    def test_stubborn_service_killed_and_other_service_still_cleaned(self):
        with tempfile.TemporaryDirectory() as root:
            processes = [MagicMock(), MagicMock()]
            for process in processes:
                process.poll.return_value = None
            processes[1].wait.side_effect = [subprocess.TimeoutExpired("server", 5), None]
            env = {"NEXENT_TEST_ASSETS_CONTAINER_HOST": "test-host"}
            with patch.object(services.subprocess, "Popen", side_effect=processes), \
                 patch.object(services, "wait_ready"), patch.object(services, "free_port", side_effect=[10001, 10002]):
                with services.controlled_services(Path(root), Path(root), env, True):
                    self.assertEqual(env["NEXENT_TEST_MCP_URL"], "http://test-host:10002/mcp")
                processes[1].kill.assert_called_once()
                processes[0].terminate.assert_called_once()

    def test_shutdown_error_does_not_leave_other_service_running(self):
        with tempfile.TemporaryDirectory() as root:
            processes = [MagicMock(), MagicMock()]
            for process in processes:
                process.poll.return_value = None
            processes[1].terminate.side_effect = OSError("failure")
            with patch.object(services.subprocess, "Popen", side_effect=processes) as start, \
                 patch.object(services, "wait_ready"), patch.object(services, "free_port", side_effect=[10001, 10002]):
                with self.assertRaisesRegex(RuntimeError, "shutdown failed"):
                    with services.controlled_services(Path(root), Path(root), {"NEXENT_TEST_ASSETS_CONTAINER_HOST": "test-host"}, True):
                        pass
                processes[0].terminate.assert_called_once()
                self.assertTrue(all(call.kwargs["stdout"].closed for call in start.call_args_list))


if __name__ == "__main__":
    unittest.main()
