"""Exercise the actual TypeScript-to-Python identity bridge without credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

REPO = Path(__file__).resolve().parents[4]
CONFIG = REPO / "test-e2e/infra/automation/d4/runner/runtime-config.ts"


class D4UserConfigTests(unittest.TestCase):
    def invoke(self, users, *, json_format=False, password=True, expected_error=False):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / "config").mkdir()
            document = {"users": users}
            (home / "config/users.yaml").write_text(
                json.dumps(document) if json_format else yaml.safe_dump(document), encoding="utf-8")
            env = dict(os.environ, NEXENT_TEST_HOME=str(home), TEST_ROOT=str(home),
                       NEXENT_REPO=str(REPO), FIXED_TEST_PYTHON=sys.executable)
            env.pop("D4_SYNTHETIC_PASSWORD", None)
            if password:
                env["D4_SYNTHETIC_PASSWORD"] = "synthetic-not-a-secret"
            script = f"import {{ testUser }} from {json.dumps(CONFIG.as_uri())};\n"
            if expected_error:
                script += "import assert from 'node:assert/strict'; assert.throws(() => testUser('tenant_a_admin'));"
            else:
                script += "import assert from 'node:assert/strict'; assert.deepEqual(testUser('tenant_a_admin'), {id:'tenant_a_admin',username:'different@fixture.invalid',password:'synthetic-not-a-secret'});"
            node = shutil.which("node")
            self.assertIsNotNone(node, "Node.js is required to verify the D4 bridge")
            result = subprocess.run([node, "--experimental-strip-types", "--input-type=module", "-e", script],
                                    env=env, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("synthetic-not-a-secret", result.stdout)

    def user(self):
        return {"id": "tenant_a_admin", "username": "different@fixture.invalid",
                "password_env_key": "D4_SYNTHETIC_PASSWORD"}

    def test_yaml_custom_identity_and_secret_key(self):
        self.invoke([self.user()])

    def test_json_configuration(self):
        self.invoke([self.user()], json_format=True)

    def test_missing_identity_has_no_fixed_fallback(self):
        self.invoke([], expected_error=True)

    def test_duplicate_identity_is_rejected(self):
        self.invoke([self.user(), self.user()], expected_error=True)

    def test_missing_password_is_rejected(self):
        self.invoke([self.user()], password=False, expected_error=True)

    def test_incomplete_identity_is_rejected(self):
        self.invoke([{"id": "tenant_a_admin"}], expected_error=True)


if __name__ == "__main__":
    unittest.main()
