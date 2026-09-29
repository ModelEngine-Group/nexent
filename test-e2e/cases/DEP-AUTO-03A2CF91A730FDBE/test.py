from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET

import httpx
import pytest
from shared.asset_registry import AssetDependencyError


CAS_MOCK_URL = os.environ.get('CAS_MOCK_URL', 'http://localhost:3001').rstrip('/')
CAS_MOCK_USERNAME = os.environ.get('CAS_MOCK_USERNAME', 'casuser')
CAS_MOCK_PASSWORD = os.environ.get('CAS_MOCK_PASSWORD', 'casuser')
SERVICE_URL = 'https://nexent.example.local/cas/callback'
HEALTH_RETRY_SECONDS = 60.0
HEALTH_RETRY_INTERVAL = 5.0


def _local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


def _healthz_ready(client: httpx.Client) -> httpx.Response:
    deadline = time.monotonic() + HEALTH_RETRY_SECONDS
    last_status = -1
    while True:
        try:
            response = client.get('/healthz')
            last_status = response.status_code
            if response.status_code == 200 and response.text.strip() == 'ok':
                return response
        except httpx.HTTPError:
            last_status = -1
        if time.monotonic() >= deadline:
            raise AssertionError(
                f'cas-mock /healthz did not become healthy within {HEALTH_RETRY_SECONDS}s; last_status={last_status}'
            )
        time.sleep(HEALTH_RETRY_INTERVAL)


def _has_local(root: ET.Element, name: str) -> bool:
    return any(_local(elem.tag) == name for elem in root.iter())


def _text_by_local(root: ET.Element, name: str) -> str | None:
    for elem in root.iter():
        if _local(elem.tag) == name:
            value = (elem.text or '').strip()
            return value or None
    return None


def _failure_code(root: ET.Element) -> str | None:
    for elem in root.iter():
        if _local(elem.tag) == 'authenticationFailure':
            return elem.get('code')
    return None


def _set_cookie_lines(response: httpx.Response) -> list[str]:
    return list(response.headers.get_list('set-cookie'))


@pytest.mark.case_id('DEP-AUTO-03A2CF91A730FDBE')
@pytest.mark.stage('D5')
def test_cas_mock_reliability_smoke() -> None:
    preparation_error = os.environ.get('NEXENT_CAS_PREPARATION_ERROR', '')
    if preparation_error:
        raise AssetDependencyError(
            'services', 'cas_mock', dependency_case_id='D0-CAS-MOCK',
            detail=preparation_error,
        )
    with httpx.Client(base_url=CAS_MOCK_URL, follow_redirects=False, timeout=10.0) as client:
        health = _healthz_ready(client)
        assert health.status_code == 200
        assert health.text.strip() == 'ok'

        form = client.get('/cas/login', params={'service': SERVICE_URL})
        assert form.status_code == 200
        form_html = form.text
        assert re.search(r'name=.?username', form_html) is not None
        assert re.search(r'name=.?password', form_html) is not None
        assert re.search(r'name=.?service', form_html) is not None
        assert re.search(r'action=.?/?cas/login', form_html) is not None

        bad = client.post(
            '/cas/login',
            data={'username': CAS_MOCK_USERNAME, 'password': 'definitely-wrong-password', 'service': SERVICE_URL},
        )
        assert bad.status_code == 401
        assert '用户名或密码错误' in bad.text

        login = client.post(
            '/cas/login',
            data={'username': CAS_MOCK_USERNAME, 'password': CAS_MOCK_PASSWORD, 'service': SERVICE_URL},
        )
        assert login.status_code == 302
        location = login.headers.get('location', '')
        ticket_match = re.search(r'ticket=(ST-[^&]+)', location)
        assert ticket_match is not None, 'login redirect Location has no ST ticket'
        ticket = ticket_match.group(1)

        cookie_lines = _set_cookie_lines(login)
        castgc_line = next((line for line in cookie_lines if 'CASTGC=' in line), None)
        assert castgc_line is not None, 'login set no CASTGC cookie'
        assert castgc_line.startswith('CASTGC=TGC-')
        assert 'Path=/' in castgc_line
        assert 'HttpOnly' in castgc_line
        assert 'SameSite=Lax' in castgc_line
        castgc_match = re.search(r'CASTGC=([^;]+)', castgc_line)
        assert castgc_match is not None
        castgc_value = castgc_match.group(1)

        validate = client.get('/cas/p3/serviceValidate', params={'ticket': ticket, 'service': SERVICE_URL})
        assert validate.status_code == 200
        assert 'xml' in validate.headers.get('content-type', '').lower()
        success_root = ET.fromstring(validate.text)
        assert _has_local(success_root, 'authenticationSuccess'), validate.text
        assert _text_by_local(success_root, 'user') == CAS_MOCK_USERNAME
        attributes = {}
        for elem in success_root.iter():
            name = _local(elem.tag)
            if name in {'uid', 'email', 'displayName', 'role', 'tenant_id', 'SessionIndex'}:
                attributes[name] = (elem.text or '').strip()
        for name in ('uid', 'email', 'displayName', 'role', 'tenant_id', 'SessionIndex'):
            assert name in attributes and attributes[name], f'missing attribute {name}'

        reuse = client.get('/cas/p3/serviceValidate', params={'ticket': ticket, 'service': SERVICE_URL})
        assert reuse.status_code == 200
        reuse_root = ET.fromstring(reuse.text)
        assert _has_local(reuse_root, 'authenticationFailure'), reuse.text
        assert _failure_code(reuse_root) == 'INVALID_TICKET', reuse.text

        logout = client.get('/cas/logout', headers={'Cookie': f'CASTGC={castgc_value}'})
        assert logout.status_code in (200, 302)
        logout_cookies = _set_cookie_lines(logout)
        clear_line = next((line for line in logout_cookies if 'CASTGC=' in line), None)
        assert clear_line is not None, 'logout did not clear CASTGC cookie'
        assert 'Max-Age=0' in clear_line

        after_logout = client.get(
            '/cas/login',
            params={'service': SERVICE_URL},
            headers={'Cookie': f'CASTGC={castgc_value}'},
        )
        assert after_logout.status_code == 200
        assert re.search(r'name=.?username', after_logout.text) is not None
