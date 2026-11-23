-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.evolution_release_skill_t
    ADD COLUMN IF NOT EXISTS sandbox_image varchar(71)
        CHECK (sandbox_image ~ '^sha256:[a-f0-9]{64}$');
COMMENT ON COLUMN nexent.evolution_release_skill_t.sandbox_image IS
    'Immutable sandbox image verified for a reviewed script revision of this Skill.';
