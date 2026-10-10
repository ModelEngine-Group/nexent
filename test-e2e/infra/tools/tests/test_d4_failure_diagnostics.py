"""Verify strict asset choice and credential-free persisted-history checks."""
from pathlib import Path
import sys
import unittest
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'automation'))
from shared.model_selection import select_configured_model
from shared.asset_registry import AssetDependencyError
from shared.cmsr import verify_history, history_diagnostics, HistoryVerificationError
import prepare_d4_shared_assets as preparation


class FailureDiagnosticsTests(unittest.TestCase):
    def test_missing_embedding_anchor_is_created_and_reused_without_replacing_bge(self):
        rows = [{'id': 1, 'model_type': 'embedding', 'model_name': 'old-bge'}]
        posts = []
        payload = {'model_type': 'embedding', 'model_name': 'configured-qwen',
                   'display_name': 'daily-embedding', 'expected_chunk_size': 2560}
        def response(body):
            return httpx.Response(200, json=body, request=httpx.Request('GET', 'http://fixture.test'))
        class API:
            async def get(self, path):
                return response({'data': rows})
            async def post(self, path, json):
                posts.append((path, dict(json)))
                if path == '/model/create': rows.append({**json, 'id': 2})
                return response({'data': {'connectivity': True}})
        @asynccontextmanager
        async def fake_client(*args, **kwargs):
            yield API()
        async def exercise():
            for _ in range(2):
                self.assertEqual(await preparation._ensure_embedding_anchor(SimpleNamespace(access_token='fixture')), 2)
        with patch.object(preparation, 'client', fake_client), \
                patch.object(preparation, 'model_request', side_effect=lambda *a:dict(payload)), \
                patch.object(preparation, 'model_id', AsyncMock(return_value=2)) as select:
            asyncio.run(exercise())
        self.assertEqual(select.await_count, 2)
        self.assertEqual(sum(path == '/model/create' for path, _ in posts), 1)
        self.assertEqual(rows[0]['model_name'], 'old-bge')
        self.assertEqual(rows[1]['expected_chunk_size'], 2560)
        self.assertEqual(rows[1]['display_name'], 'configured-qwen')

    def test_explicit_preference_overrides_candidate_order(self):
        config = {'model': 'old,new', 'preferred_model': 'new'}
        rows = [{'id': 1, 'model_type': 'embedding', 'model_name': 'old'},
                {'id': 2, 'model_type': 'embedding', 'model_name': 'new'}]
        self.assertEqual(select_configured_model(config, 'embedding', rows), 2)
        with self.assertRaises(AssetDependencyError):
            select_configured_model(config, 'embedding', rows[:1])

    def test_invalid_preference_is_not_invented_or_ignored(self):
        with self.assertRaises(AssetDependencyError):
            select_configured_model({'model': 'old', 'preferred_model': 'unknown'}, 'embedding', [])

    def test_history_failure_is_specific_and_contains_no_raw_text(self):
        body = {'data': [{'message': [{'role': 'assistant', 'message': [
            {'type': 'parse', 'content': 'private-secret CMSR_OK_n'},
            {'type': 'step_count', 'content': '1'},
            {'type': 'step_count', 'content': '2'},
            {'type': 'final_answer', 'content': 'CMSR_FINAL_n'}]}]}]}
        verify_history(body, 'n')
        body['data'][0]['message'][0]['message'].append({'type': 'parse', 'content': 'private-secret'})
        with self.assertRaisesRegex(HistoryVerificationError, 'parse_count: expected 1, observed 2') as caught:
            verify_history(body, 'n')
        self.assertNotIn('private-secret', str(caught.exception))
        self.assertNotIn('private-secret', str(history_diagnostics(body, 'n')))

    def test_missing_commit_and_failed_fragment_are_not_passes(self):
        for content, expected in [('CMSR_FINAL_n', 'committed_marker_present'),
                                  ('CMSR_FAILED_n CMSR_OK_n CMSR_FINAL_n', 'failed_fragment_present')]:
            body = {'data': [{'message': [{'role': 'assistant', 'message': [
                {'type': 'parse', 'content': content}, {'type': 'step_count', 'content': '1'},
                {'type': 'step_count', 'content': '2'}, {'type': 'final_answer', 'content': 'CMSR_FINAL_n'}]}]}]}
            with self.assertRaisesRegex(HistoryVerificationError, expected):
                verify_history(body, 'n')

    def test_marker_in_code_is_not_a_real_final_answer(self):
        body = {'data': [{'message': [{'role': 'assistant', 'message': [
            {'type': 'parse', 'content': "print('CMSR_OK_n'); final_answer('CMSR_FINAL_n')"},
            {'type': 'step_count', 'content': '1'}, {'type': 'step_count', 'content': '2'},
            {'type': 'final_answer', 'content': 'failed'},
        ]}]}]}
        with self.assertRaisesRegex(HistoryVerificationError, 'final_marker_present'):
            verify_history(body, 'n')


if __name__ == '__main__':
    unittest.main()
