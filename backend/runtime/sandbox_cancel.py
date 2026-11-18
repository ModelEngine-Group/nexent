# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Allow trusted Config callers to signal a run without impersonating its owner."""

from runtime.sandbox_journal import SandboxRunJournal


def signal_distributed_cancel(client, *, deployment_id, namespace, tenant_id, user_id, conversation_id,
                              expected_generation=None, cancel_ttl):
    if any(not isinstance(value, str) or not value for value in (deployment_id, namespace, tenant_id, user_id)):
        raise ValueError('Distributed cancellation requires trusted deployment, tenant and user identities')
    key = SandboxRunJournal.business_key(deployment_id, namespace, tenant_id, user_id, conversation_id)
    prefix = 'runtime:ksm:state:' + key
    return bool(client.eval("""
        local leased = redis.call('HGET', KEYS[1], 'run_id')
        local indexed = redis.call('HGET', KEYS[2], 'generation')
        local current = leased or indexed
        if not current then return 0 end
        if ARGV[1] ~= '' and current ~= ARGV[1] then
            if current ~= indexed or redis.call('HGET', KEYS[2], 'automation_generation') ~= ARGV[1] then
                return 0
            end
        end
        local run = ARGV[2] .. ':' .. current
        if not leased then
            local status = redis.call('HGET', run, 'status')
            if status ~= 'running' and status ~= 'preparing' then return 0 end
        end
        redis.call('SETEX', run .. ':cancel', ARGV[3], current)
        return 1
    """, 2, 'runtime:ksm:lease:' + key, prefix + ':current',
        str(expected_generation) if expected_generation is not None else '', prefix, cancel_ttl))


def request_distributed_cancel(tenant_id, user_id, conversation_id, expected_generation=None):
    from contracts.constants import environment as settings
    from infrastructure.redis.run_state import runtime_state_service

    return signal_distributed_cancel(runtime_state_service.client,
        deployment_id=settings.NEXENT_RUNTIME_DEPLOYMENT_ID, namespace=settings.KUBERNETES_NAMESPACE,
        tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id,
        expected_generation=expected_generation, cancel_ttl=settings.RUNTIME_CANCEL_TTL_SECONDS)
