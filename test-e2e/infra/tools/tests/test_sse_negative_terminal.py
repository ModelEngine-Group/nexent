"""Negative terminals must never make ordinary streams pass."""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[2] / 'automation/shared/sse.py'
spec = importlib.util.spec_from_file_location('sse_under_test', PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TerminalTests(unittest.TestCase):
    def test_success_checks_still_reject_error(self):
        with self.assertRaises(AssertionError):
            module.assert_terminal_event([{'data': {'type': 'error', 'content': 'safe error'}}])

    def test_negative_accepts_last_explicit_root_error(self):
        module.assert_terminal_event([{'data': {'type': 'error', 'content': 'safe error'}}], allow_error=True)

    def test_negative_rejects_child_error(self):
        with self.assertRaises(AssertionError):
            module.assert_terminal_event([{'data': {'type': 'error', 'content': 'child error', 'depth': 1}}], allow_error=True)

    def test_negative_rejects_nonterminal_or_empty_error(self):
        for events in ([{'data': {'type': 'model_output', 'content': 'failed'}}],
                       [{'data': {'type': 'error', 'content': ''}}],
                       [{'data': {'type': 'error', 'content': 'error'}}, {'data': {'type': 'step_count'}}]):
            with self.assertRaises(AssertionError):
                module.assert_terminal_event(events, allow_error=True)
