"""Exercise the fixture over HTTP without Docker or third-party dependencies."""

import contextlib
import http.client
import importlib.util
import io
import json
import secrets
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "server.py"
SPEC = importlib.util.spec_from_file_location("memory_mock", SOURCE)
mock = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mock)


class MemoryMockTests(unittest.TestCase):
    def setUp(self):
        self.token = secrets.token_urlsafe(24)
        self.server = mock.MemoryServer(("127.0.0.1", 0), self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method, path, body=None, *, org="org-a", token=None):
        headers = {"Authorization": f"Token {self.token if token is None else token}", "X-Org-Id": org}
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=2)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response), response.headers

    def add(self, *, user="user-a", agent=None, org="org-a", marker="unique-marker", event="unit-one"):
        body = {"user_id": user, "messages": [{"role": "user", "content": marker}],
                "metadata": {"event_id": event}, "infer": False}
        if agent:
            body["agent_id"] = agent
        status, result, _ = self.request("POST", "/v3/memories/add/", body, org=org)
        self.assertEqual(status, 200)
        return result["event_id"]

    def search(self, filters=None, **kwargs):
        return self.request("POST", "/v3/memories/search/", {
            "query": "unique-marker", "filters": filters or {"user_id": "user-a"}, "top_k": 5,
        }, **kwargs)

    def test_ready_is_nonsecret_and_explicitly_mock(self):
        status, data, _ = self.request("GET", "/readyz", token="wrong")
        self.assertEqual(status, 200)
        self.assertEqual(data["profile"], "mock")
        self.assertNotIn(self.token, json.dumps(data))

    def test_token_required(self):
        status, data, _ = self.search(token="wrong")
        self.assertEqual(status, 401)
        self.assertNotIn(self.token, json.dumps(data))
        status, _, _ = self.request("POST", "/__control/fault", {"user_id": "user-a", "status": 503}, token="wrong")
        self.assertEqual(status, 401)

    def test_ingest_search_event_delete_and_negative_search(self):
        status, data, _ = self.search()
        self.assertEqual(data["results"], [])
        event = self.add()
        status, data, _ = self.request("GET", f"/v1/event/{event}/")
        self.assertEqual((status, data["status"]), (200, "SUCCEEDED"))
        status, data, _ = self.search()
        self.assertEqual(status, 200)
        self.assertEqual(data["results"][0]["memory"], "unique-marker")
        record = data["results"][0]["id"]
        self.assertEqual(self.request("DELETE", f"/v1/memories/{record}/?user_id=other")[0], 404)
        self.assertEqual(self.request("DELETE", f"/v1/memories/{record}/?user_id=user-a")[0], 200)
        self.assertEqual(self.search()[1]["results"], [])
        self.assertEqual(self.request("GET", f"/v1/event/{event}/")[0], 404)

    def test_organization_user_and_agent_isolation(self):
        event = self.add(agent="agent-a")
        self.assertEqual(self.search(org="org-b")[1]["results"], [])
        self.assertEqual(self.request("GET", f"/v1/event/{event}/", org="org-b")[0], 404)
        self.assertEqual(self.search({"user_id": "user-b"})[1]["results"], [])
        self.assertEqual(self.search({"AND": [{"user_id": "user-a"}, {"agent_id": "agent-b"}]})[1]["results"], [])
        self.assertEqual(len(self.search({"AND": [{"user_id": "user-a"}, {"agent_id": "agent-a"}]})[1]["results"]), 1)
        # The real plugin falls back to user-only search for user-level memories.
        self.assertEqual(len(self.search({"user_id": "user-a"})[1]["results"]), 1)

    def test_agent_only_identity_is_supported(self):
        status, _, _ = self.request("POST", "/v3/memories/add/", {
            "agent_id": "agent-only", "messages": [{"role": "user", "content": "unique-marker"}], "infer": False,
        })
        self.assertEqual(status, 200)
        self.assertEqual(len(self.search({"agent_id": "agent-only"})[1]["results"]), 1)

    def test_no_fabricated_search_result(self):
        self.add(marker="unrelated-value")
        self.assertEqual(self.search()[1]["results"], [])

    def test_replayed_event_does_not_duplicate_memory(self):
        self.add()
        self.add()
        self.assertEqual(len(self.search()[1]["results"]), 1)
        self.add(user="user-b")
        self.assertEqual(len(self.server.state.records), 2)

    def test_filters_fail_closed(self):
        for filters in ({}, {"OR": [{"user_id": "a"}]}, {"run_id": "a"},
                        {"AND": [{"user_id": "a"}, {"user_id": "b"}]}, {"user_id": ""}):
            with self.subTest(filters=filters):
                status, _, _ = self.request("POST", "/v3/memories/search", {"query": "x", "filters": filters})
                self.assertEqual(status, 422)

    def test_invalid_payloads_do_not_mutate(self):
        for body in ({}, {"user_id": "a", "messages": []}, {"user_id": "a", "messages": [1]},
                     {"user_id": "a", "messages": [{"role": "user", "content": "x"}], "metadata": []},
                     {"user_id": "a", "messages": [{"role": "user", "content": "x"}], "infer": True}):
            self.assertEqual(self.request("POST", "/v3/memories/add", body)[0], 422)
        self.assertEqual(self.server.state.records, {})

    def test_fault_injection_is_user_and_org_scoped_and_resettable(self):
        self.add()
        self.add(user="user-b")
        for code in (401, 403, 429, 503):
            self.request("POST", "/__control/fault", {"user_id": "user-a", "status": code})
            status, _, headers = self.search()
            self.assertEqual(status, code)
            if code == 429:
                self.assertEqual(headers["Retry-After"], "1")
            self.assertEqual(self.search({"user_id": "user-b"})[0], 200)
            self.assertEqual(self.search(org="org-b")[0], 200)
        self.assertEqual(self.request("DELETE", "/__control/reset?user_id=user-a")[1]["deleted"], 1)
        self.assertEqual(self.search()[0], 200)
        self.assertEqual(len(self.search({"user_id": "user-b"})[1]["results"]), 1)

    def test_timeout_fault_and_recovery(self):
        self.request("POST", "/__control/fault", {"user_id": "user-a", "delay_seconds": 0.01})
        with patch.object(mock.time, "sleep") as delay:
            self.assertEqual(self.search()[0], 200)
            delay.assert_called_once_with(0.01)
        self.assertEqual(self.request("POST", "/__control/fault", {"user_id": "a", "delay_seconds": 31})[0], 422)

    def test_observations_do_not_contain_contents_or_credentials(self):
        self.add()
        self.search()
        status, data, _ = self.request("GET", "/__control/observations?user_id=user-a")
        self.assertEqual(status, 200)
        self.assertEqual(data["counts"], {"add": 1, "search": 1})
        self.assertNotIn("unique-marker", json.dumps(data))
        self.assertNotIn(self.token, json.dumps(data))

    def test_expiration_and_capacity(self):
        self.add()
        with patch.object(mock, "MAX_ITEMS", 1):
            self.assertEqual(self.request("POST", "/v3/memories/add", {
                "user_id": "other", "messages": [{"role": "user", "content": "x"}],
            })[0], 507)
        for record in self.server.state.records.values():
            record["created"] -= mock.TTL_SECONDS + 1
        self.assertEqual(self.search()[1]["results"], [])

    def test_oversized_body_and_unknown_route(self):
        # Reject at the header boundary without requiring an oversized upload.
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        try:
            connection.putrequest("POST", "/v3/memories/add")
            connection.putheader("Authorization", f"Token {self.token}")
            connection.putheader("Content-Length", str(mock.MAX_BODY + 1))
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(response.status, 413)
            response.read()
        finally:
            connection.close()
        self.assertEqual(self.request("GET", "/unimplemented")[0], 404)

    def test_short_credential_rejected(self):
        with self.assertRaises(ValueError):
            mock.MemoryServer(("127.0.0.1", 0), "short")

    def test_no_request_log_leaks(self):
        with contextlib.redirect_stderr(io.StringIO()) as logs:
            self.add()
        self.assertEqual(logs.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
