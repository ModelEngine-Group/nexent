"""Health checks for asset dependencies, never a replacement for test assertions."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import random
import tempfile
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from shared.asset_registry import AssetDependencyError
from shared.config import load_secret_env, service_url, test_root
from shared.http import assert_status, client, response_message


def fingerprint(config, row, tenant, scope):
    # Digest credentials; never persist credentials or response bodies.
    credential = load_secret_env().get(str(config.get('secret_env_key') or ''), config.get('api_key', ''))
    stable_row = {k: v for k, v in row.items() if k not in {
        'updated_at', 'created_at', 'update_time', 'create_time', 'connect_status'}}
    value = [config, stable_row, credential, str(tenant), service_url('config'), str(scope)]
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def retry_delay(header, attempt):
    try:
        delay = float(header)
    except (ValueError, TypeError):
        try:
            delay = parsedate_to_datetime(header).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            delay = 2 ** (attempt + 1) + random.uniform(0, 1)
    # Do not retry sooner than a long Retry-After: caller stops instead.
    return max(0, delay)


def record(event):
    if not os.environ.get('RESULT_DIR'):
        return
    path = Path(os.environ['RESULT_DIR']) / 'runtime/model-health.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as out:
        out.write(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(), **event}) + '\n')


async def create_configured_model_dependency(api, payload, *, case_id):
    """Retry only a vector probe rejected before model persistence.

    This helper is for prerequisite models, never model-management acceptance
    tests. Do not retry ambiguous transport failures on a mutating POST, name
    collisions, permissions, validation, unrelated 409s or server errors.
    """
    name = str(payload.get('display_name') or payload.get('model_name') or '')
    kind = str(payload.get('model_type') or '')
    expected_error = f"Failed to get embedding dimension for model '{name}'."
    for attempt in range(3):
        started = time.monotonic()
        try:
            response = await api.post('/model/create', json=payload)
        except httpx.TransportError as exc:
            record({'operation': 'create_dependency_model', 'case_id': case_id, 'model': name,
                    'attempt': attempt + 1, 'outcome': 'ambiguous_transport_write',
                    'error_type': type(exc).__name__, 'duration_seconds': round(time.monotonic() - started, 3)})
            raise
        failed_probe = (
            kind in {'embedding', 'multi_embedding'} and response.status_code == 409
            and response_message(response).startswith(expected_error)
        )
        record({'operation': 'create_dependency_model', 'case_id': case_id, 'model': name,
                'attempt': attempt + 1, 'http_status': response.status_code,
                'outcome': 'dimension_probe_failed' if failed_probe else f'http_{response.status_code}',
                'duration_seconds': round(time.monotonic() - started, 3)})
        if not failed_probe:
            assert_status(response, 200)
            return response
        if attempt < 2:
            delay = retry_delay(response.headers.get('Retry-After'), attempt)
            if delay > 30:
                record({'operation': 'create_dependency_model', 'case_id': case_id, 'model': name,
                        'outcome': 'retry_after_exceeds_budget', 'delay_seconds': delay})
                break
            await asyncio.sleep(delay)
    raise AssetDependencyError('models', kind, consumer_case_id=case_id,
                               detail='configured vector dimension probe failed before model creation; '
                                      'see runtime/model-health.jsonl')


async def ensure_model_health(identity, config, row, *, force=False):
    """At most 3 probes, caching only successes in the current batch scope.

    Product endpoints sometimes wrap a provider failure in HTTP 200 and lose
    its cause. Such a failure is recorded as connectivity_false, not invented
    as a 429. Negative authentication/validation HTTP responses are not retried.
    """
    name = str(row.get('display_name') or row.get('model_name') or '')
    kind = str(row.get('model_type') or '')
    scope = os.environ.get('NEXENT_MODEL_HEALTH_CACHE_SCOPE') or os.environ.get('RESULT_DIR', '')
    ttl = max(0, float(os.environ.get('NEXENT_MODEL_HEALTH_TTL', '300')))
    key = fingerprint(config, row, identity.tenant_id, scope)
    cache = test_root() / 'state/model-health' / (key + '.json')
    try:
        previous = json.loads(cache.read_text())
    except (OSError, ValueError):
        previous = {}
    age = time.time() - previous.get('verified_at', 0)
    if not force and scope and ttl > 0 and 0 <= age < ttl and previous.get('key') == key:
        record({'model': name, 'outcome': 'cached_dependency_health', 'age_seconds': round(age, 3)})
        return

    outcomes = []
    for attempt in range(3):
        started = time.monotonic()
        response = None
        try:
            # Reopen after every probe: a closed keep-alive connection must
            # not poison a retry. This is a read-like dependency check only.
            async with client('config', token=identity.access_token, timeout=45) as api:
                response = await api.post('/model/healthcheck', params={'display_name': name, 'model_type': kind})
            payload = response.json() if response.status_code == 200 else {}
            data = payload.get('data', payload) if isinstance(payload, dict) else {}
            success = isinstance(data, dict) and data.get('connectivity') is True
            last = 'connected' if success else ('connectivity_false' if response.status_code == 200 else f'http_{response.status_code}')
        except (httpx.TransportError, ValueError) as exc:
            success = False
            last = type(exc).__name__
        outcomes.append(last)
        record({'operation': 'dependency_health', 'model': name, 'attempt': attempt + 1, 'outcome': last,
                'http_status': response.status_code if response is not None else None,
                'duration_seconds': round(time.monotonic() - started, 3)})
        if success:
            cache.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=cache.parent, prefix='health-')
            try:
                with os.fdopen(fd, 'w') as out:
                    json.dump({'key': key, 'verified_at': time.time()}, out)
                os.replace(temporary, cache)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return
        retryable = response is None or response.status_code in {200, 429, 502, 503, 504}
        if attempt == 2 or not retryable:
            break
        delay = retry_delay(response.headers.get('Retry-After') if response is not None else None, attempt)
        if delay > 30:
            record({'model': name, 'outcome': 'retry_after_exceeds_budget', 'delay_seconds': delay})
            break
        await asyncio.sleep(delay)
    # A previous positive result cannot rescue a failed recheck.
    cache.unlink(missing_ok=True)
    raise AssetDependencyError('models', name, detail='dependency health failed: ' + ', '.join(outcomes)
                               + '; see runtime/model-health.jsonl')
