-- Migration: Rename tenant-memory permissions from MEM.AGENT to MEM.TENANT
-- Date: 2026-07-25
-- Description: Align permission names with the tenant memory layer they govern.

SET search_path TO nexent;

UPDATE nexent.role_permission_t
SET permission_type = 'MEM.TENANT'
WHERE permission_type = 'MEM.AGENT';
