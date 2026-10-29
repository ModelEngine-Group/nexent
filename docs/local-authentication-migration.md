# Local authentication and historical account migration

Nexent authenticates users with its existing PostgreSQL database. The application
does not require Supabase, GoTrue or Kong. The optional `speed` deployment mode is
an explicitly unauthenticated demo; the default is `full` local authentication.

## Preserved behavior

Email/password registration still requires an invitation. Canonical role/email are stored on the account. Groups, permission definitions,
business ownership and API keys keep their existing tables.
OAuth provider flows and CAS ticket validation, renewal and single logout remain
available. Provider account creation and email lookup use the local account store.

Ordinary authentication uses signed JWTs without a server-side session table.
The legacy `session` response envelope remains compatible with the frontend BFF;
its `refresh_token` is empty. Ordinary JWTs expire after `JWT_EXPIRY` seconds and
require login again. `/user/refresh_token` rejects old credentials with 401.
Logout clears cookies; an ordinary copied JWT remains valid until its deadline.
Password changes increment the account credential revision and invalidate prior
JWTs. Disabled/deleted accounts and missing tenant relationships reject access.
CAS continues to use its existing dedicated session table and `sid` revocation.

## New persistence

- `nexent.user_account_t` stores stable user IDs, normalized email, password hash
  and scheme, password-login eligibility, account status, email confirmation,
  credential revision and bounded historical provider metadata.

Application transactions serialize email/ID creation with advisory locks. New
passwords use salted scrypt; compatible historical bcrypt hashes are verified in
their original format. Password changes write scrypt. Password hashes and source
metadata are never returned by identity APIs.

## Upgrade sequence

1. Back up both the original Supabase database and business PostgreSQL. Retain
   those backups until account, provider-binding and ownership checks finish.
   Freeze registration, password changes and provider binding during cutover.
2. Apply `deploy/sql/migrations/v2.8.1_001_local_user_accounts.sql` using the normal
   migration runner, or apply this additive migration to the target manually.
   Do not alter the historical initialization/merged SQL files.
3. Run the migration on the deployment host with Python 3.11 and the backend
   virtual environment, or install the tool's `requirements.txt`. The tool reads
   `deploy/env/.env` by default; exported variables take precedence. Source defaults
   to host loopback port 5436 and target to host loopback port 5434. Deployment-only
   Docker service names are translated to these host endpoints. Remote endpoints use the existing SUPABASE_POSTGRES_HOST/PORT and POSTGRES_HOST/PORT fields.
4. Run host-side preflight. The source password is read from
   `SUPABASE_POSTGRES_PASSWORD` first. If no source password is configured, an
   interactive terminal prompts with hidden input. Noninteractive execution fails
   with an actionable message. Do not paste credentials into saved commands.

   ```sh
   python deploy/sql/tools/supabase_to_postgres/migrate.py
   ```

   If the old containers were removed, manually restore the old database from
   its existing data directory first:

   ```sh
   python deploy/sql/tools/supabase_to_postgres/legacy_stack.py up
   ```

   Set ROOT_DIR to the original deployment storage root or SUPABASE_DATA_DIR to
   its PostgreSQL directory containing PG_VERSION. Full old GoTrue/Kong startup
   is available explicitly with --with-auth. See the tool README and
   legacy.env.example for the relocated Compose files and environment settings.

   The default local-source flow discovers the existing Supabase DB container.
   When stopped, that container is started and PostgreSQL readiness is awaited.
   The tool never recreates a container, initializes an empty source or changes a
   volume. `--source-container supabase_db` selects an existing container when
   names are ambiguous; `--no-start-source` disables automatic startup. An explicit source host address connects directly; default/service-alias settings retain Docker management.
5. Review source/inserted/skipped counts, disabled orphan counts. Resolve ID/email conflicts and unsupported source rows. Default dry-run
   writes no account rows, although it may start the existing source DB.
6. After preflight succeeds, explicitly apply from the host:

   ```sh
   python deploy/sql/tools/supabase_to_postgres/migrate.py --apply
   ```

   Accounts share one target transaction. A failure rolls back
   the import. Repeating it skips matching identities and preserves newer local
   passwords, credential revisions and account state. Connection overrides and
   password priorities are documented in
   [the tool README](../deploy/sql/tools/supabase_to_postgres/README.md).
7. Keep or securely provision `JWT_SECRET`, and set `JWT_ISSUER` to `nexent` or
   another deployment-specific issuer. Keep `IND_AIDP_IMAGE_SIGNING_KEY` unchanged
   if configured. All API/runtime services must share the intended signing setup.
   The new issuer and required account revision reject legacy Supabase JWTs.
8. Start the backend/frontend together and rerun deployment/bootstrap. A fresh
   installation can create SU directly. An existing SU membership without its
   migrated account blocks bootstrap so a new UUID cannot replace that owner.
9. Verify old-user password login, original user IDs and business ownership,
   password change, API keys, provider binding and CAS single logout. Retire the
   old auth services only after these checks. Normal application processes do not need source database access.
   Remove legacy containers after verification with `legacy_stack.py down`, using
   the same environment file. The teardown retains original bind data and volumes.

The import copies `auth.users`, retains `auth.identities` snapshots within the
account metadata. Source `auth.audit_log_entries` is never read or imported. Original
creation/update and email-confirmation times are retained. Banned/deleted users
remain unavailable. Source identities without an active local tenant membership
are retained as disabled accounts and never receive a default role or tenant.
CAS-created random-password identities are not automatically enabled for password
login. Review exceptional historical CAS accounts that later acquired a known
password before enabling that login method. Source session, refresh-token,
confirmation/recovery secrets and unrelated Supabase system-schema data remain
in the source backup and are not activated in the target.

## Rollback

