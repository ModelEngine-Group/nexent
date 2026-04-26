-- Fix missing A2A tables for v2.0.3
-- Run this script to create all missing A2A protocol tables

-- =============================================================================
-- Table 1: ag_a2a_nacos_config_t
-- Purpose: Store Nacos server configuration for external A2A agent discovery
-- =============================================================================
CREATE TABLE IF NOT EXISTS nexent.ag_a2a_nacos_config_t (
    id BIGSERIAL PRIMARY KEY,
    config_id VARCHAR(64) UNIQUE NOT NULL,
    nacos_addr VARCHAR(512) NOT NULL,
    nacos_username VARCHAR(100),
    nacos_password VARCHAR(256),
    namespace_id VARCHAR(100) DEFAULT 'public',
    name VARCHAR(100) NOT NULL,
    description TEXT,
    tenant_id VARCHAR(100) NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    last_scan_at TIMESTAMP(6),
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- =============================================================================
-- Table 2: ag_a2a_external_agent_t
-- Purpose: Cache external A2A agents discovered from URL or Nacos
-- =============================================================================
CREATE TABLE IF NOT EXISTS nexent.ag_a2a_external_agent_t (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    version VARCHAR(50),
    agent_url VARCHAR(512) NOT NULL,
    protocol_type VARCHAR(20) DEFAULT 'JSONRPC',
    streaming BOOLEAN DEFAULT FALSE,
    supported_interfaces JSONB,
    source_type VARCHAR(20) NOT NULL,
    source_url VARCHAR(512),
    nacos_config_id VARCHAR(64),
    nacos_agent_name VARCHAR(255),
    tenant_id VARCHAR(100) NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100),
    raw_card JSONB,
    cached_at TIMESTAMP(6),
    cache_expires_at TIMESTAMP(6),
    is_available BOOLEAN DEFAULT TRUE,
    last_check_at TIMESTAMP(6),
    last_check_result VARCHAR(50),
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- =============================================================================
-- Table 3: ag_a2a_external_agent_relation_t
-- Purpose: Relation between local agent and external A2A agent
-- =============================================================================
CREATE TABLE IF NOT EXISTS nexent.ag_a2a_external_agent_relation_t (
    id BIGSERIAL PRIMARY KEY,
    local_agent_id INTEGER NOT NULL,
    external_agent_id BIGINT NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    is_enabled BOOLEAN DEFAULT TRUE,
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT uq_local_external_agent UNIQUE (local_agent_id, external_agent) DEFERRABLE INITIALLY DEFERRED
);

-- =============================================================================
-- Table 4: ag_a2a_server_agent_t
-- Purpose: Local agents registered as A2A Server endpoints
-- =============================================================================
CREATE TABLE IF NOT EXISTS nexent.ag_a2a_server_agent_t (
    id BIGSERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    endpoint_id VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    version VARCHAR(50),
    agent_url VARCHAR(512),
    streaming BOOLEAN DEFAULT FALSE,
    supported_interfaces JSONB,
    card_overrides JSONB,
    is_enabled BOOLEAN DEFAULT FALSE,
    raw_card JSONB,
    published_at TIMESTAMP(6),
    unpublished_at TIMESTAMP(6),
    response_format VARCHAR(20) DEFAULT 'task',
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- =============================================================================
-- Table 5: ag_a2a_task_t
-- Purpose: A2A tasks for tracking requests
-- =============================================================================
CREATE TABLE IF NOT EXISTS nexent.ag_a2a_task_t (
    id BIGSERIAL PRIMARY KEY,
    task_id VARCHAR(64) UNIQUE NOT NULL,
    endpoint_id VARCHAR(64) NOT NULL,
    agent_id INTEGER NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    mode VARCHAR(20) DEFAULT 'standard',
    session_id VARCHAR(100),
    parent_task_id VARCHAR(64),
    input_data JSONB,
    output_data JSONB,
    error_message TEXT,
    created_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP(6),
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- =============================================================================
-- Table 6: ag_a2a_message_t
-- Purpose: A2A messages within tasks
-- =============================================================================
CREATE TABLE IF NOT EXISTS nexent.ag_a2a_message_t (
    id BIGSERIAL PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    message_id VARCHAR(64) UNIQUE NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT,
    attachments JSONB,
    metadata JSONB,
    is_final BOOLEAN DEFAULT FALSE,
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA nexent TO "root";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA nexent TO "root";

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_a2a_external_agent_tenant ON nexent.ag_a2a_external_agent_t(tenant_id);
CREATE INDEX IF NOT EXISTS idx_a2a_server_agent_endpoint ON nexent.ag_a2a_server_agent_t(endpoint_id);
CREATE INDEX IF NOT EXISTS idx_a2a_server_agent_tenant ON nexent.ag_a2a_server_agent_t(tenant_id);
CREATE INDEX IF NOT EXISTS idx_a2a_task_tenant ON nexent.ag_a2a_task_t(tenant_id);
CREATE INDEX IF NOT EXISTS idx_a2a_task_task_id ON nexent.ag_a2a_task_t(task_id);
CREATE INDEX IF NOT EXISTS idx_a2a_message_task_id ON nexent.ag_a2a_message_t(task_id);

-- Add foreign key constraint for ag_a2a_external_agent_relation_t (separate due to table order)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_external_agent'
        AND table_schema = 'nexent'
        AND table_name = 'ag_a2a_external_agent_relation_t'
    ) THEN
        ALTER TABLE nexent.ag_a2a_external_agent_relation_t
        ADD CONSTRAINT fk_external_agent
        FOREIGN KEY (external_agent_id)
        REFERENCES nexent.ag_a2a_external_agent_t(id)
        DEFERRABLE INITIALLY DEFERRED;
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Foreign key constraint already exists or cannot be added: %', SQLERRM;
END $$;

-- Add foreign key constraint for ag_a2a_message_t
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_task_id'
        AND table_schema = 'nexent'
        AND table_name = 'ag_a2a_message_t'
    ) THEN
        ALTER TABLE nexent.ag_a2a_message_t
        ADD CONSTRAINT fk_task_id
        FOREIGN KEY (task_id)
        REFERENCES nexent.ag_a2a_task_t(task_id)
        DEFERRABLE INITIALLY DEFERRED;
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Foreign key constraint already exists or cannot be added: %', SQLERRM;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_endpoint_id'
        AND table_schema = 'nexent'
        AND table_name = 'ag_a2a_task_t'
    ) THEN
        ALTER TABLE nexent.ag_a2a_task_t
        ADD CONSTRAINT fk_endpoint_id
        FOREIGN KEY (endpoint_id)
        REFERENCES nexent.ag_a2a_server_agent_t(endpoint_id)
        DEFERRABLE INITIALLY DEFERRED;
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Foreign key constraint already exists or cannot be added: %', SQLERRM;
END $$;

SELECT 'A2A tables created successfully!' AS result;
