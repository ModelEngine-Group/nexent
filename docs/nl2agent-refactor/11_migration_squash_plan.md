# NL2Agent migration squash plan

## Scope

The feature is unreleased, so the clean branch must not replay its prototype evolution. Replace these snapshot migrations:

- `v2.3.0_0716_add_nl2agent_session.sql`
- `v2.3.0_0717_index_nl2agent_session_cleanup.sql`
- `v2.3.0_0717_share_nl2agent_catalog_snapshots.sql`
- `v2.3.0_0717_unique_nl2agent_builder.sql`
- `v2.3.0_0718_persist_nl2agent_runner.sql`

with one new release migration whose final identifier is selected against the clean branch's release train. Do not carry backfills for Redis-era `session_catalogs`, `catalog_revision`, nullable Runner IDs, MD5/SHA snapshot transitions or the shared snapshot table.

## Final migration content

In dependency order:

1. Create `nl2agent_session_t` exactly as specified in `05_persistence_simplification.md`, including inline `catalog_snapshot`.
2. Create owner/recovery/retention indexes and unique tenant+Draft/Conversation constraints.
3. Create `nl2agent_installation_operation_t` with unique stable key, checkpoint, lease and cleanup indexes.
4. Add the partial unique index for one undeleted tenant NL2Agent Runner using the existing Agent table and its canonical internal identity.
5. Add comments and permissions consistent with neighboring Nexent tables.
6. Make the SQL idempotent under the repository's checksum + advisory-lock runner where project conventions require replayability.

The migration must not seed tenant data. Runner provisioning remains idempotent application behavior because tenants are dynamic.

## Fresh-install parity

Apply the identical final table/constraint/index definitions to every fresh-install source used by this repository:

- `deploy/sql/init.sql` in the documented baseline/snapshot layout;
- any Docker fresh schema path present on the clean branch;
- `k8s/helm/nexent/charts/nexent-common/files/init.sql` if that path exists in the target branch, as required by repository migration policy.

The current snapshot uses `deploy/sql/init.sql` rather than the path named in the supplied AGENTS overview; this must be reconciled against the clean branch at implementation time. Generated or templated copies must come from one SQL source if the deployment tooling supports it.

## Local migration guard

Keep the standard `deploy/common/run_local_sql_migrations.py` mechanism but replace checks tied to v0718 with final-schema assertions:

- both tables exist;
- Runner ID, workflow revision and inline catalog are non-null;
- operation unique/lease indexes exist;
- the obsolete shared snapshot table and Redis-era columns are absent on a clean installation;
- final migration ID/checksum is recorded.

Omit `repair_nl2agent_tables.py` from the clean branch. It is explicitly described as temporary and cannot establish complete provenance.

## Review and test procedure

1. Build a database at the documented baseline and run the one final migration.
2. Build a fresh database from init SQL.
3. Compare tables, columns, defaults, nullability, constraints and indexes.
4. Run the migration twice through the standard runner and verify checksum/idempotency behavior.
5. Run two migration processes concurrently and verify the existing advisory lock serializes them.
6. Run Session start, installation claim and Finalize transaction integration tests against the resulting schema.
7. Verify no code or test refers to the five prototype migration IDs, shared catalog table, Redis keys or repair tool.

## Rollout and rollback

The final migration lands in PR5 with the feature flag still off. Deployment applies it before enablement. Rollback is disabling the feature; destructive down-migration is not required and must not be automatic. Because no released NL2Agent data is migrated, no prototype-data compatibility path belongs in production.
