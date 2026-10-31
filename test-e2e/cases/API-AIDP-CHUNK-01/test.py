# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""D2 contract test for AIDP knowledge base chunk settings.

Proves the running HTTP contract for the chunk configuration introduced by
commit 01400d399: creation defaults of 512 tokens / 51 overlap tokens with
Top K 10 and similarity 0, an editable chunk setting through PUT, the
half-of-chunk-size overlap ceiling on both verbs, and detail read-back of the
chunk fields as top level values.
"""

from __future__ import annotations

import uuid

import pytest

from shared.http import assert_status, client, response_message

CASE_ID = 'API-AIDP-CHUNK-01'


def _run_tag() -> str:
    return uuid.uuid4().hex[:8]


async def _create_kb(api, run_tag: str, extra: dict | None = None) -> dict:
    """Create a run-owned AIDP knowledge base and return its kds_id."""
    payload = {
        'name': 'aidp-chunk-%s' % run_tag,
        'description': 'chunk settings contract %s' % run_tag,
        'embedding_model': 'bge-m3',
    }
    if extra:
        payload.update(extra)
    response = await api.post('/aidp-mgmt/knowledge-bases', json=payload)
    assert_status(response, 200)
    body = response.json()
    kds_id = body.get('kds_id') or body.get('id')
    assert kds_id, 'create response must carry a kds_id, got %r' % (body,)
    return body


async def _cleanup(api, kds_ids: list[str]) -> None:
    for kds_id in kds_ids:
        try:
            await api.delete('/aidp-mgmt/knowledge-bases/%s' % kds_id)
        except Exception:  # noqa: BLE001 - cleanup is best effort and must not mask results
            pass


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D2')
async def test_aidp_chunk_settings_contract(tenant_a_admin, tenant_b_admin):
    """Chunk defaults, editable chunk settings, overlap ceiling and detail read-back."""
    run_tag = _run_tag()
    created: list[str] = []

    async with client('config', token=tenant_a_admin.access_token) as api:
        try:
            # ---- AC-01: creation without chunk fields uses the AIDP defaults ----
            created_body = await _create_kb(api, run_tag)
            kds_id = str(created_body.get('kds_id') or created_body.get('id'))
            created.append(kds_id)

            detail_response = await api.get('/aidp-mgmt/knowledge-bases/%s' % kds_id)
            assert_status(detail_response, 200)
            detail = detail_response.json()

            # AC-02: chunk fields come back as top level values, not nested or stringly typed.
            assert detail.get('chunk_token_num') == 512, (
                'creation default chunk_token_num must be 512 (AIDP default), got %r'
                % (detail.get('chunk_token_num'),)
            )
            assert detail.get('chunk_overlap_num') == 51, (
                'creation default chunk_overlap_num must be 51 (10% of 512), got %r'
                % (detail.get('chunk_overlap_num'),)
            )
            assert isinstance(detail.get('chunk_token_num'), int), (
                'chunk_token_num must be an int in the detail response, got %r'
                % (type(detail.get('chunk_token_num')).__name__,)
            )
            assert detail.get('topk') == 10, (
                'creation default topk must be 10, got %r' % (detail.get('topk'),)
            )
            assert float(detail.get('similarity') or 0) == 0.0, (
                'creation default similarity must be 0, got %r' % (detail.get('similarity'),)
            )

            # ---- AC-03: editing only the chunk fields updates just those fields ----
            before = dict(detail)
            update_response = await api.put(
                '/aidp-mgmt/knowledge-bases/%s' % kds_id,
                json={'chunk_token_num': 1024, 'chunk_overlap_num': 102},
            )
            assert_status(update_response, 200)

            reread_response = await api.get('/aidp-mgmt/knowledge-bases/%s' % kds_id)
            assert_status(reread_response, 200)
            after = reread_response.json()
            assert after.get('chunk_token_num') == 1024, (
                'chunk_token_num must persist the edited value 1024, got %r'
                % (after.get('chunk_token_num'),)
            )
            assert after.get('chunk_overlap_num') == 102, (
                'chunk_overlap_num must persist the edited value 102, got %r'
                % (after.get('chunk_overlap_num'),)
            )
            for field in ('name', 'description', 'embedding_model'):
                assert after.get(field) == before.get(field), (
                    'field %r must be unchanged by a chunk-only update: before=%r after=%r'
                    % (field, before.get(field), after.get(field))
                )

            # ---- AC-04: overlap above half the chunk size is rejected on update ----
            oversize_response = await api.put(
                '/aidp-mgmt/knowledge-bases/%s' % kds_id,
                json={'chunk_token_num': 256, 'chunk_overlap_num': 129},
            )
            assert oversize_response.status_code in (400, 422), (
                'overlap above half of chunk size must be rejected, got %s'
                % (oversize_response.status_code,)
            )
            assert 'chunk_overlap_num' in response_message(oversize_response).lower() or (
                'chunk_overlap_num' in oversize_response.text.lower()
            ), 'rejection must name chunk_overlap_num, got %r' % (response_message(oversize_response),)

            # The rejected update must not partially write.
            guarded_response = await api.get('/aidp-mgmt/knowledge-bases/%s' % kds_id)
            assert_status(guarded_response, 200)
            guarded = guarded_response.json()
            assert guarded.get('chunk_token_num') == 1024 and guarded.get('chunk_overlap_num') == 102, (
                'a rejected overlap must leave the previous chunk configuration intact, got %r/%r'
                % (guarded.get('chunk_token_num'), guarded.get('chunk_overlap_num'))
            )

            # ---- AC-04: exactly half is accepted (ceiling is inclusive) ----
            half_response = await api.put(
                '/aidp-mgmt/knowledge-bases/%s' % kds_id,
                json={'chunk_token_num': 256, 'chunk_overlap_num': 128},
            )
            assert_status(half_response, 200)
            half_reread = await api.get('/aidp-mgmt/knowledge-bases/%s' % kds_id)
            assert_status(half_reread, 200)
            half_body = half_reread.json()
            assert half_body.get('chunk_token_num') == 256 and half_body.get('chunk_overlap_num') == 128, (
                'overlap equal to half of the chunk size must be accepted, got %r/%r'
                % (half_body.get('chunk_token_num'), half_body.get('chunk_overlap_num'))
            )

            # ---- AC-04: creation rejects an oversized overlap too ----
            reject_response = await api.post(
                '/aidp-mgmt/knowledge-bases',
                json={
                    'name': 'aidp-chunk-%s-reject' % run_tag,
                    'description': 'oversized overlap must be rejected',
                    'embedding_model': 'bge-m3',
                    'chunk_token_num': 512,
                    'chunk_overlap_num': 257,
                },
            )
            assert reject_response.status_code in (400, 422), (
                'creation with overlap above half of chunk size must be rejected, got %s'
                % (reject_response.status_code,)
            )

            # ---- AC-05: a cross-tenant chunk update is denied ----
            await _cleanup(api, [kds_id])
            created.clear()

        finally:
            await _cleanup(api, created)

    # Cross-tenant denial needs a second identity, so it runs in its own client.
    async with client('config', token=tenant_a_admin.access_token) as owner_api:
        try:
            cross_body = await _create_kb(owner_api, '%s-cross' % run_tag)
            cross_kds_id = str(cross_body.get('kds_id') or cross_body.get('id'))
            created.append(cross_kds_id)

            async with client('config', token=tenant_b_admin.access_token) as other_api:
                cross_response = await other_api.put(
                    '/aidp-mgmt/knowledge-bases/%s' % cross_kds_id,
                    json={'chunk_token_num': 2048, 'chunk_overlap_num': 204},
                )
            assert cross_response.status_code in (401, 403, 404), (
                'a cross-tenant chunk update must be denied, got %s'
                % (cross_response.status_code,)
            )

            still_response = await owner_api.get('/aidp-mgmt/knowledge-bases/%s' % cross_kds_id)
            assert_status(still_response, 200)
            still = still_response.json()
            assert still.get('chunk_token_num') == 512, (
                'a denied cross-tenant update must not change the owner configuration, got %r'
                % (still.get('chunk_token_num'),)
            )
        finally:
            await _cleanup(owner_api, created)
