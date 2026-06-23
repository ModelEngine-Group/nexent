# SQL Migration Layout

Nexent keeps deployment SQL in merged version groups:

- `v1_merged_migrations.sql`: all 1.x migrations
- `v2.0_merged_migrations.sql`: all 2.0.x migrations
- `v2.1_merged_migrations.sql`: all 2.1.x migrations
- `v2.2_merged_migrations.sql`: all 2.2.x migrations

Each source section must keep these markers:

```sql
-- nexent-migration-source: v2.2.1_YYYY_description.sql
-- nexent-migration-checksum: <sha256 of the original section>
-- nexent-migration-probe: SELECT ...
```

`deploy/common/run-sql-migrations.sh` records and skips migrations by
`nexent-migration-source`, not by the merged file name. This preserves
compatibility with databases that already recorded the historical per-file
migration IDs.

`deploy/sql/init.sql` is the initial baseline before
`v1.1.0_0619_add_tenant_config_t.sql`. These merged files contain only
incremental SQL after that baseline. When `schema_migrations` is missing on an
existing database, the runner uses each source section probe to decide whether
the section can be recorded as `baselined`; a missing or failing probe stops
startup instead of guessing.
