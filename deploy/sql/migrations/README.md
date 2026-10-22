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
`v2.4_merged_migrations.sql`, and migrations since v2.4.0 are consolidated in
`v2.5.0_merged_migrations.sql`, `v2.6.0_merged_migrations.sql` (which merges
all migrations applied after the v2.5.1 release, through v2.6.0),
`v2.7.0_merged_migrations.sql` (which merges all migrations applied after
the v2.6.1 release, through v2.7.0), and `v2.8.0_merged_migrations.sql`
(which merges every migration file still loose after the v2.7.0 release).
Newer migrations remain separate until their minor-version history is
consolidated.

A filename prefix records the release the migration targets when it is written,
not the develop version at that moment, so repeated prefixes and skipped
versions do occur. Deployment order comes only from `sort -V` over the file
names; never infer it from the authored sequence.

Important: do NOT modify a `*_merged_migrations.sql` file after it has been
deployed. Because it bundles many historical migrations, even a comment-only
edit will trip the cascade and re-execute every subsequent file, which can
take a long time on large merges. Use a new versioned file (for example
`v2.6.0_xxxx_*.sql`) for any change after the merge.

`v2.7.1_005_remove_agent_prompt_templates.sql` removes the retired private Agent prompt-template table and Agent binding columns. Historical initialization and merged migrations remain unchanged. Prompt generation uses bundled SDK defaults after this migration.

The unified Agent prompt migrations are appended to `v2.7.0_merged_migrations.sql` in this order: Agent section consolidation, frozen marketplace JSON consolidation, and physical `duty_prompt` to `prompt` rename. The previously committed `v2.7.1_005_unify_agent_prompts.sql` remains for migration history and safely becomes a no-op after the merged file. The new marketplace and rename sections have no separate migration files. This requested update changes the merged file checksum, so the migration runner re-applies that file and cascades to subsequent migrations.
