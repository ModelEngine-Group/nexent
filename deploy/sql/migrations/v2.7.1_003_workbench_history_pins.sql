-- Account-scoped Workbench preferences; all writers serialize scope uniqueness.
CREATE TABLE IF NOT EXISTS nexent.conversation_workbench_pin_t (
    pin_id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    conversation_id INT4 NOT NULL,
    pinned_at TIMESTAMPTZ NOT NULL,
    created_by VARCHAR(100),
    create_time TIMESTAMP DEFAULT NOW(),
    updated_by VARCHAR(100),
    update_time TIMESTAMP DEFAULT NOW(),
    delete_flag VARCHAR(1) DEFAULT 'N'
);
COMMENT ON COLUMN nexent.conversation_workbench_pin_t.pin_id IS 'Technical identifier of a Workbench pin';
COMMENT ON COLUMN nexent.conversation_workbench_pin_t.user_id IS 'Authenticated owner of the pin';
COMMENT ON COLUMN nexent.conversation_workbench_pin_t.tenant_id IS 'Authenticated tenant scope of the pin';
COMMENT ON COLUMN nexent.conversation_workbench_pin_t.conversation_id IS 'Owned active Workbench conversation; integrity enforced by pin service';
COMMENT ON COLUMN nexent.conversation_workbench_pin_t.pinned_at IS 'Server-generated monotonic pin time; repinning refreshes ordering';
COMMENT ON COLUMN nexent.conversation_workbench_pin_t.created_by IS 'Creating authenticated user';
COMMENT ON COLUMN nexent.conversation_workbench_pin_t.create_time IS 'Creation time of the pin record';
COMMENT ON COLUMN nexent.conversation_workbench_pin_t.updated_by IS 'Last authenticated user to change the pin';
COMMENT ON COLUMN nexent.conversation_workbench_pin_t.update_time IS 'Last pin or unpin operation time';
COMMENT ON COLUMN nexent.conversation_workbench_pin_t.delete_flag IS 'Soft deletion: N pinned, Y unpinned';
CREATE INDEX IF NOT EXISTS idx_workbench_pin_scope_order
    ON nexent.conversation_workbench_pin_t (user_id, tenant_id, pinned_at DESC, pin_id DESC)
    WHERE delete_flag = 'N';
