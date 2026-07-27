-- Migration: Phase 2 Memory Architecture - records and retrieval hit tables
-- Date: 2026-07-13
-- Description: Create `memory_records_t` (authoritative memory store) and
-- `memory_retrieval_hits_t` (per-hit log for Dreaming aggregation) for the
-- Memory Architecture Phase 2 implementation.
--
-- Design notes:
-- * `memory_records_t` is the single source of truth for tenant/user/agent
--   memory. Tenant and user long-term memories live in PG only; agent
--   short-term memory is mirrored into Elasticsearch by
--   `services.memory_index_service`.
-- * `memory_retrieval_hits_t` is written by the `search_memory` flow so the
--   Dreaming scheduler can aggregate recall statistics in batch.
-- * Soft delete uses `delete_flag` matching the rest of the schema; soft
--   deleted rows are filtered by every read access layer.
-- * All isolation keys follow the existing `memory_user_config_t` style
--   (varchar(100)) to keep tenant/user queries consistent across tables.
-- * Primary keys use PostgreSQL `SERIAL4` shorthand (which implicitly creates
--   a backing sequence + NOT NULL + PRIMARY KEY), avoiding the verbose
--   `int4 + DEFAULT nextval(...) + CONSTRAINT ... PRIMARY KEY` triplet.
-- * Idempotent: uses `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ADD COLUMN IF NOT EXISTS`,
--   `CREATE INDEX IF NOT EXISTS`, and `DROP TRIGGER IF EXISTS` so it is safe to
--   re-run even if the tables already exist from a prior partial run.

SET search_path TO nexent;
BEGIN;

-- Authoritative memory record store (create only if not exists).
CREATE TABLE IF NOT EXISTS nexent."memory_records_t" (
    "memory_id"          SERIAL4 PRIMARY KEY,
    "tenant_id"          varchar(100) COLLATE "pg_catalog"."default" NOT NULL,
    "user_id"            varchar(100) COLLATE "pg_catalog"."default" NOT NULL,
    "agent_id"           varchar(100) COLLATE "pg_catalog"."default",
    "conversation_id"    varchar(100) COLLATE "pg_catalog"."default",
    "layer"              varchar(30)  COLLATE "pg_catalog"."default" NOT NULL,
    "memory_type"        varchar(30)  COLLATE "pg_catalog"."default",
    "status"             varchar(30)  COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'active',
    "content"            text         COLLATE "pg_catalog"."default" NOT NULL,
    "concept_tags"       text[]       COLLATE "pg_catalog"."default",
    "es_index_name"      varchar(255) COLLATE "pg_catalog"."default",
    "create_time"        timestamp DEFAULT CURRENT_TIMESTAMP,
    "update_time"        timestamp DEFAULT CURRENT_TIMESTAMP,
    "created_by"         varchar(100) COLLATE "pg_catalog"."default",
    "updated_by"         varchar(100) COLLATE "pg_catalog"."default",
    "delete_flag"        varchar(1)   COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'N'::character varying,
    "idempotency_key"    varchar(128) COLLATE "pg_catalog"."default" NOT NULL,
    "recall_count"       int4         NOT NULL DEFAULT 0,
    "daily_count"        int4         NOT NULL DEFAULT 0,
    "grounded_count"     int4         NOT NULL DEFAULT 0,
    "last_recalled_at"   timestamp,
    "query_hashes"       text[]       COLLATE "pg_catalog"."default",
    "recall_days"        text[]       COLLATE "pg_catalog"."default",
    "light_hits"         int4         NOT NULL DEFAULT 0,
    "rem_hits"           int4         NOT NULL DEFAULT 0,
    "last_light_at"      timestamp,
    "last_rem_at"        timestamp
);

ALTER TABLE nexent."memory_records_t" OWNER TO "root";

