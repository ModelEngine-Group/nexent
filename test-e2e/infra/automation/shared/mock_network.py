"""Separate the mock listener from the address a deployed service calls."""
import os
from urllib.parse import urlsplit
from shared.asset_registry import AssetDependencyError


def mock_bind_host():
    return os.environ.get('NEXENT_TEST_MOCK_BIND_HOST','0.0.0.0').strip()


def mock_callback_url(port):
    host = (os.environ.get('NEXENT_TEST_MOCK_CALLBACK_HOST') or
            os.environ.get('NEXENT_TEST_ASSETS_CONTAINER_HOST') or '').strip()
    if not host:
        raise AssetDependencyError('services','mock_callback_host',detail=
            'Set machine-local NEXENT_TEST_MOCK_CALLBACK_HOST to a host reachable from the deployed backend')
    parsed = urlsplit('http://' + host)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.path or
            parsed.query or parsed.fragment or parsed.port or parsed.hostname in ('0.0.0.0','::')):
        raise ValueError('Mock callback host must be a host only, not a URL, credentials or wildcard')
    return f'http://{host}:{int(port)}'
