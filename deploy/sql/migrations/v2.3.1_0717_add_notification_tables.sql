-- Migration: Add notification_t and notification_receiver_t tables
-- Date: 2026-07-17
-- Description: In-app notification message table plus per-user fan-out delivery/read table.

SET search_path TO nexent;

-- notification_t: one row per message
CREATE SEQUENCE IF NOT EXISTS nexent.notification_t_notification_id_seq;

CREATE TABLE IF NOT EXISTS nexent.notification_t (
    notification_id BIGINT NOT NULL DEFAULT nextval('nexent.notification_t_notification_id_seq'),
    event_type VARCHAR(50) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    unique_id BIGINT,
    details JSONB,
    scope VARCHAR(20) NOT NULL,
    tenant_id VARCHAR(100),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT notification_t_pkey PRIMARY KEY (notification_id)
);

ALTER SEQUENCE nexent.notification_t_notification_id_seq
    OWNED BY nexent.notification_t.notification_id;
ALTER TABLE nexent.notification_t OWNER TO root;

COMMENT ON TABLE nexent.notification_t IS 'In-app notification message table; per-user delivery lives in notification_receiver_t';
COMMENT ON COLUMN nexent.notification_t.notification_id IS 'Notification ID, unique primary key';
COMMENT ON COLUMN nexent.notification_t.event_type IS 'Event type, e.g. repository_review_approved / repository_review_rejected';
COMMENT ON COLUMN nexent.notification_t.resource_type IS 'Resource type, e.g. agent_repository / skill_repository / mcp_repository';
COMMENT ON COLUMN nexent.notification_t.unique_id IS 'Related resource primary key (e.g. agent_repository_id)';
COMMENT ON COLUMN nexent.notification_t.details IS 'i18n interpolation details for the event template';
COMMENT ON COLUMN nexent.notification_t.scope IS 'Audience scope: SU / TENANT / TENANT_ADMIN / TENANT_USER / USER';
COMMENT ON COLUMN nexent.notification_t.tenant_id IS 'Target tenant; NULL for SU scope';
COMMENT ON COLUMN nexent.notification_t.is_active IS 'Whether this notification is still active/valid';
COMMENT ON COLUMN nexent.notification_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.notification_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.notification_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.notification_t.updated_by IS 'Updater ID';
COMMENT ON COLUMN nexent.notification_t.delete_flag IS 'Soft delete flag: Y/N';

CREATE INDEX IF NOT EXISTS ix_notification_event_resource_unique_active
    ON nexent.notification_t (event_type, resource_type, unique_id, is_active);

-- notification_receiver_t: one row per receiver (fan-out)
CREATE SEQUENCE IF NOT EXISTS nexent.notification_receiver_t_receiver_id_seq;

CREATE TABLE IF NOT EXISTS nexent.notification_receiver_t (
    receiver_id BIGINT NOT NULL DEFAULT nextval('nexent.notification_receiver_t_receiver_id_seq'),
    notification_id BIGINT NOT NULL,
    receiver_user_id VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(100),
    is_read BOOLEAN DEFAULT FALSE,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT notification_receiver_t_pkey PRIMARY KEY (receiver_id)
);

ALTER SEQUENCE nexent.notification_receiver_t_receiver_id_seq
    OWNED BY nexent.notification_receiver_t.receiver_id;
ALTER TABLE nexent.notification_receiver_t OWNER TO root;

COMMENT ON TABLE nexent.notification_receiver_t IS 'Per-user notification delivery and read status (fan-out from notification_t)';
COMMENT ON COLUMN nexent.notification_receiver_t.receiver_id IS 'Receiver row ID, unique primary key';
COMMENT ON COLUMN nexent.notification_receiver_t.notification_id IS 'FK to notification_t.notification_id';
COMMENT ON COLUMN nexent.notification_receiver_t.receiver_user_id IS 'Receiver user ID';
COMMENT ON COLUMN nexent.notification_receiver_t.tenant_id IS 'Tenant ID for multi-tenancy isolation';
COMMENT ON COLUMN nexent.notification_receiver_t.is_read IS 'Whether this receiver has read the notification';
COMMENT ON COLUMN nexent.notification_receiver_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.notification_receiver_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.notification_receiver_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.notification_receiver_t.updated_by IS 'Updater ID';
COMMENT ON COLUMN nexent.notification_receiver_t.delete_flag IS 'Soft delete flag: Y/N';

CREATE INDEX IF NOT EXISTS ix_notification_receiver_user_read
    ON nexent.notification_receiver_t (receiver_user_id, is_read);
CREATE INDEX IF NOT EXISTS ix_notification_receiver_notification_id
    ON nexent.notification_receiver_t (notification_id);

-- update_time triggers
CREATE OR REPLACE FUNCTION update_notification_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_notification_update_time_trigger ON nexent.notification_t;
CREATE TRIGGER update_notification_update_time_trigger
BEFORE UPDATE ON nexent.notification_t
FOR EACH ROW
EXECUTE FUNCTION update_notification_update_time();

CREATE OR REPLACE FUNCTION update_notification_receiver_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_notification_receiver_update_time_trigger ON nexent.notification_receiver_t;
CREATE TRIGGER update_notification_receiver_update_time_trigger
BEFORE UPDATE ON nexent.notification_receiver_t
FOR EACH ROW
EXECUTE FUNCTION update_notification_receiver_update_time();

ALTER TABLE nexent.ag_agent_repository_t
    ADD COLUMN IF NOT EXISTS content TEXT;

COMMENT ON COLUMN nexent.ag_agent_repository_t.content IS
    'Listing note on submit or review opinion on approve/reject';

ALTER TABLE nexent.ag_agent_repository_t
    ADD COLUMN IF NOT EXISTS content TEXT;

COMMENT ON COLUMN nexent.ag_agent_repository_t.content IS
    'Listing note on submit or review opinion on approve/reject';

ALTER TABLE nexent.ag_skill_repository_t
    ADD COLUMN IF NOT EXISTS content TEXT;

COMMENT ON COLUMN nexent.ag_skill_repository_t.content IS
    'Listing note on submit or review opinion on approve/reject';