COMMENT ON COLUMN nexent."memory_records_t"."memory_id" IS 'Auto-incremented memory primary key (serial4).';
COMMENT ON COLUMN nexent."memory_records_t"."tenant_id" IS 'Tenant ID (isolation key).';
COMMENT ON COLUMN nexent."memory_records_t"."user_id" IS 'User ID (isolation key for user/agent layers).';
COMMENT ON COLUMN nexent."memory_records_t"."agent_id" IS 'Agent ID (isolation key for agent short-term layer).';
COMMENT ON COLUMN nexent."memory_records_t"."conversation_id" IS 'Conversation ID (further isolation key for agent).';
COMMENT ON COLUMN nexent."memory_records_t"."layer" IS 'Memory layer: tenant | user | agent.';
COMMENT ON COLUMN nexent."memory_records_t"."memory_type" IS 'Memory type: long_term | short_term.';
COMMENT ON COLUMN nexent."memory_records_t"."status" IS 'Status: active | archived | disabled.';
COMMENT ON COLUMN nexent."memory_records_t"."content" IS 'Memory content.';
COMMENT ON COLUMN nexent."memory_records_t"."concept_tags" IS 'Optional concept tags from Dreaming REM phase.';
COMMENT ON COLUMN nexent."memory_records_t"."es_index_name" IS 'Elasticsearch index for agent short-term memory (mem_<model>_<dim>); null for PG-only layers.';
COMMENT ON COLUMN nexent."memory_records_t"."create_time" IS 'Creation time, audit field.';
COMMENT ON COLUMN nexent."memory_records_t"."update_time" IS 'Update time, audit field.';
COMMENT ON COLUMN nexent."memory_records_t"."created_by" IS 'Creator ID, audit field.';
COMMENT ON COLUMN nexent."memory_records_t"."updated_by" IS 'Last updater ID, audit field.';
COMMENT ON COLUMN nexent."memory_records_t"."delete_flag" IS 'Soft delete flag (Y/N).';
COMMENT ON COLUMN nexent."memory_records_t"."idempotency_key" IS 'Idempotency key for write deduplication.';
COMMENT ON COLUMN nexent."memory_records_t"."recall_count" IS 'Total recall hit count.';
COMMENT ON COLUMN nexent."memory_records_t"."daily_count" IS 'Recall hit count for the most recent active day.';
COMMENT ON COLUMN nexent."memory_records_t"."grounded_count" IS 'Count of grounded (verified) recalls.';
COMMENT ON COLUMN nexent."memory_records_t"."last_recalled_at" IS 'Most recent recall timestamp.';
COMMENT ON COLUMN nexent."memory_records_t"."query_hashes" IS 'Hashes of queries that recalled this memory.';
COMMENT ON COLUMN nexent."memory_records_t"."recall_days" IS 'ISO date strings of recall days.';
COMMENT ON COLUMN nexent."memory_records_t"."light_hits" IS 'Light Sleep phase hit count.';
COMMENT ON COLUMN nexent."memory_records_t"."rem_hits" IS 'REM Sleep phase hit count.';
COMMENT ON COLUMN nexent."memory_records_t"."last_light_at" IS 'Last Light Sleep timestamp.';
COMMENT ON COLUMN nexent."memory_records_t"."last_rem_at" IS 'Last REM Sleep timestamp.';
COMMENT ON TABLE  nexent."memory_records_t" IS 'Authoritative store for tenant/user/agent memory (Phase 2).';

-- Idempotent indexes (safe to re-run).
CREATE INDEX IF NOT EXISTS "idx_memory_records_tenant"
    ON nexent."memory_records_t" ("tenant_id");
CREATE INDEX IF NOT EXISTS "idx_memory_records_user"
    ON nexent."memory_records_t" ("tenant_id", "user_id");
CREATE INDEX IF NOT EXISTS "idx_memory_records_agent"
    ON nexent."memory_records_t" ("tenant_id", "user_id", "agent_id", "conversation_id");
CREATE INDEX IF NOT EXISTS "idx_memory_records_idempotency"
    ON nexent."memory_records_t" ("tenant_id", "idempotency_key");
CREATE INDEX IF NOT EXISTS "idx_memory_records_status"
    ON nexent."memory_records_t" ("tenant_id", "user_id", "layer", "status");

