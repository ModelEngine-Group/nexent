"""Non-browser A2A probes; credentials never cross the JSON stdout boundary."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

AUTOMATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION))

from shared.a2a import A2AMock  # noqa: E402
from shared.asset_registry import register_asset, mark_asset_state  # noqa: E402
from shared.auth import sign_in  # noqa: E402
from shared.config import service_url  # noqa: E402
from shared.http import assert_status, client  # noqa: E402


class ProbeFailure(AssertionError):
    """Only controller-authored, credential-free diagnostics may be exposed."""


def verify_invocation(response, marker):
    if response.status_code != 200:
        raise ProbeFailure(f'published invocation returned HTTP {response.status_code}')
    payload = response.json()
    task = payload.get('task')
    if isinstance(task, dict):
        state = (task.get('status') or {}).get('state')
        if state not in ('TASK_STATE_COMPLETED', 'completed'):
            known = state if state in ('TASK_STATE_FAILED', 'TASK_STATE_CANCELED',
                                      'TASK_STATE_WORKING', 'TASK_STATE_SUBMITTED') else 'non-completed'
            raise ProbeFailure(f'published invocation HTTP 200 but task state is {known}')
        messages = [(task.get('status') or {}).get('message') or {}]
        messages.extend(task.get('artifacts') or [])
    else:
        messages = [payload.get('message') or {}]
    answer = '\n'.join(str(part.get('text', '')) for message in messages
                       for part in (message.get('parts') or []) if isinstance(part, dict))
    if marker not in answer:
        raise ProbeFailure('published invocation omitted the required response marker')


async def run(args):
    if args.command == 'northbound-config':
        return {'northbound_url': service_url('northbound')}
    if args.command in ('config', 'wire'):
        mock = A2AMock()
        try:
            await mock.ready()
            if args.command == 'config':
                return {'product_url': mock.settings['product_url'], 'northbound_url': service_url('northbound')}
            response = await mock.control.get('/__test/observations')
            assert_status(response, 200)
            rows = [row for row in response.json()['items'] if
                    row.get('headers', {}).get('x-nexent-test-run') == args.nonce or
                    (row['agent'] == 'basic' and row['method'] == 'POST' and row['observed_at'] >= args.after)]
            target = Path(os.environ['RESULT_DIR']) / 'a2a-wire'
            target.mkdir(parents=True, exist_ok=True)
            (target / f'{args.nonce}.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
            return {'get_count': sum(row['method'] == 'GET' for row in rows),
                    'post_count': sum(row['method'] == 'POST' for row in rows),
                    'authenticated': all(row['authenticated'] for row in rows)}
        finally:
            await mock.close()
    async with client('northbound', timeout=600) as external:
        card = await external.get(f'/nb/a2a/{args.endpoint}/.well-known/agent-card.json')
        assert_status(card, 200)
        body = card.json()
        assert str(body['version']) == args.version
        if args.command == 'card':
            return {'name': body['name'], 'version': body['version'], 'interfaces': body['supportedInterfaces']}
        identity = await sign_in('tenant_a_admin')
        owned_token_id = None
        async with client('config', token=identity.access_token) as api:
            listed = await api.get('/user/tokens', params={'user_id': identity.user_id})
            assert_status(listed, 200)
            tokens = listed.json()['data']
            try:
                # Reuse a readable existing test key; never regenerate and revoke it.
                if tokens:
                    assert tokens[0].get('can_copy'), 'existing key must be readable without replacement'
                    secret = tokens[0]['access_key']
                else:
                    created = await api.post('/user/tokens')
                    assert_status(created, 200)
                    token = created.json()['data']
                    owned_token_id = token['token_id']
                    secret = token['access_key']
                    register_asset('owned_a2a_token', str(owned_token_id), owned_token_id,
                                   owner_case_id='PW-A2A-PUBLISH-01', cleanup={
                                       'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                                       'path': f'/user/tokens/{owned_token_id}', 'allowed_statuses': [200, 404]})
                response = await external.post(f'/nb/a2a/{args.endpoint}/message:send', headers={
                    'Authorization': f'Bearer {secret}', 'A2A-Version': '1.0',
                }, json={'message': {'messageId': args.nonce, 'role': 'ROLE_USER',
                                    'parts': [{'text': f'只回复 {args.marker}'}]}})
                verify_invocation(response, args.marker)
                return {'status': response.status_code, 'marker_verified': True, 'version': body['version']}
            finally:
                if owned_token_id is not None:
                    assert_status(await api.delete(f'/user/tokens/{owned_token_id}'), (200, 404))
                    mark_asset_state('owned_a2a_token', str(owned_token_id), 'DELETED')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['config', 'northbound-config', 'wire', 'card', 'call'])
    parser.add_argument('--nonce', default='')
    parser.add_argument('--after', default='')
    parser.add_argument('--endpoint', default='')
    parser.add_argument('--version', default='')
    parser.add_argument('--marker', default='')
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(run(args)), ensure_ascii=False))
        return 0
    except Exception as exc:
        # Never include request bodies or credential-bearing representations.
        detail = str(exc) if isinstance(exc, ProbeFailure) else type(exc).__name__
        print(f'A2A probe failed: {detail}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
