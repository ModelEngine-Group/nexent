-- =============================================================================
-- Add Foreign Key Constraint to ag_a2a_message_t
-- =============================================================================
-- Version: v2.0.2
-- Date: 2026-04-20
-- Description: Add foreign key constraint on task_id referencing ag_a2a_task_t(id)
-- Target Table: nexent.ag_a2a_message_t
-- =============================================================================

-- Add foreign key constraint: task_id references ag_a2a_task_t(id) with CASCADE delete
ALTER TABLE nexent.ag_a2a_message_t
    ADD CONSTRAINT ag_a2a_message_t_task_id_fk
    FOREIGN KEY (task_id)
    REFERENCES nexent.ag_a2a_task_t(id) ON DELETE CASCADE;