-- Per-hit retrieval log for Dreaming aggregation (create only if not exists).
CREATE TABLE IF NOT EXISTS nexent."memory_retrieval_hits_t" (
    "hit_id"             SERIAL4 PRIMARY KEY,
    "tenant_id"          varchar(100) COLLATE "pg_catalog"."default",
    "user_id"            varchar(100) COLLATE "pg_catalog"."default",
    "agent_id"           varchar(100) COLLATE "pg_catalog"."default",
    "conversation_id"    varchar(100) COLLATE "pg_catalog"."default",
    "memory_id"          int4,
    "query_text"         text         COLLATE "pg_catalog"."default",
    "query_hash"         varchar(128) COLLATE "pg_catalog"."default",
    "retrieval_score"    numeric(38, 18),
    "source"             varchar(100)  COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'nexent',
    "occurred_at"        timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "day"                varchar(100)  COLLATE "pg_catalog"."default",
    "grounded"           boolean      NOT NULL DEFAULT false,
    "create_time"        timestamp DEFAULT CURRENT_TIMESTAMP,
    "update_time"        timestamp DEFAULT CURRENT_TIMESTAMP,
    "created_by"         varchar(100) COLLATE "pg_catalog"."default",
    "updated_by"         varchar(100) COLLATE "pg_catalog"."default",
    "delete_flag"        varchar(1)   COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'N'::character varying
);

ALTER TABLE nexent."memory_retrieval_hits_t" OWNER TO "root";

COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."hit_id" IS 'Hit primary key (serial4).';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."tenant_id" IS 'Tenant ID.';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."user_id" IS 'User ID.';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."agent_id" IS 'Agent ID.';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."conversation_id" IS 'Conversation ID.';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."memory_id" IS 'Recalled memory id (null on miss rows).';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."query_text" IS 'Original search query text.';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."query_hash" IS 'Stable hash of the query text.';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."retrieval_score" IS 'Similarity score reported by the backend.';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."source" IS 'Hit origin: nexent | external_provider.';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."occurred_at" IS 'Time the hit was recorded.';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."day" IS 'ISO date string (occurred_at::date).';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."grounded" IS 'Whether the hit was verified/grounded.';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."create_time" IS 'Row creation time.';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."update_time" IS 'Row last update time.';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."created_by" IS 'User that created the row.';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."updated_by" IS 'User that last updated the row.';
COMMENT ON COLUMN nexent."memory_retrieval_hits_t"."delete_flag" IS 'Soft delete flag (N = active, Y = deleted).';
COMMENT ON TABLE  nexent."memory_retrieval_hits_t" IS 'Per-hit memory retrieval log; consumed by Dreaming scheduler.';

CREATE INDEX IF NOT EXISTS "idx_memory_retrieval_hits_memory"
    ON nexent."memory_retrieval_hits_t" ("memory_id", "occurred_at");
CREATE INDEX IF NOT EXISTS "idx_memory_retrieval_hits_tenant_user_agent"
    ON nexent."memory_retrieval_hits_t" ("tenant_id", "user_id", "agent_id", "day");

-- Trigger to keep update_time fresh on UPDATE (idempotent: drop first, then create).
CREATE OR REPLACE FUNCTION nexent."update_memory_records_update_time"()
RETURNS TRIGGER AS $$
BEGIN
    NEW."update_time" = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS "update_memory_records_update_time_trigger" ON nexent."memory_records_t";
CREATE TRIGGER "update_memory_records_update_time_trigger"
BEFORE UPDATE ON nexent."memory_records_t"
FOR EACH ROW
EXECUTE FUNCTION nexent."update_memory_records_update_time"();

-- Trigger to keep memory_retrieval_hits_t.update_time fresh on UPDATE.
CREATE OR REPLACE FUNCTION nexent."update_memory_retrieval_hits_update_time"()
RETURNS TRIGGER AS $$
BEGIN
    NEW."update_time" = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS "update_memory_retrieval_hits_update_time_trigger" ON nexent."memory_retrieval_hits_t";
CREATE TRIGGER "update_memory_retrieval_hits_update_time_trigger"
BEFORE UPDATE ON nexent."memory_retrieval_hits_t"
FOR EACH ROW
EXECUTE FUNCTION nexent."update_memory_retrieval_hits_update_time"();

COMMIT;
