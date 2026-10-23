# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from __future__ import annotations

import asyncio
import os
import time

import pytest
import pytest_asyncio

from shared.http import assert_status, client
from shared.aidp import create_payload
from shared.factories.ownership import register_owned_http

CASE_ID = 'API-AUTO-FECE331C989B771F'

AIDP_MAX_UPLOAD_FILE_COUNT = 50
AIDP_SMALL_FILE_MAX_SIZE_BYTES = 20 * 1024 * 1024

COUNT_REASON_ZH = '单次最多上传 50 个文件'
COUNT_REASON_EN = 'You can upload up to 50 files at a time'
SIZE_20MB_REASON_ZH = '文件大小不能超过 20 MB'
SIZE_20MB_REASON_EN = 'File size must not exceed 20 MB'


def _file(name, content):
    return ('files', (name, content, 'application/octet-stream'))


@pytest_asyncio.fixture(scope='function')
async def aidp_kb(tenant_a_admin):
    name = f'aidp-d2-doc-contract-{os.getpid()}-{int(time.time())}'
    async with client('config', token=tenant_a_admin.access_token) as api:
        created = await api.post(
            '/aidp-mgmt/knowledge-bases',
            json=await create_payload(tenant_a_admin, name, ingroup_permission='PRIVATE'),
        )
        assert_status(created, 200)
        body = created.json()
        kds_id = str(body.get('kds_id') or body.get('id') or '')
        assert kds_id, f'create KB response missing kds_id: {body!r}'
        register_owned_http(tenant_a_admin, 'aidp_knowledge_bases', kds_id,
                            f'/aidp-mgmt/knowledge-bases/{kds_id}')
    try:
        yield kds_id
    finally:
        async with client('config', token=tenant_a_admin.access_token) as api:
            removed = await api.delete(f'/aidp-mgmt/knowledge-bases/{kds_id}')
            assert_status(removed, (200, 404))


@pytest.mark.asyncio
@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D2')
async def test_aidp_document_upload_list_contract(aidp_kb, tenant_a_admin, tenant_a_user):
    kds_id = aidp_kb
    documents_path = f'/aidp-mgmt/knowledge-bases/{kds_id}/documents'
    files_path = f'/aidp-mgmt/knowledge-bases/{kds_id}/files'
    suffix = f'{os.getpid()}-{int(time.time())}'

    async with client('config', token=tenant_a_admin.access_token) as api:
        fifty_one = [
            _file(f'doc_{i:02d}.txt', b'x')
            for i in range(AIDP_MAX_UPLOAD_FILE_COUNT + 1)
        ]
        resp = await api.post(documents_path, files=fifty_one)
        assert_status(resp, 200)
        payload = resp.json()
        assert payload['summary'] == {'total': 51, 'success': 0, 'failed': 51}
        assert payload['success_list'] == []
        assert len(payload['failed_list']) == 51
        for item in payload['failed_list']:
            assert item['reason_zh'] == COUNT_REASON_ZH
            assert item['reason_en'] == COUNT_REASON_EN
            assert item['file_name']

        oversize = b'0' * (AIDP_SMALL_FILE_MAX_SIZE_BYTES + 1)
        resp = await api.post(documents_path, files=[_file(f'big_{suffix}.txt', oversize)])
        assert_status(resp, 200)
        payload = resp.json()
        assert payload['summary'] == {'total': 1, 'success': 0, 'failed': 1}
        assert payload['success_list'] == []
        assert len(payload['failed_list']) == 1
        assert payload['failed_list'][0]['reason_zh'] == SIZE_20MB_REASON_ZH
        assert payload['failed_list'][0]['reason_en'] == SIZE_20MB_REASON_EN

        valid_name = f'valid_{suffix}.txt'
        big_a = f'big_a_{suffix}.txt'
        big_b = f'big_b_{suffix}.txt'
        mixed = [
            _file(valid_name, b'valid content'),
            _file(big_a, oversize),
            _file(big_b, oversize),
        ]
        resp = await api.post(documents_path, files=mixed)
        assert_status(resp, 200)
        payload = resp.json()
        assert payload['summary']['total'] == 3
        assert payload['summary']['success'] == len(payload['success_list'])
        assert payload['summary']['failed'] == len(payload['failed_list'])
        success_names = {item['file_name'] for item in payload['success_list']}
        assert valid_name in success_names
        failed_by_name = {item['file_name']: item for item in payload['failed_list']}
        assert big_a in failed_by_name
        assert big_b in failed_by_name
        assert failed_by_name[big_a]['reason_zh'] == SIZE_20MB_REASON_ZH
        assert failed_by_name[big_b]['reason_zh'] == SIZE_20MB_REASON_ZH

        resp = await api.get(files_path, params={'page': 1, 'page_size': 10})
        assert_status(resp, 200)
        payload = resp.json()
        assert isinstance(payload.get('value'), list)
        assert len(payload['value']) <= 10
        assert isinstance(payload.get('total_count'), int)
        assert isinstance(payload.get('has_more'), bool)
        assert payload.get('processing_count') == 0
        assert isinstance(payload.get('total_reliable'), bool)
        if payload['total_count'] == 0:
            assert payload['has_more'] is False

        # AIDP always returns next_link, including on the last page. Wait for
        # the uploaded file to become visible in the ingested-files listing,
        # then prove the keyword actually matched it and the short page stops.
        filtered_payload = {}
        for _ in range(60):
            filtered = await api.get(
                files_path,
                params={'page': 1, 'page_size': 10, 'keyword': valid_name},
            )
            assert_status(filtered, 200)
            filtered_payload = filtered.json()
            if any(
                item.get('file_name') == valid_name
                for item in filtered_payload.get('value', [])
            ):
                break
            await asyncio.sleep(1)
        else:
            raise AssertionError(
                f'{valid_name} did not appear in /files within 60 seconds: '
                f'{filtered_payload}'
            )

        filtered_names = {
            item.get('file_name') for item in filtered_payload['value']
        }
        assert valid_name in filtered_names
        assert len(filtered_payload['value']) == 1
        assert filtered_payload['total_reliable'] is False
        assert filtered_payload['has_more'] is False

    async with client('config') as anonymous:
        resp = await anonymous.post(documents_path, files=[_file('x.txt', b'x')])
        assert_status(resp, 401)

    async with client('config', token=tenant_a_user.access_token) as user_api:
        resp = await user_api.post(documents_path, files=[_file('x.txt', b'x')])
        assert_status(resp, 403)
        assert tenant_a_admin.password not in resp.text
        assert tenant_a_admin.access_token not in resp.text
        resp = await user_api.get(files_path, params={'page': 1, 'page_size': 10})
        assert_status(resp, 403)

    async with client('config', token=tenant_a_admin.access_token) as api:
        resp = await api.get(
            '/aidp-mgmt/knowledge-bases/nonexistent-kds-xyz/files',
            params={'page': 1, 'page_size': 10},
        )
        assert_status(resp, 404)
        assert tenant_a_admin.password not in resp.text
        assert tenant_a_admin.access_token not in resp.text
