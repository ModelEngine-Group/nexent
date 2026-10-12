from __future__ import annotations

import pytest

from backend.utils.config_utils import (
    CONTEXT_COMPACTION_TRIGGER_RATIO_KEY,
    LEGACY_CONTEXT_SOFT_LIMIT_RATIO_KEY,
    TenantConfigManager,
)
from nexent.core.models.capacity_budget import (
    CapacityReservePolicy,
    InvalidReservePolicy,
)


TEST_TENANT = 'tenant-a'


@pytest.mark.case_id('UT-BE-AUTO-70481C0B221C926E')
@pytest.mark.stage('D1')
def test_get_capacity_reserve_policy_key_migration_and_legacy_fallback(monkeypatch):
    manager = TenantConfigManager()
    stubbed_config: dict[str, str] = {}

    def stub_load_config(self, tenant_id, force_reload=False):
        return stubbed_config

    monkeypatch.setattr(TenantConfigManager, 'load_config', stub_load_config)

    # Scenario A: canonical key drives the policy
    stubbed_config.clear()
    stubbed_config[CONTEXT_COMPACTION_TRIGGER_RATIO_KEY] = '0.8'
    policy_a = manager.get_capacity_reserve_policy(TEST_TENANT)
    assert isinstance(policy_a, CapacityReservePolicy)
    assert policy_a.compaction_trigger_ratio == 0.8
    assert policy_a.compaction_trigger_ratio_source == 'tenant_config'

    # Scenario B: canonical missing -> legacy payload fallback
    stubbed_config.clear()
    stubbed_config[LEGACY_CONTEXT_SOFT_LIMIT_RATIO_KEY] = '0.9'
    policy_b = manager.get_capacity_reserve_policy(TEST_TENANT)
    assert isinstance(policy_b, CapacityReservePolicy)
    assert policy_b.compaction_trigger_ratio == 0.9
    assert policy_b.compaction_trigger_ratio_source == 'legacy_payload'

    # Scenario C: canonical wins over legacy when both present
    stubbed_config.clear()
    stubbed_config[CONTEXT_COMPACTION_TRIGGER_RATIO_KEY] = '0.8'
    stubbed_config[LEGACY_CONTEXT_SOFT_LIMIT_RATIO_KEY] = '0.9'
    policy_c = manager.get_capacity_reserve_policy(TEST_TENANT)
    assert policy_c.compaction_trigger_ratio == 0.8
    assert policy_c.compaction_trigger_ratio_source == 'tenant_config'

    # Scenario D: both keys absent -> code default policy
    stubbed_config.clear()
    policy_d = manager.get_capacity_reserve_policy(TEST_TENANT)
    assert isinstance(policy_d, CapacityReservePolicy)
    assert policy_d.compaction_trigger_ratio == 0.8
    assert policy_d.compaction_trigger_ratio_source == 'code_default'

    # Scenario E1: non-numeric canonical value fails closed
    stubbed_config.clear()
    stubbed_config[CONTEXT_COMPACTION_TRIGGER_RATIO_KEY] = 'abc'
    with pytest.raises(InvalidReservePolicy) as exc_e1:
        manager.get_capacity_reserve_policy(TEST_TENANT)
    assert 'context.compaction_trigger_ratio must be a decimal in (0, 1]' in str(exc_e1.value)

    # Scenario E2: out-of-range canonical value fails closed
    stubbed_config.clear()
    stubbed_config[CONTEXT_COMPACTION_TRIGGER_RATIO_KEY] = '1.5'
    with pytest.raises(InvalidReservePolicy) as exc_e2:
        manager.get_capacity_reserve_policy(TEST_TENANT)
    assert 'context.compaction_trigger_ratio must be a decimal in (0, 1]' in str(exc_e2.value)