Before new identity/password writes, restore the target PostgreSQL backup and old
application configuration together against the preserved source database. The old
backend requires role/email columns on the association table, so rolling back only
the application after this SQL upgrade is insufficient. After cutover writes,
reconcile new accounts, profile edits and password changes before restoring a
backup. Neither the importer nor deployment removes the source authentication
volume. SQL replay is an idempotent forward upgrade, not a rollback operation.

## Local verification

`AUTH-LOCAL-D2-001`, `API-005` and `API-006` exercise actual FastAPI user routes,
native password/JWT code and disposable PostgreSQL databases. `AUTH-LOCAL-D5-001`
proves source snapshot import, original passwords/IDs, source audit exclusion, dry-run,
repeat safety, conflicts and rollback after a database insert failure. Configure
`NEXENT_AUTH_TEST_DSN` for an isolated PostgreSQL instance with permission to
create/drop temporary test databases. Provider UT remains separate from full
external CAS/OAuth journeys, which retain their repository policy exclusion.

## Code ownership after the backend refactor

The gateway validates JWTs and credential policies in
`backend/gateway/authentication/auth.py`; API keys use the neighboring
`northbound_auth.py`. Identity HTTP routes live in `backend/management/api/identity/`.
Account tables and persistence live in `backend/management/db/identity/` and
are registered by `backend/management/db/models/__init__.py`. Environment reads
remain centralized in `backend/contracts/constants/environment.py`.

## Post-migration acceptance checklist

| Area | Required verification |
| --- | --- |
| Historical password login | Existing email/original password works; wrong password, unconfirmed, disabled and deleted accounts fail. Include bcrypt and non-ASCII/long passwords supported by the source. |
| Registration | Invitation validation, duplicate email and role/group assignment work; no account remains after transactional creation failure. |
| Password change | Old password fails after change, new password works, previously issued JWTs fail. |
| JWT and browser cookies | Login sets HttpOnly credentials, expiry requires login, legacy refresh is rejected, stale refresh cookies are removed and logout clears cookies. A copied ordinary JWT remains valid until expiry unless credentials/status change. |
| Existing ownership | Original UUID, tenant, role, group membership, conversations, agents, knowledge and API-key ownership match the pre-cutover records. |
| OAuth | Existing bindings keep the same user ID; first registration, missing-email completion, explicit account linking and unlinking work; disabled users cannot sign in or mutate bindings. |
| CAS | Existing bindings and first provisioning retain identity; renewal and single logout work with existing sid revocation; CAS-only accounts remain password-login disabled. |
| Account deletion and API keys | Deletion/disable denies JWT and API-key access; cleanup and role boundaries remain effective. |
| Super administrator | Fresh bootstrap creates one SU; rerun preserves UUID/password; an unmigrated historical SU blocks replacement. |
| Migration and deployment | Dry-run writes nothing, apply preserves hashes/times, repeat keeps newer credentials, conflicts roll back; all backend services share JWT settings and start without Supabase. |

Run live OAuth and CAS journeys against the actual providers before production
cutover. Local service/API tests do not establish external-provider acceptance.

## Account profile ownership and repeat-safe SQL upgrade

`user_account_t.user_email` is the single persisted login email and `user_role`
is stored on the same account. `user_tenant_t` keeps only user/tenant association
and standard record/audit fields. Existing HTTP payloads keep their `email` keys;
association query results project role/email from the account for compatibility.

All schema upgrade steps are integrated into
`deploy/sql/migrations/v2.8.1_001_local_user_accounts.sql` as one atomic DO block.
It upgrades an older account `email` column, adds missing profile columns, checks
conflicting IDs/emails/roles, transfers old association metadata, and only then
drops the old association role/email columns. Original active association values
are preferred; deleted-only identities stay deleted. Ambiguous old identities
cause rollback instead of arbitrary role selection.

If a legacy association has no account, the SQL creates a disabled account with
the original UUID, role/email and a credential-pending marker. The host importer
then fills its original credentials. Its `updated` counter reports these hydrated
accounts; `inserted` counts genuinely new records, and `skipped` counts accounts
already migrated. A placeholder is never allowed to sign in before credential
migration. Provider metadata never supplies a role.

The SQL can be rerun: existing passwords, credential versions, completed profile
edits and deletion state are retained. The importer also never overwrites a live
password. Keep the original data/backup until both SQL and account import finish.
Deleting account rows after the old columns have been removed also deletes that
identity's canonical role/email; SQL replay cannot recover intentionally removed
metadata from an association-only table.

## Initial administrator credential output

Docker and Kubernetes deployment print the initial administrator email/password
only after the backend confirms a newly created account. Explicitly hidden or
manual-password flows do not print it. Existing accounts, creation errors and a
concurrent creator returning exists=true never disclose the supplied password.
Rerunning deployment preserves the existing password and cannot recover plaintext
from its hash. Backend bootstrap JSON and stdin password transport are unchanged.

## Checking Helm configuration after the migration

`secrets.jwtSecret is required for local authentication` means Helm ran and the
application values omitted the signing key. The pytest-based Bash/Helm rendering
suite was removed at user request. Manual template checks still require an
explicit signing key.

For a manual template check, provide synthetic values explicitly:

```bash
helm template env-test deploy/k8s/helm/nexent \
  --set-string nexent-common.secrets.jwtSecret=synthetic-template-test-only-signing-key
```

Production deployment must use its own signing key. `deploy/k8s/deploy.sh` generates
or reuses it and writes private Helm values. Direct Helm deployment must supply
`nexent-common.secrets.jwtSecret` in its private values file; setting the shell
variable `JWT_SECRET` alone does not populate Helm values. Keep that private file
out of Git and retain the key across upgrades to preserve existing local JWTs.
