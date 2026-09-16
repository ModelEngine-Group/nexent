# Database design, access, and migrations

Use for relational schema design, `backend/database/**/*.py`, related service-level integrity checks, and schema work under `deploy/sql/`.

## Design workflow

1. Identify business entities and relationships before deciding tables and fields. An E-R diagram is optional; describe relationships clearly in the design even when no diagram is produced.
2. Gather query scenarios, including filters, joins, sorting, pagination, updates, and version/history needs. Use these to choose columns, JSONB, tables, and indexes together.
3. Specify field names, business definitions, types/lengths, nullability/defaults, audit behavior, references, and application-enforced integrity. Record JSONB boundaries and index rationale alongside DDL.
4. Compare with existing models, callers, and migrations. Apply new design requirements to new schema; explicitly resolve legacy compatibility before implementing a schema change.

## Table and field naming

- Use lowercase snake_case. Business tables follow `<module>_<business_noun_phrase>_t`; backend-only log tables follow `<module>_<business_noun_phrase>_log`; archive tables follow `<table_name>_<archive_date>_bak` when archiving is needed.
- Use one to three meaningful nouns or a noun phrase. Prefer module-consistent abbreviations; avoid a lone ambiguous verb. For example, `conversation_share_record_t` identifies a sharing record more clearly than `conversation_share_t`.
- Name fields for business meaning and specific usage. Include units for measured values, such as `latency_ms` or `amount_usd`. Keep reference-field names consistent with the identifiers they reference.
- Qualify broad names such as `data`, `info`, or `metadata`; use names such as `provider_metadata` with a defined purpose.
- Every field needs an English database column comment describing its business meaning and applicable scenario. For example, a credential used only for speech-model authentication must state that limitation.
- Carry comments into generated DDL/database metadata. Inspect whether the ORM declaration emits a database comment; Python-only documentation is not sufficient evidence that the column is commented.

## Field types and boundaries

Treat length/type choices as part of the specification and align input validation with them.

| Meaning | Recommended default | Design requirement |
| --- | --- | --- |
| Name/title | `VARCHAR(100)` | Adjust to an explicit business limit |
| Enum/status code | `VARCHAR(30)` | Keep the vocabulary and length consistent |
| General integer | `INT4` | Confirm the required range |
| Primary/reference identifier | `INT4` | Match the referenced identifier's type; document capacity or legacy exceptions |
| Dictionary/variable structured value | `JSONB` | Define purpose, accepted keys/structure, value types, and validation boundaries |

- Avoid unbounded `TEXT`/`VARCHAR` for values with meaningful business limits. Use them for bodies, error stacks, or raw text when no stable upper bound exists.
- Do not copy an illustrative limit such as 1,000 characters for every message body. Derive limits from the actual contract and verify boundary/rejection behavior.

## Columns, JSONB, or tables

| Situation | Preferred representation |
| --- | --- |
| Attribute meaningful for all rows, queried/sorted/aggregated, or frequently updated | Explicit column |
| Row-specific supplemental data, variable structures, or a value primarily read as a whole | Purpose-specific JSONB, such as a snapshot or raw provider output |
| New business entity/relationship with many attributes | Separate table |
| Small entity/relationship wholly subordinate to another entity | A few columns or bounded JSONB, chosen from the access patterns |

Document JSONB ownership and validation, including allowed/required keys or an explicitly opaque provider payload, null/default semantics, and applicable size limits. Do not hide stable queryable business attributes in an unrestricted metadata bag.

## Audit fields

The new design standard requires all five audit fields on every new table, including log/archive designs. Existing exceptions must be identified rather than copied silently.

| Field | Type | Meaning |
| --- | --- | --- |
| `created_by` | `VARCHAR(100)` | Creating user or system actor |
| `create_time` | `TIMESTAMP` | Creation time |
| `updated_by` | `VARCHAR(100)` | Last updating user or system actor |
| `update_time` | `TIMESTAMP` | Last update time |
| `delete_flag` | `VARCHAR(1)` | Soft-delete marker, default `N` |

