-- Add missing delete_flag column to document_tag_projection.
-- The table was created from a hand-written DDL that omitted this column,
-- but the SQLAlchemy model inherits TableBase which defines delete_flag.

ALTER TABLE nexent.document_tag_projection
    ADD COLUMN IF NOT EXISTS delete_flag VARCHAR(1) NOT NULL DEFAULT 'N';
