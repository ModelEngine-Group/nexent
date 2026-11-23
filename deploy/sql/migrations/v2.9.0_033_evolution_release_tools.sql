-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE TABLE IF NOT EXISTS nexent.evolution_release_excluded_tool_t (
    tenant_id varchar(100) NOT NULL,
    agent_id integer NOT NULL,
    version_no integer NOT NULL CHECK (version_no > 0),
    tool_name varchar NOT NULL CHECK (length(tool_name) > 0),
    PRIMARY KEY (tenant_id, agent_id, version_no, tool_name)
);
COMMENT ON TABLE nexent.evolution_release_excluded_tool_t IS 'Confirmed exclusions from the effective tool catalog of one Agent version.';
COMMENT ON COLUMN nexent.evolution_release_excluded_tool_t.tenant_id IS 'Owning tenant.';
COMMENT ON COLUMN nexent.evolution_release_excluded_tool_t.agent_id IS 'Business Agent whose tool catalog was evaluated.';
COMMENT ON COLUMN nexent.evolution_release_excluded_tool_t.version_no IS 'Published version that enforces this selection.';
COMMENT ON COLUMN nexent.evolution_release_excluded_tool_t.tool_name IS 'Effective tool name removed before prompt assembly and Runtime registration.';
