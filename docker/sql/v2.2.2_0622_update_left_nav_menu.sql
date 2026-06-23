-- ============================================================
-- Menu Structure Migration V2
-- Migration Date: 2026-06-22
-- ============================================================

-- Step 1: Clear all existing LEFT_NAV_MENU permissions
DELETE FROM nexent.role_permission_t
WHERE permission_category = 'VISIBILITY' AND permission_type = 'LEFT_NAV_MENU';

ALTER TABLE role_permission_t 
ADD COLUMN IF NOT EXISTS parent_key VARCHAR(50);
-- ============================================================
-- New Menu Structure:
-- ROOT:  /, /chat, /agent-dev, /resource-space, /resource-manage, /owner-manage, /users
-- AGENT-DEV: /models, /knowledges, /agents, /memory
-- RESOURCE-SPACE: /agent-repository, /mcp-space, /skill-space
-- ============================================================
-- ID Format: <role_prefix>xx
--   SU=10xx, ADMIN=11xx, DEV=12xx, USER=13xx, SPEED=14xx, ASSET_OWNER=15xx
-- parent_key: NULL for first-level, parent route for second-level
-- ============================================================

-- SU Menus (root level)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1001, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(1002, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-manage');

-- ADMIN Menus (root level)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1101, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(1102, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(1103, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-dev'),
(1104, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-space'),
(1105, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-manage'),
(1106, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/users');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1107, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/models', '/agent-dev'),
(1108, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges', '/agent-dev'),
(1109, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents', '/agent-dev'),
(1110, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory', '/agent-dev');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1111, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-repository', '/resource-space'),
(1112, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-space', '/resource-space'),
(1113, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/skill-space', '/resource-space');

-- DEV Menus (NO /resource-manage, root level)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1201, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(1202, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(1203, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-dev'),
(1204, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-space'),
(1205, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/users');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1206, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/models', '/agent-dev'),
(1207, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges', '/agent-dev'),
(1208, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents', '/agent-dev'),
(1209, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory', '/agent-dev');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1210, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-repository', '/resource-space'),
(1211, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-space', '/resource-space'),
(1212, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/skill-space', '/resource-space');

-- USER Menus (Minimal, all root level)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1301, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(1302, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(1303, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(1304, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/users');

-- SPEED Menus (root level)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1401, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(1402, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(1403, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-dev'),
(1404, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-space'),
(1405, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-manage');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1406, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/models', '/agent-dev'),
(1407, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges', '/agent-dev'),
(1408, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents', '/agent-dev'),
(1409, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory', '/agent-dev');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1410, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-repository', '/resource-space'),
(1411, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-space', '/resource-space'),
(1412, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/skill-space', '/resource-space');

-- ASSET_OWNER Menus (root level)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1501, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(1502, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(1503, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-dev'),
(1504, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-space'),
(1505, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/owner-manage');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1506, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/models', '/agent-dev'),
(1507, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges', '/agent-dev'),
(1508, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents', '/agent-dev');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1509, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-repository', '/resource-space'),
(1510, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-space', '/resource-space'),
(1511, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/skill-space', '/resource-space');