- Inherit the five audit fields from `backend/database/db_models.py::TableBase`, which uses the names and types above. Do not redeclare inherited audit columns.
- Define how all write paths maintain timestamps, including raw SQL and SQLAlchemy Core operations; do not assume an ORM `onupdate` setting proves database-wide behavior.

## Keys, references, and business uniqueness

- Every business table has a single technical primary key. If business identity is composite, add a separate record identifier instead of making that business combination the primary key.
- For versioned resources, distinguish stable entity identity from a version-specific row ID. The supplied example uses `agent_no` across versions and `agent_id` for a concrete version; this is a design example, not authorization to rename existing columns.
- New business-table designs do not declare database foreign-key constraints or non-primary unique constraints. Do not circumvent this policy with a unique index. Primary-key uniqueness and appropriate structural constraints such as `NOT NULL` remain allowed.
- Keep logical reference names consistent and implement relationship checks and business uniqueness in the service layer. Document these contracts in field comments and identify the responsible service/write paths.
- Specify the uniqueness scope, including tenant, version, and active/deleted rows where relevant. Verify missing references, duplicates, and concurrent writes. A check followed by an insert alone is not evidence of race-safe uniqueness; define transaction/serialization or another application-level coordination strategy where required.
- Existing foreign keys and unique constraints/indexes are compatibility concerns. Do not remove them during unrelated work. Any removal needs an explicit migration and replacement integrity behavior, including all writers.

## Index design

- Design indexes together with tables using actual filtering, joining, ordering, and pagination scenarios. Describe which query each index supports and why its column order/predicate is appropriate.
- Consider common active-row filtering and query combinations; avoid indexing every field by default. Business indexes remain non-unique under the policy above.
- Include index DDL in the migration and validate representative query plans when an execution environment is available. Report unverified performance assumptions explicitly.

## Models and CRUD

- Define models in `backend/database/db_models.py`, inheriting `TableBase` and reusing its shared audit fields.
- Prefer SQLAlchemy Core `insert`/`update`/`select` with `session.execute()` / `session.scalars()`. ORM `session.add()` remains allowed.
- Creation sets the creating/updating actor and `delete_flag='N'`; populate timestamps through the designed defaults. Updates normally overwrite the row, refresh the updating actor/time, and preserve creation fields.
- Business tables use soft deletion. Set `delete_flag='Y'`, the updating actor/time, and soft-delete dependent rows in the same transaction when required by the relationship contract.
- Normal reads filter `delete_flag='N'`, including relevant joins. Reuse a shared active-row filter when available; do not assume the current data layer already injects it automatically. History/deleted-row access must be explicit.
- If a resource requires retained versions, consider inserting a new version and soft-deleting the previous one in one transaction. Specify stable/version-specific references and which record reads should return; do not impose versioning on every update.

## Transaction ownership and errors

- Use `with get_db_session() as session:` from `backend/database/client.py`, or its supported shared-session form for a caller-owned transaction.
- CRUD functions never call `commit()`, `rollback()`, or `close()`. The session owner handles lifecycle; the current context manager leaves explicitly supplied sessions to their caller.
- Let exceptions propagate from CRUD modules. Central session management rolls back, logs, re-raises, and closes sessions it owns.
- Define a shared database exception in `backend/consts/exceptions.py` if needed and verify its raising boundary. The current client re-raises original exceptions; it does not automatically create `DatabaseOperationError`.

## SQL

- Every file named `init.sql` or with `merged_migrations` in its name is already merged into the target branch, which is immutable. Never modify, rename, or delete one.
- Add a versioned migration under `deploy/sql/migrations/`, following current naming/version conventions. Application version is `APP_VERSION` in `backend/consts/const.py`.
- Verify naming/comments, type limits, JSONB validation, audit maintenance, reference/uniqueness behavior, soft deletion/versioning, query indexes, transaction ownership, and migration compatibility as applicable. External database execution requires authorization for that action.
