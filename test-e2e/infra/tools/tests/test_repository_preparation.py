"""Repository fixture health must not change the author authorization boundary."""
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'automation'))
from shared.factories import repository


class RepositoryPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_uses_reviewer_but_author_creates_and_publishes(self):
        author = SimpleNamespace(id='author', tenant_id='same', access_token='author-session')
        reviewer = SimpleNamespace(id='reviewer', tenant_id='same', access_token='reviewer-session')
        draft_calls, requests = [], []

        @asynccontextmanager
        async def draft(who, **kwargs):
            draft_calls.append((who, kwargs))
            yield 123, {}

        def response(data):
            return httpx.Response(200, json=data, request=httpx.Request('POST', 'http://fixture.test'))

        @asynccontextmanager
        async def client(service, *, token):
            async def post(path, **kwargs):
                requests.append((token, 'POST', path))
                return response({'version_no': 1} if path.endswith('/publish') else {'agent_repository_id': 456})
            async def patch_request(path, **kwargs):
                requests.append((token, 'PATCH', path))
                return response({})
            async def get(path, **kwargs):
                requests.append((token, 'GET', path))
                return response({})
            yield SimpleNamespace(post=post, patch=patch_request, get=get)

        with patch.object(repository, '_llm_id', AsyncMock(return_value=7)) as health, \
                patch.object(repository, '_draft_agent', draft), \
                patch.object(repository, 'client', client), \
                patch.object(repository, 'register_asset'):
            self.assertEqual(await repository.prepare_agent_listing(author, reviewer), 456)
        health.assert_awaited_once_with(reviewer)
        self.assertIs(draft_calls[0][0], author)
        self.assertEqual(draft_calls[0][1]['model_ids'], [7])
        self.assertEqual([r[0] for r in requests], ['author-session'] * 3 + ['reviewer-session'] * 2)

    async def test_cross_tenant_reviewer_rejected_before_any_probe(self):
        with patch.object(repository, '_llm_id', AsyncMock()) as health:
            with self.assertRaises(ValueError):
                await repository.prepare_agent_listing(
                    SimpleNamespace(tenant_id='a'), SimpleNamespace(tenant_id='b'))
        health.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
