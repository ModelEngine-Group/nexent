from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from app.auth import AUTH_PROFILES, JwtService, authenticate, security_contract
from app.cards import card_dict
from app.observations import ObservationStore
from app.redaction import redact_headers
from app.scenarios import ScenarioCatalog


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.jwt = JwtService("secret", "issuer", 60)

    def test_idkey_requires_both_headers(self) -> None:
        profile = AUTH_PROFILES["idkey"]
        self.assertTrue(
            authenticate(profile, {"x-hw-id": "hw-id-001", "x-hw-appkey": "hw-key-001"}, self.jwt)
        )
        self.assertFalse(authenticate(profile, {"x-hw-id": "hw-id-001"}, self.jwt))

    def test_jwt_is_bound_to_agent_and_subject(self) -> None:
        token = self.jwt.issue("jwt", "hw-id-002")
        self.assertTrue(self.jwt.verify(token, "jwt", "hw-id-002"))
        self.assertFalse(self.jwt.verify(token, "both", "hw-id-003"))

    def test_expired_jwt_is_rejected(self) -> None:
        token = self.jwt.issue("jwt", "hw-id-002", ttl_seconds=-1)
        time.sleep(0.01)
        self.assertFalse(self.jwt.verify(token, "jwt", "hw-id-002"))

    def test_both_profile_advertises_alternative_requirements(self) -> None:
        schemes, requirements = security_contract(AUTH_PROFILES["both"])
        self.assertEqual(3, len(schemes))
        self.assertEqual(2, len(requirements))


class EvidenceTests(unittest.TestCase):
    def test_sensitive_headers_are_not_stored_verbatim(self) -> None:
        headers = redact_headers({"Authorization": "Bearer secret", "X-HW-ID": "hw-id-002"})
        self.assertNotIn("secret", str(headers))
        self.assertEqual("hw-id-002", headers["X-HW-ID"])

    def test_observation_store_is_bounded_and_copied(self) -> None:
        store = ObservationStore(limit=1)
        store.add({"value": 1})
        store.add({"value": 2})
        items = store.list()
        self.assertEqual([2], [item["value"] for item in items])
        items[0]["value"] = 3
        self.assertEqual(2, store.list()[0]["value"])


class ContractTests(unittest.TestCase):
    def test_both_card_uses_or_requirements(self) -> None:
        card = card_dict("http://mock:8888", "both")
        self.assertEqual(2, len(card["securityRequirements"]))
        self.assertEqual("http://mock:8888/both", card["supportedInterfaces"][0]["url"])

    def test_scenario_catalog_can_select_and_reset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.yaml"
            path.write_text("scenarios:\n  normal: {}\n  broken:\n    fault:\n      status: 500\n", encoding="utf-8")
            catalog = ScenarioCatalog(str(path), "normal")
            catalog.select("broken")
            self.assertEqual(500, catalog.current()["fault"]["status"])
            catalog.reset()
            self.assertEqual("normal", catalog.current_name)


if __name__ == "__main__":
    unittest.main()

