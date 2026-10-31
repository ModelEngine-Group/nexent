"""Exercise the actual TypeScript ownership guard without a live Provider."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parents[3] / 'cases/PW-MEMORY-PROVIDER-01/owned-provider.ts'


class MemoryCleanupTests(unittest.TestCase):
    def test_original_renamed_absent_and_foreign_resources(self):
        program = f"import {{ ownedProviderId }} from {json.dumps(SCRIPT.as_uri())};\n" + '''
import assert from 'node:assert/strict';
const foreign = {provider_name:'unrelated-provider',provider_config_id:90};
const own = {provider_name:'run-owned',provider_config_id:12};
assert.equal(ownedProviderId([foreign,own],'run-owned',null),12);
assert.equal(ownedProviderId([foreign,{...own,provider_name:'run-owned-updated'}],'run-owned',12),12);
assert.equal(ownedProviderId([foreign],'run-owned',12),null);
assert.throws(()=>ownedProviderId([own,{...own,provider_name:'run-owned-updated'}],'run-owned',12),/ambiguous/);
assert.throws(()=>ownedProviderId([{...own,provider_config_id:13}],'run-owned',12),/identity changed/);
assert.throws(()=>ownedProviderId([{...own,provider_config_id:0}],'run-owned',null),/invalid/);
assert.throws(()=>ownedProviderId({},'run-owned',null),/items/);
'''
        node = shutil.which('node')
        self.assertIsNotNone(node)
        result = subprocess.run([node, '--experimental-strip-types', '--input-type=module', '-e', program],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
