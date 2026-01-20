-- Add invitation code and group management system
-- This migration adds invitation codes, groups, and permission management features

-- 1. Create tenant_invitation_code_t table for invitation codes
CREATE TABLE IF NOT EXISTS nexent.tenant_invitation_code_t (
    invitation_id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    invitation_code VARCHAR(100) NOT NULL,
    group_ids VARCHAR, -- int4 list
    capacity INT4 NOT NULL DEFAULT 1,
    expiry_date TIMESTAMP(6) WITHOUT TIME ZONE,
    status VARCHAR(30) NOT NULL,
    code_type VARCHAR(30) NOT NULL,
    create_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    update_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Add comments for tenant_invitation_code_t table
COMMENT ON TABLE nexent.tenant_invitation_code_t IS 'Tenant invitation code information table';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.invitation_id IS 'Invitation ID, primary key';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.tenant_id IS 'Tenant ID, foreign key';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.invitation_code IS 'Invitation code';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.group_ids IS 'Associated group IDs list';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.capacity IS 'Invitation code capacity';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.expiry_date IS 'Invitation code expiry date';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.status IS 'Invitation code status: IN_USE, EXPIRE, DISABLE, RUN_OUT';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.code_type IS 'Invitation code type: ADMIN_INVITE, DEV_INVITE, USER_INVITE';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.create_time IS 'Create time';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.created_by IS 'Created by';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.updated_by IS 'Updated by';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.delete_flag IS 'Delete flag, Y/N';

-- 2. Create tenant_invitation_record_t table for invitation usage records
CREATE TABLE IF NOT EXISTS nexent.tenant_invitation_record_t (
    invitation_record_id SERIAL PRIMARY KEY,
    invitation_id INT4 NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    create_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    update_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Add comments for tenant_invitation_record_t table
COMMENT ON TABLE nexent.tenant_invitation_record_t IS 'Tenant invitation record table';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.invitation_record_id IS 'Invitation record ID, primary key';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.invitation_id IS 'Invitation ID, foreign key';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.user_id IS 'User ID';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.create_time IS 'Create time';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.created_by IS 'Created by';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.updated_by IS 'Updated by';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.delete_flag IS 'Delete flag, Y/N';

-- 3. Create tenant_group_info_t table for group information
CREATE TABLE IF NOT EXISTS nexent.tenant_group_info_t (
    group_id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_description VARCHAR(500),
    create_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    update_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Add comments for tenant_group_info_t table
COMMENT ON TABLE nexent.tenant_group_info_t IS 'Tenant group information table';
COMMENT ON COLUMN nexent.tenant_group_info_t.group_id IS 'Group ID, primary key';
COMMENT ON COLUMN nexent.tenant_group_info_t.tenant_id IS 'Tenant ID, foreign key';
COMMENT ON COLUMN nexent.tenant_group_info_t.group_name IS 'Group name';
COMMENT ON COLUMN nexent.tenant_group_info_t.group_description IS 'Group description';
COMMENT ON COLUMN nexent.tenant_group_info_t.create_time IS 'Create time';
COMMENT ON COLUMN nexent.tenant_group_info_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.tenant_group_info_t.created_by IS 'Created by';
COMMENT ON COLUMN nexent.tenant_group_info_t.updated_by IS 'Updated by';
COMMENT ON COLUMN nexent.tenant_group_info_t.delete_flag IS 'Delete flag, Y/N';

-- 4. Create tenant_group_user_t table for group user membership
CREATE TABLE IF NOT EXISTS nexent.tenant_group_user_t (
    group_user_id SERIAL PRIMARY KEY,
    group_id INT4 NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    create_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    update_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Add comments for tenant_group_user_t table
COMMENT ON TABLE nexent.tenant_group_user_t IS 'Tenant group user membership table';
COMMENT ON COLUMN nexent.tenant_group_user_t.group_user_id IS 'Group user ID, primary key';
COMMENT ON COLUMN nexent.tenant_group_user_t.group_id IS 'Group ID, foreign key';
COMMENT ON COLUMN nexent.tenant_group_user_t.user_id IS 'User ID, foreign key';
COMMENT ON COLUMN nexent.tenant_group_user_t.create_time IS 'Create time';
COMMENT ON COLUMN nexent.tenant_group_user_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.tenant_group_user_t.created_by IS 'Created by';
COMMENT ON COLUMN nexent.tenant_group_user_t.updated_by IS 'Updated by';
COMMENT ON COLUMN nexent.tenant_group_user_t.delete_flag IS 'Delete flag, Y/N';

-- 5. Add fields to user_tenant_t table
ALTER TABLE nexent.user_tenant_t
ADD COLUMN IF NOT EXISTS user_role VARCHAR(30);

-- Add comments for new fields in user_tenant_t table
COMMENT ON COLUMN nexent.user_tenant_t.user_role IS 'User role: SU, ADMIN, DEV, USER';

-- 6. Create role_permission_t table for role permissions
CREATE TABLE IF NOT EXISTS nexent.role_permission_t (
    role_permission_id SERIAL PRIMARY KEY,
    user_role VARCHAR(30) NOT NULL,
    permission_category VARCHAR(30),
    permission_type VARCHAR(30),
    permission_subtype VARCHAR(30)
);

-- Add comments for role_permission_t table
COMMENT ON TABLE nexent.role_permission_t IS 'Role permission configuration table';
COMMENT ON COLUMN nexent.role_permission_t.role_permission_id IS 'Role permission ID, primary key';
COMMENT ON COLUMN nexent.role_permission_t.user_role IS 'User role: SU, ADMIN, DEV, USER';
COMMENT ON COLUMN nexent.role_permission_t.permission_category IS 'Permission category';
COMMENT ON COLUMN nexent.role_permission_t.permission_type IS 'Permission type';
COMMENT ON COLUMN nexent.role_permission_t.permission_subtype IS 'Permission subtype';

-- 7. Add fields to knowledge_record_t table
ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS group_ids VARCHAR, -- int4 list
ADD COLUMN IF NOT EXISTS ingroup_permission VARCHAR(30);

-- Add comments for new fields in knowledge_record_t table
COMMENT ON COLUMN nexent.knowledge_record_t.group_ids IS 'Knowledge base group IDs list';
COMMENT ON COLUMN nexent.knowledge_record_t.ingroup_permission IS 'In-group permission: EDIT, READ_ONLY, PRIVATE';

-- 8. Add fields to ag_tenant_agent_t table
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS group_ids VARCHAR; -- int4 list

-- Add comments for new fields in ag_tenant_agent_t table
COMMENT ON COLUMN nexent.ag_tenant_agent_t.group_ids IS 'Agent group IDs list';

-- 9. Insert role permission data
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(2, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
(3, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
(4, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-tools'),
(5, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring'),
(6, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
(7, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(8, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
(9, 'SU', 'RESOURCE', 'AGENT', 'READ'),
(10, 'SU', 'RESOURCE', 'AGENT', 'DELETE'),
(11, 'SU', 'RESOURCE', 'KB', 'READ'),
(12, 'SU', 'RESOURCE', 'KB', 'DELETE'),
(13, 'SU', 'RESOURCE', 'KB.GROUPS', 'READ'),
(14, 'SU', 'RESOURCE', 'KB.GROUPS', 'UPDATE'),
(15, 'SU', 'RESOURCE', 'KB.GROUPS', 'DELETE'),
(16, 'SU', 'RESOURCE', 'USER.ROLE', 'READ'),
(17, 'SU', 'RESOURCE', 'USER.ROLE', 'UPDATE'),
(18, 'SU', 'RESOURCE', 'USER.ROLE', 'DELETE'),
(19, 'SU', 'RESOURCE', 'MCP', 'READ'),
(20, 'SU', 'RESOURCE', 'MCP', 'DELETE'),
(21, 'SU', 'RESOURCE', 'MEM.SETTING', 'READ'),
(22, 'SU', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(23, 'SU', 'RESOURCE', 'MEM.AGENT', 'READ'),
(24, 'SU', 'RESOURCE', 'MEM.AGENT', 'DELETE'),
(25, 'SU', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(26, 'SU', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(27, 'SU', 'RESOURCE', 'MODEL', 'CREATE'),
(28, 'SU', 'RESOURCE', 'MODEL', 'READ'),
(29, 'SU', 'RESOURCE', 'MODEL', 'UPDATE'),
(30, 'SU', 'RESOURCE', 'MODEL', 'DELETE'),
(31, 'SU', 'RESOURCE', 'TENANT', 'CREATE'),
(32, 'SU', 'RESOURCE', 'TENANT', 'READ'),
(33, 'SU', 'RESOURCE', 'TENANT', 'UPDATE'),
(34, 'SU', 'RESOURCE', 'TENANT', 'DELETE'),
(35, 'SU', 'RESOURCE', 'TENANT.INFO', 'READ'),
(36, 'SU', 'RESOURCE', 'TENANT.INFO', 'UPDATE'),
(37, 'SU', 'RESOURCE', 'TENANT.INVITE', 'CREATE'),
(38, 'SU', 'RESOURCE', 'TENANT.INVITE', 'READ'),
(39, 'SU', 'RESOURCE', 'TENANT.INVITE', 'UPDATE'),
(40, 'SU', 'RESOURCE', 'TENANT.INVITE', 'DELETE'),
(41, 'SU', 'RESOURCE', 'GROUP', 'CREATE'),
(42, 'SU', 'RESOURCE', 'GROUP', 'READ'),
(43, 'SU', 'RESOURCE', 'GROUP', 'UPDATE'),
(44, 'SU', 'RESOURCE', 'GROUP', 'DELETE'),
(45, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(46, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(47, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/setup'),
(48, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
(49, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/market'),
(50, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents'),
(51, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
(52, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-tools'),
(53, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring'),
(54, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
(55, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(56, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
(57, 'ADMIN', 'RESOURCE', 'AGENT', 'CREATE'),
(58, 'ADMIN', 'RESOURCE', 'AGENT', 'READ'),
(59, 'ADMIN', 'RESOURCE', 'AGENT', 'UPDATE'),
(60, 'ADMIN', 'RESOURCE', 'AGENT', 'DELETE'),
(61, 'ADMIN', 'RESOURCE', 'KB', 'CREATE'),
(62, 'ADMIN', 'RESOURCE', 'KB', 'READ'),
(63, 'ADMIN', 'RESOURCE', 'KB', 'UPDATE'),
(64, 'ADMIN', 'RESOURCE', 'KB', 'DELETE'),
(65, 'ADMIN', 'RESOURCE', 'KB.GROUPS', 'READ'),
(66, 'ADMIN', 'RESOURCE', 'KB.GROUPS', 'UPDATE'),
(67, 'ADMIN', 'RESOURCE', 'KB.GROUPS', 'DELETE'),
(68, 'ADMIN', 'RESOURCE', 'USER.ROLE', 'READ'),
(69, 'ADMIN', 'RESOURCE', 'MCP', 'CREATE'),
(70, 'ADMIN', 'RESOURCE', 'MCP', 'READ'),
(71, 'ADMIN', 'RESOURCE', 'MCP', 'UPDATE'),
(72, 'ADMIN', 'RESOURCE', 'MCP', 'DELETE'),
(73, 'ADMIN', 'RESOURCE', 'MEM.SETTING', 'READ'),
(74, 'ADMIN', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(75, 'ADMIN', 'RESOURCE', 'MEM.AGENT', 'CREATE'),
(76, 'ADMIN', 'RESOURCE', 'MEM.AGENT', 'READ'),
(77, 'ADMIN', 'RESOURCE', 'MEM.AGENT', 'DELETE'),
(78, 'ADMIN', 'RESOURCE', 'MEM.PRIVATE', 'CREATE'),
(79, 'ADMIN', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(80, 'ADMIN', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(81, 'ADMIN', 'RESOURCE', 'MODEL', 'CREATE'),
(82, 'ADMIN', 'RESOURCE', 'MODEL', 'READ'),
(83, 'ADMIN', 'RESOURCE', 'MODEL', 'UPDATE'),
(84, 'ADMIN', 'RESOURCE', 'MODEL', 'DELETE'),
(85, 'ADMIN', 'RESOURCE', 'TENANT.INFO', 'READ'),
(86, 'ADMIN', 'RESOURCE', 'TENANT.INFO', 'UPDATE'),
(87, 'ADMIN', 'RESOURCE', 'TENANT.INVITE', 'CREATE'),
(88, 'ADMIN', 'RESOURCE', 'TENANT.INVITE', 'READ'),
(89, 'ADMIN', 'RESOURCE', 'TENANT.INVITE', 'UPDATE'),
(90, 'ADMIN', 'RESOURCE', 'TENANT.INVITE', 'DELETE'),
(91, 'ADMIN', 'RESOURCE', 'GROUP', 'CREATE'),
(92, 'ADMIN', 'RESOURCE', 'GROUP', 'READ'),
(93, 'ADMIN', 'RESOURCE', 'GROUP', 'UPDATE'),
(94, 'ADMIN', 'RESOURCE', 'GROUP', 'DELETE'),
(95, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(96, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(97, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/setup'),
(98, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
(99, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/market'),
(100, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents'),
(101, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
(102, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-tools'),
(103, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring'),
(104, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
(105, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(106, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
(107, 'DEV', 'RESOURCE', 'AGENT', 'CREATE'),
(108, 'DEV', 'RESOURCE', 'AGENT', 'READ'),
(109, 'DEV', 'RESOURCE', 'AGENT', 'UPDATE'),
(110, 'DEV', 'RESOURCE', 'AGENT', 'DELETE'),
(111, 'DEV', 'RESOURCE', 'KB', 'CREATE'),
(112, 'DEV', 'RESOURCE', 'KB', 'READ'),
(113, 'DEV', 'RESOURCE', 'KB', 'UPDATE'),
(114, 'DEV', 'RESOURCE', 'KB', 'DELETE'),
(115, 'DEV', 'RESOURCE', 'KB.GROUPS', 'READ'),
(116, 'DEV', 'RESOURCE', 'KB.GROUPS', 'UPDATE'),
(117, 'DEV', 'RESOURCE', 'KB.GROUPS', 'DELETE'),
(118, 'DEV', 'RESOURCE', 'USER.ROLE', 'READ'),
(119, 'DEV', 'RESOURCE', 'MCP', 'CREATE'),
(120, 'DEV', 'RESOURCE', 'MCP', 'READ'),
(121, 'DEV', 'RESOURCE', 'MCP', 'UPDATE'),
(122, 'DEV', 'RESOURCE', 'MCP', 'DELETE'),
(123, 'DEV', 'RESOURCE', 'MEM.SETTING', 'READ'),
(124, 'DEV', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(125, 'DEV', 'RESOURCE', 'MEM.AGENT', 'READ'),
(126, 'DEV', 'RESOURCE', 'MEM.PRIVATE', 'CREATE'),
(127, 'DEV', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(128, 'DEV', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(129, 'DEV', 'RESOURCE', 'MODEL', 'READ'),
(130, 'DEV', 'RESOURCE', 'TENANT.INFO', 'READ'),
(131, 'DEV', 'RESOURCE', 'GROUP', 'READ'),
(132, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(133, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(134, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
(135, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
(136, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
(137, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(138, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
(139, 'USER', 'RESOURCE', 'AGENT', 'READ'),
(140, 'USER', 'RESOURCE', 'KB', 'CREATE'),
(141, 'USER', 'RESOURCE', 'KB', 'READ'),
(142, 'USER', 'RESOURCE', 'KB', 'UPDATE'),
(143, 'USER', 'RESOURCE', 'KB', 'DELETE'),
(144, 'USER', 'RESOURCE', 'KB.GROUPS', 'READ'),
(145, 'USER', 'RESOURCE', 'KB.GROUPS', 'UPDATE'),
(146, 'USER', 'RESOURCE', 'KB.GROUPS', 'DELETE'),
(147, 'USER', 'RESOURCE', 'USER.ROLE', 'READ'),
(148, 'USER', 'RESOURCE', 'MCP', 'CREATE'),
(149, 'USER', 'RESOURCE', 'MCP', 'READ'),
(150, 'USER', 'RESOURCE', 'MCP', 'UPDATE'),
(151, 'USER', 'RESOURCE', 'MCP', 'DELETE'),
(152, 'USER', 'RESOURCE', 'MEM.SETTING', 'READ'),
(153, 'USER', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(154, 'USER', 'RESOURCE', 'MEM.AGENT', 'READ'),
(155, 'USER', 'RESOURCE', 'MEM.PRIVATE', 'CREATE'),
(156, 'USER', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(157, 'USER', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(158, 'USER', 'RESOURCE', 'MODEL', 'READ'),
(159, 'USER', 'RESOURCE', 'TENANT.INFO', 'READ'),
(160, 'USER', 'RESOURCE', 'GROUP', 'READ'),
(161, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(162, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(163, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/setup'),
(164, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
(165, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/market'),
(166, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents'),
(167, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
(168, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-tools'),
(169, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring'),
(170, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
(171, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(172, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
(173, 'SPEED', 'RESOURCE', 'AGENT', 'CREATE'),
(174, 'SPEED', 'RESOURCE', 'AGENT', 'READ'),
(175, 'SPEED', 'RESOURCE', 'AGENT', 'UPDATE'),
(176, 'SPEED', 'RESOURCE', 'AGENT', 'DELETE'),
(177, 'SPEED', 'RESOURCE', 'KB', 'CREATE'),
(178, 'SPEED', 'RESOURCE', 'KB', 'READ'),
(179, 'SPEED', 'RESOURCE', 'KB', 'UPDATE'),
(180, 'SPEED', 'RESOURCE', 'KB', 'DELETE'),
(181, 'SPEED', 'RESOURCE', 'KB.GROUPS', 'READ'),
(182, 'SPEED', 'RESOURCE', 'KB.GROUPS', 'UPDATE'),
(183, 'SPEED', 'RESOURCE', 'KB.GROUPS', 'DELETE'),
(184, 'SPEED', 'RESOURCE', 'USER.ROLE', 'READ'),
(185, 'SPEED', 'RESOURCE', 'MCP', 'CREATE'),
(186, 'SPEED', 'RESOURCE', 'MCP', 'READ'),
(187, 'SPEED', 'RESOURCE', 'MCP', 'UPDATE'),
(188, 'SPEED', 'RESOURCE', 'MCP', 'DELETE'),
(189, 'SPEED', 'RESOURCE', 'MEM.SETTING', 'READ'),
(190, 'SPEED', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(191, 'SPEED', 'RESOURCE', 'MEM.AGENT', 'CREATE'),
(192, 'SPEED', 'RESOURCE', 'MEM.AGENT', 'READ'),
(193, 'SPEED', 'RESOURCE', 'MEM.AGENT', 'DELETE'),
(194, 'SPEED', 'RESOURCE', 'MEM.PRIVATE', 'CREATE'),
(195, 'SPEED', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(196, 'SPEED', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(197, 'SPEED', 'RESOURCE', 'MODEL', 'CREATE'),
(198, 'SPEED', 'RESOURCE', 'MODEL', 'READ'),
(199, 'SPEED', 'RESOURCE', 'MODEL', 'UPDATE'),
(200, 'SPEED', 'RESOURCE', 'MODEL', 'DELETE'),
(201, 'SPEED', 'RESOURCE', 'TENANT.INFO', 'READ'),
(202, 'SPEED', 'RESOURCE', 'TENANT.INFO', 'UPDATE'),
(203, 'SPEED', 'RESOURCE', 'TENANT.INVITE', 'CREATE'),
(204, 'SPEED', 'RESOURCE', 'TENANT.INVITE', 'READ'),
(205, 'SPEED', 'RESOURCE', 'TENANT.INVITE', 'UPDATE'),
(206, 'SPEED', 'RESOURCE', 'TENANT.INVITE', 'DELETE'),
(207, 'SPEED', 'RESOURCE', 'GROUP', 'CREATE'),
(208, 'SPEED', 'RESOURCE', 'GROUP', 'READ'),
(209, 'SPEED', 'RESOURCE', 'GROUP', 'UPDATE'),
(210, 'SPEED', 'RESOURCE', 'GROUP', 'DELETE')
ON CONFLICT (role_permission_id) DO NOTHING;