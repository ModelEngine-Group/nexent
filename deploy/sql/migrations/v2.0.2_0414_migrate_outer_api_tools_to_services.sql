-- Migration: Convert ag_outer_api_tools (tool-level) to ag_outer_api_services (service-level)
-- Date: 2026-04-09
-- Description: Each OpenAPI service now stores one record instead of one record per tool.
--             Only service-level fields (mcp_service_name, openapi_json, server_url, etc.) are kept.

-- Step 1: Create new table for services
CREATE TABLE IF NOT EXISTS nexent.ag_outer_api_services (
    id BIGSERIAL PRIMARY KEY,
    mcp_service_name VARCHAR(100) NOT NULL,
    description TEXT,
    openapi_json JSONB,
    server_url VARCHAR(500),
    headers_template JSONB,
    tenant_id VARCHAR(100) NOT NULL,
    is_available BOOLEAN DEFAULT TRUE,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Step 2: Migrate data - one record per service
-- Use DISTINCT ON to get one record per (tenant_id, mcp_service_name)
-- Order by update_time DESC to keep the most recently updated record
INSERT INTO nexent.ag_outer_api_services (
    mcp_service_name,
    description,
    openapi_json,
    server_url,
    headers_template,
    tenant_id,
    is_available,
    create_time,
    update_time,
    created_by,
    updated_by,
    delete_flag
)
SELECT DISTINCT ON (t.tenant_id, t.mcp_service_name)
    t.mcp_service_name,
    t.description,
    t.openapi_json,
    t.server_url,
    t.headers_template,
    t.tenant_id,
    COALESCE(t.is_available, TRUE) as is_available,
    t.create_time,
    t.update_time,
    t.created_by,
    t.updated_by,
    t.delete_flag
FROM nexent.ag_outer_api_tools t
WHERE t.delete_flag != 'Y'
ORDER BY t.tenant_id, t.mcp_service_name, t.update_time DESC
ON CONFLICT DO NOTHING;

-- Step 3: Verify migration
SELECT 'Migrated services count: ' || COUNT(*) FROM nexent.ag_outer_api_services;

-- Step 4: Drop old table after successful migration
DROP TABLE IF EXISTS nexent.ag_outer_api_tools;

-- Step 5: Drop the old sequence (no longer needed)
DROP SEQUENCE IF EXISTS nexent.ag_outer_api_tools_id_seq;
