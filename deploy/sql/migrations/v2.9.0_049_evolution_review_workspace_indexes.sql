-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE INDEX IF NOT EXISTS idx_evolution_review_batch_scope
    ON nexent.evolution_review_batch_t (tenant_id, agent_id, agent_version_no, batch_id DESC);

CREATE INDEX IF NOT EXISTS idx_evolution_review_turn_batch
    ON nexent.evolution_review_turn_t (batch_id, turn_id DESC) WHERE batch_id IS NOT NULL;
