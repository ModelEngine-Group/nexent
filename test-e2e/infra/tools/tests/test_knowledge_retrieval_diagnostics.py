"""Exercise actual TypeScript error handling without exposing upstream bodies."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class KnowledgeDiagnosticsTests(unittest.TestCase):
    def test_failure_metadata_is_bounded_and_keeps_http_failure(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Existing Node runtime is required')
        helper = Path(__file__).resolve().parents[2] / 'automation/d4/runner/knowledge-diagnostics.ts'
        with tempfile.TemporaryDirectory() as temporary:
            script = '''
import { knowledgeRetrievalFailure } from HELPER;
const root = ROOT;
const secretBody = "SSLError SSLEOFError Max retries exceeded https://private.test/?api_key=private-secret";
const failure = knowledgeRetrievalFailure(500, secretBody, root);
if (failure.name !== "ProductFailure" || failure.message.includes("private-secret")) throw new Error("unsafe failure");
const plain = knowledgeRetrievalFailure(503, "private-secret unavailable", root + "/plain");
if (plain.message.includes("private-secret")) throw new Error("unsafe plain failure");
const timeout = knowledgeRetrievalFailure(504, {detail: "ReadTimeout: timed out"}, root + "/timeout");
if (timeout.name !== "ProductFailure") throw new Error("wrong failure category");
'''.replace('HELPER', json.dumps(helper.as_uri())).replace('ROOT', json.dumps(temporary))
            outcome = subprocess.run([node, '--experimental-strip-types', '--input-type=module', '-e', script],
                                     text=True, capture_output=True, timeout=15)
            self.assertEqual(outcome.returncode, 0, outcome.stderr)
            root = Path(temporary)
            tls = json.loads((root / 'runtime/knowledge-retrieval-failure.json').read_text())
            self.assertEqual(tls, {'http_status': 500, 'upstream_tls_error': True,
                                  'upstream_connection_error': True, 'upstream_timeout': False})
            plain = json.loads((root / 'plain/runtime/knowledge-retrieval-failure.json').read_text())
            self.assertFalse(plain['upstream_tls_error'])
            self.assertFalse(plain['upstream_connection_error'])
            timeout = json.loads((root / 'timeout/runtime/knowledge-retrieval-failure.json').read_text())
            self.assertTrue(timeout['upstream_timeout'])
            self.assertNotIn('private-secret', json.dumps([tls, plain, timeout]))
            self.assertNotIn('private.test', json.dumps([tls, plain, timeout]))
