"""Bounded Python bridge; never prints identity credentials."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.cmsr import control, setup, verify_history, history_diagnostics, HistoryVerificationError
from shared.case_evidence import write_case_evidence
from shared.auth import sign_in
from shared.http import client, assert_status


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['setup', 'reset', 'state', 'failed', 'success', 'delete', 'history'])
    parser.add_argument('--nonce')
    parser.add_argument('--mode', choices=['transport', 'semantic'])
    parser.add_argument('--conversation', type=int)
    args = parser.parse_args()
    if args.operation == 'history':
        identity = await sign_in('tenant_a_admin')
        async with client('runtime', token=identity.access_token) as api:
            response = await api.get(f'/conversation/{args.conversation}')
        write_case_evidence('cmsr-history', {
            'http_status': response.status_code,
            'conversation_id': args.conversation,
            'history': history_diagnostics(response.json(), args.nonce) if response.status_code == 200 else None,
        })
        assert_status(response, 200)
        verify_history(response.json(), args.nonce)
        result = {'verified': True}
    else:
        result = await setup('CMSR-D4-001', publish=True) if args.operation == 'setup' else await control(
            args.nonce, args.operation, mode=args.mode)
        if args.operation == 'state':
            write_case_evidence('cmsr-provider-state', {
                key: result.get(key) for key in ('calls', 'paused', 'completed', 'expired')
            })
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({'error_type': type(exc).__name__,
                          'check': str(exc) if isinstance(exc, HistoryVerificationError) else None}), file=sys.stderr)
        sys.exit(1)
