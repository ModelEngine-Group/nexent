# SQL Migration Layout

Nexent keeps deployment SQL in versioned migration files under this directory.
The migration runner uses the SQL file name as the migration ID and stores the
current file checksum in `nexent.schema_migrations`.

Execution rules:

- Files are discovered with `*.sql` and sorted by version-aware filename order.
- A file with no migration record is executed and recorded as `applied`.
- A file with the same recorded checksum is skipped.
- A file with a different recorded checksum is executed again, then its checksum,
  execution time, app version, and source file are updated.

Keep migration SQL idempotent because changing an existing file causes it to run
again. Use patterns such as `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD
COLUMN IF NOT EXISTS`, and conflict-safe inserts where possible.

`deploy/sql/init.sql` is the initial baseline before these incremental files.

Historical migrations through v2.4.0 are consolidated by minor version in
`v2.2_merged_migrations.sql`, `v2.3_merged_migrations.sql`, and
`v2.4_merged_migrations.sql`. Newer migrations remain separate until their
minor-version history is consolidated.
