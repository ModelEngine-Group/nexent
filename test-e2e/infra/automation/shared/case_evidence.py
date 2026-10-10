"""Write bounded, sanitized case diagnostics outside the product checkout."""
from __future__ import annotations

import json
import os
from collections import Counter, deque
from pathlib import Path
import re

from shared.config import load_secret_env
from shared.sse import read_sse


def write_case_evidence(name: str, payload, *, secrets=()) -> None:
    root = os.environ.get('RESULT_DIR')
    if not root:
        return
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('Evidence name must be a simple filename stem')
    # Fail closed when configured secrets cannot be loaded.
    protected = sorted({str(value) for value in (*load_secret_env().values(), *secrets)
                        if value and len(str(value)) >= 4}, key=len, reverse=True)

    def sanitize(value, key=''):
        normalized = re.sub(r'[^a-z0-9]', '', key.lower())
        if any(part in normalized for part in
               ('password', 'token', 'apikey', 'accesskey', 'authorization', 'secret')):
            return '***'
        if isinstance(value, dict):
            return {str(k): sanitize(v, str(k)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [sanitize(v) for v in value]
        if isinstance(value, str):
            for secret in protected:
                value = value.replace(secret, '***')
            value = re.sub(r'(?i)bearer\s+[a-z0-9._~+/=-]+', 'Bearer ***', value)
            value = re.sub(r'(?i)\bsk-[a-z0-9._-]+', 'sk-***', value)
            value = re.sub(
                r'(?i)((?:X-Amz-(?:Signature|Credential|Security-Token)|access_token|api_key)(?:=|%3d))[^&\s\"\x27\\]+',
                r'\1***', value,
            )
            return value
        return value

    path = Path(root) / 'runtime' / f'{name}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sanitize(payload), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def stream_diagnostics(events):
    """Keep protocol decisions and the tail, not the entire thinking stream."""
    payloads = [item.get('data') for item in events if isinstance(item.get('data'), dict)]
    selected = []
    for index, data in enumerate(payloads):
        if data.get('type') in {'error', 'plan', 'execution_logs', 'nl2a', 'nl2a_state'}:
            selected.append({'index': index, 'data': data})
    return {'event_count': len(events), 'protocol_events': selected[-50:], 'tail': payloads[-5:]}


async def read_sse_with_evidence(response, name, *, secrets=(), limit=1000):
    """Retain completed diagnostic frames even if consumption times out."""
    selected, tail = deque(maxlen=50), deque(maxlen=5)
    counts = Counter()
    pending = []
    ending = 'interrupted'

    def observe_frame():
        if not pending:
            return
        raw = '\n'.join(pending)
        pending.clear()
        if raw == '[DONE]':
            counts['[DONE]'] += 1
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {'type': 'raw', 'content': raw}
        kind = str(payload.get('type', 'unknown')) if isinstance(payload, dict) else 'unknown'
        counts[kind] += 1
        tail.append(payload)
        if kind in {'error', 'plan', 'execution_logs', 'nl2a', 'nl2a_state'}:
            selected.append(payload)

    class ObservedResponse:
        async def aiter_lines(self):
            async for line in response.aiter_lines():
                if line.startswith('data:'):
                    pending.append(line[5:].removeprefix(' '))
                elif not line.rstrip('\r'):
                    observe_frame()
                yield line
            observe_frame()

    try:
        result = await read_sse(ObservedResponse(), limit=limit)
        ending = 'consumed'
        return result
    except BaseException as exc:
        ending = type(exc).__name__
        raise
    finally:
        write_case_evidence(name, {
            'ending': ending, 'types': dict(counts), 'protocol_events': list(selected),
            'tail': list(tail), 'incomplete_frame_pending': bool(pending),
        }, secrets=secrets)
