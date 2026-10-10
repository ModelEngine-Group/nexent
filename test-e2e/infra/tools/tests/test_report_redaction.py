"""Failure diagnostics must preserve the failure but remove session credentials."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'automation'))
import nexent_formal_pytest as plugin


class ReportRedactionTests(unittest.TestCase):
    def test_traceback_and_captured_logs_redacted_without_hiding_failure(self):
        secret = 'fixture-actual-session-12345'
        report = SimpleNamespace(longrepr=f'AssertionError: expected 404 got 500; {secret}',
                                 sections=[('Captured stdout', f'northbound_admin_key = "{secret}"')],
                                 outcome='failed')
        plugin.redact_report(report, {'northbound_admin_key': secret})
        self.assertNotIn(secret, report.longrepr)
        self.assertNotIn(secret, report.sections[0][1])
        self.assertIn('expected 404 got 500', report.longrepr)
        self.assertEqual(report.outcome, 'failed')

    def test_identity_tokens_and_skip_tuple_structure(self):
        secret = 'fixture-identity-session-12345'
        report = SimpleNamespace(longrepr=('case.py', 2, f'Blocked: {secret}'), sections=[])
        plugin.redact_report(report, {'user': SimpleNamespace(access_token=secret)})
        self.assertEqual(report.longrepr[:2], ('case.py', 2))
        self.assertNotIn(secret, report.longrepr[2])


if __name__ == '__main__':
    unittest.main()
