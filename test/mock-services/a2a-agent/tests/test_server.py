from __future__ import annotations

import unittest
import uuid

from starlette.testclient import TestClient

from app.server import app


class ServerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_health_and_basic_card(self) -> None:
        self.assertEqual(200, self.client.get("/healthz").status_code)
        response = self.client.get("/basic/.well-known/agent-card.json")
        self.assertEqual(200, response.status_code)
        self.assertEqual("JSONRPC", response.json()["supportedInterfaces"][1]["protocolBinding"])

    def test_protected_card_rejects_and_accepts_idkey(self) -> None:
        url = "/idkey/.well-known/agent-card.json"
        self.assertEqual(401, self.client.get(url).status_code)
        response = self.client.get(
            url,
            headers={"X-HW-ID": "hw-id-001", "X-HW-APPKEY": "hw-key-001"},
        )
        self.assertEqual(200, response.status_code)

    def test_jsonrpc_requires_version_and_returns_deterministic_data(self) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": "request-1",
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role": "ROLE_USER",
                    "parts": [{"text": "Query pedestrian flow"}],
                }
            },
        }
        missing_version = self.client.post("/basic/v1", json=payload)
        self.assertIn("error", missing_version.json())
        response = self.client.post("/basic/v1", json=payload, headers={"A2A-Version": "1.0"})
        self.assertEqual(200, response.status_code)
        self.assertIn("total=1283", response.text)

    def test_control_routes_require_token(self) -> None:
        self.assertEqual(401, self.client.get("/__test/scenario").status_code)
        response = self.client.get(
            "/__test/scenario",
            headers={"X-A2A-Control-Token": "local-test-control"},
        )
        self.assertEqual(200, response.status_code)
        self.assertIn("happy-jsonrpc", response.json()["available"])

    def test_metadata_evidence_is_fingerprinted(self) -> None:
        import hashlib
        import json
        metadata = {"trace_marker": "test-42", "secret": "never-record-this"}
        response = self.client.post("/basic/v1", headers={"A2A-Version": "1.0"}, json={
            "jsonrpc": "2.0", "id": "metadata", "method": "SendMessage",
            "params": {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"text": "echo"}], "metadata": metadata}},
        })
        self.assertEqual(200, response.status_code)
        observations = self.client.get("/__test/observations", headers={"X-A2A-Control-Token": "local-test-control"}).json()["items"]
        self.assertNotIn("never-record-this", json.dumps(observations))
        expected = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(expected, observations[-1]["payload_summary"]["metadata_sha256"])
        self.assertTrue(observations[-1]["authenticated"])


if __name__ == "__main__":
    unittest.main()
