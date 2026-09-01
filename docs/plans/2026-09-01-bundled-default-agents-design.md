# Bundled Default Agents Design

## 1. Goal

Make official agents available in Nexent's Agent Repository immediately after platform installation, without adding an "Install Official Agents" action to the resource-management page. Official agents are platform-level, read-only repository templates. A tenant copies an official agent into My Agents, after which the copy has the same edit, version, publish, and repository-submission permissions as any other tenant-owned agent.

## 2. Resource delivery

Official agent content is maintained outside the Nexent source repository. The release pipeline combines a selected industry profile from the external official-agent repository with the Nexent installer package:

```text
nexent-installer-medical/
├── deploy/
├── images/
└── official-agents/
    └── medical/
        ├── medical-researcher.zip
        └── clinical-assistant.zip
```

Deployment config selects the profile and runtime path:

```env
OFFICIAL_AGENT_PROFILE=medical
OFFICIAL_AGENTS_PATH=/mnt/nexent/official-agents/medical
```

Docker copies/mounts the selected package read-only. Kubernetes uses an external volume or equivalent package mount. Profiles such as `general`, `medical`, and `finance` use the same Nexent code and load only their configured resources.

## 3. Persistence model

Reuse the existing `AgentInfo` and `AgentRepository` tables; add no schema fields or new tables. Reserve a tenant identifier for platform templates:

```python
OFFICIAL_AGENT_TENANT_ID = "__nexent_official__"
OFFICIAL_AGENT_USER_ID = "__nexent_system__"
```

Official source agents and repository listings use the reserved tenant. Existing `agent_id` remains the source agent identity, and the existing repository upsert behavior is reused. The synchronization process must locate and reuse the existing source agent before updating its repository snapshot, so repeated starts do not create duplicates or replace tenant copies.

No additional database uniqueness constraint is required. The repository's existing `agent_id` plus publisher-tenant lookup is the idempotency key, provided the official source agent ID is kept stable.

## 4. Startup synchronization

After database connectivity and migrations are ready, the backend runs a non-blocking official-agent synchronization task:

```text
read OFFICIAL_AGENTS_PATH
  → enumerate selected profile bundles
  → validate and safely unpack each ZIP
  → load agent snapshot, skills, and knowledge-base seed files
  → find or create the source agent under the reserved tenant
  → upsert the official repository snapshot
```

The task is isolated per bundle. Invalid or missing packages are logged and skipped without preventing Nexent from starting. Unchanged bundles are skipped; changed versions update only the official repository snapshot. Existing tenant copies are never overwritten.

ZIP extraction must use a temporary directory and reject path traversal. Required files and snapshot structure are validated before persistence.

## 5. Repository visibility and permissions

Repository listing queries return both:

```text
publisher_tenant_id = current tenant
OR publisher_tenant_id = OFFICIAL_AGENT_TENANT_ID
```

Official entries are visible to all tenants and have a read-only template presentation. Users can view details and copy them. Edit, review, unshare, and delete operations against the reserved tenant are rejected. Download/copy counters may still be incremented.

Copying reads the official `agent_info_json` snapshot but imports into the current user's tenant through the existing repository import flow. Skills, MCPs, and knowledge-base references follow the existing import behavior. The resulting agent is a normal tenant-owned agent and may be edited, versioned, submitted for review, shared, or updated in the repository.

The frontend reuses the existing Agent Repository page and copy flow. It adds an official badge and hides management actions for official entries; it does not add a dedicated official-agent installation modal.

## 6. Error and upgrade behavior

- No profile or path: follow the configured default policy (`general` or disabled).
- Missing profile directory: log a clear warning/error and keep the main service available.
- One invalid bundle: skip only that bundle.
- Synchronization failure: roll back the current bundle and continue with others.
- Repeated startup: reuse the stable source agent and update the existing repository record.
- External bundle version change: update the official template only.
- Tenant copy failure: do not mutate the official template or other tenants.
- Tenant edits and republishes: use the normal tenant repository review flow.

## 7. Verification

Backend tests cover profile resolution, ZIP validation, reserved-tenant initialization, first sync, repeated sync, version refresh, per-bundle failure isolation, cross-tenant visibility, read/copy permission, management-operation rejection, tenant ownership after copy, and ordinary republish behavior.

Deployment tests cover offline package composition, Docker read-only mount, Kubernetes resource injection, default/missing profiles, and profile isolation. Frontend tests verify official badges/actions and that copied agents appear in My Agents.

Acceptance requires a medical package deployment to expose medical agents in Agent Repository immediately after startup, allow tenants to copy and fully edit/republish them, avoid duplicate official entries after restart, and prevent a general profile from loading medical resources.

## 8. Scope boundaries

This change does not add a new official-agent API, database table, database column, or resource-management installation wizard. It also does not add source-lineage metadata to copied tenant agents.
