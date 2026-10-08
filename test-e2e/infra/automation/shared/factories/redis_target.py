"""Resolve the deployed Redis wire endpoint without copying secrets to disk/logs."""
from __future__ import annotations

import ipaddress
import json
import os
import subprocess
from urllib.parse import urlsplit, urlunsplit

from shared.asset_registry import AssetDependencyError


def _inspect(name):
    result = subprocess.run(['docker', 'inspect', name], capture_output=True,
                            text=True, timeout=15, check=False)
    if result.returncode:
        raise AssetDependencyError('services', 'redis', detail=f'cannot inspect {name}')
    records = json.loads(result.stdout)
    if len(records) != 1:
        raise AssetDependencyError('services', 'redis', detail='ambiguous Docker target')
    return records[0]


def deployed_redis_urls():
    app = _inspect(os.environ.get('NEXENT_TEST_CONFIG_CONTAINER', 'nexent-config'))
    cache = _inspect(os.environ.get('NEXENT_TEST_REDIS_CONTAINER', 'nexent-redis'))
    values = dict(value.split('=', 1) for value in app['Config']['Env'] if '=' in value)
    addresses = {str(value.get('IPAddress') or '')
                 for value in cache['NetworkSettings']['Networks'].values()}
    addresses.discard('')
    if len(addresses) != 1:
        raise AssetDependencyError('services', 'redis', detail='Redis container has no unique network address')
    # Host-side tests may not reach a Docker bridge (notably Docker Desktop).
    # An explicit machine-local endpoint keeps deployment topology out of tests.
    address = os.environ.get('NEXENT_TEST_REDIS_HOST', '').strip() or addresses.pop()
    published_port = None
    if os.name == 'nt' and not os.environ.get('NEXENT_TEST_REDIS_HOST'):
        bindings = (cache['NetworkSettings'].get('Ports') or {}).get('6379/tcp') or []
        if bindings:
            address = '127.0.0.1'
            published_port = int(bindings[0]['HostPort'])
    try:
        address = str(ipaddress.ip_address(address))
    except ValueError:
        if any(character in address for character in '/:@ \t\r\n'):
            raise AssetDependencyError('services', 'redis', detail='invalid Redis host override')
    if ':' in address:
        address = f'[{address}]'

    def wire_url(value):
        parsed = urlsplit(value or '')
        if parsed.scheme not in {'redis', 'rediss'} or not parsed.hostname:
            raise AssetDependencyError('services', 'redis', detail='deployed Redis URL is missing or invalid')
        userinfo = parsed.netloc.rsplit('@', 1)[0] + '@' if '@' in parsed.netloc else ''
        port = int(os.environ.get('NEXENT_TEST_REDIS_PORT') or published_port or parsed.port or 6379)
        if not 1 <= port <= 65535:
            raise AssetDependencyError('services', 'redis', detail='invalid Redis port override')
        netloc = userinfo + address + f':{port}'
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    general = wire_url(values.get('REDIS_URL'))
    backend = wire_url(values.get('REDIS_BACKEND_URL') or values.get('REDIS_URL'))
    return general, backend
