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

Cascading re-apply:

- When any file is re-applied because its checksum changed, the runner marks
  every subsequent file (including the changed one) as "dirty" for the rest of
  that session, regardless of whether their own checksums still match. This is
  necessary because a destructive statement earlier in the chain (for example
  `DROP COLUMN`) may have rolled the schema back to a state a later file was
  compensating against; skipping that later file would leave the database in
  an inconsistent state. The cascade is one-way: once tripped, it stays
  tripped until the end of the deployment. A subsequent deployment with no
  changed files starts with a clean cascade flag.
- `deploy/sql/init.sql` runs unconditionally on every startup and does not
  participate in the cascade. Keep its statements idempotent.

Keep migration SQL idempotent because changing an existing file causes it to run
again. Use patterns such as `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD
COLUMN IF NOT EXISTS`, and conflict-safe inserts where possible.

`deploy/sql/init.sql` is the initial baseline before these incremental files.

Historical migrations through v2.4.0 are consolidated by minor version in
`v2.2_merged_migrations.sql`, `v2.3_merged_migrations.sql`, and
`v2.4_merged_migrations.sql`. Newer migrations remain separate until their
minor-version history is consolidated.

Important: do NOT modify a `*_merged_migrations.sql` file after it has been
deployed. Because it bundles many historical migrations, even a comment-only
edit will trip the cascade and re-execute every subsequent file, which can
take a long time on large merges. Use a new versioned file (for example
`v2.6.0_xxxx_*.sql`) for any change after the merge.
