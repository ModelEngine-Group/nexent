# AIDP Integration

Nexent integrates with the AIDP enterprise knowledge retrieval platform, offering vector, full-text, and graph retrieval channels plus their combinations. AIDP has two integration modes:

- **Platform-managed mode**: enabled via the deployment switch `ENABLE_AIDP_KNOWLEDGE`; the Knowledge Base Configuration page is fully replaced by AIDP knowledge base management, and the retrieval tool is injected automatically — transparent to end users
- **Standalone mode**: for independently deployed AIDP services; configure the connection manually through the `ind_aidp_search` tool without affecting other platform knowledge base features

## 1. Platform-managed mode

### 1.1 Prerequisites

Managed mode is configured on the deployment side; there is no UI entry:

| Environment variable | Description |
| -------------------- | ----------- |
| `ENABLE_AIDP_KNOWLEDGE` | Set to `true` to enable AIDP knowledge bases (disabled by default) |
| `AIDP_SERVER_URL` | AIDP service address |
| `AIDP_API_KEY` | AIDP API key (held by the backend; the frontend never touches it) |
| `AIDP_TENANT_ID` | AIDP tenant ID, `aidp` by default |

### 1.2 What changes when enabled

- **Knowledge Base Configuration page**: fully replaced by AIDP knowledge base management (the sidebar menu name stays unchanged)
- **Resource Management page**: the tenant "Knowledge Base" tab is hidden; knowledge bases are managed uniformly on the Knowledge Base Configuration page
- **Agent Chat**: the conversation "Current conversation knowledge bases" switches to the AIDP knowledge base tab, with a maximum of 10 knowledge bases per selection
- **Agent Evaluation**: the "Associated knowledge base" dropdown of AI-generated evaluation sets switches to AIDP knowledge bases

### 1.3 Knowledge base management

**Knowledge base list**: supports name search (server-side filtering), table/card views, column settings with resizable columns; each row shows the permission scope (private / group read-only / group editable), creator, and creation time, with "Import files" and "Delete" actions; deletion previews affected agents first.

**Creating a knowledge base**: the form has six sections — basic info, document chunking, vector generation, retrieval matching, knowledge graph, and permissions & user groups — pre-filled with recommended defaults (512-token chunks, 10% overlap, TopK 10, etc.):

- Document chunking: smart chunking / legal article modes, with maximum tokens per chunk and overlap percentage
- Vector generation: choose an embedding model (creation is blocked when none is available)
- Retrieval matching: similarity threshold and retrieval TopK
- Knowledge graph: optional; supports domain selection (general/finance/medical/legal), sub-graph expansion hops, composition model, and prompt language; **once the graph is disabled it cannot be re-enabled**
- Permissions & user groups: knowledge bases created by Users are always private; other roles can choose private / group read-only / group editable and pick authorized user groups

**File management**: the knowledge base detail page provides "Uploaded files / Upload tasks / Details" tabs:

- Supports text, web page, document, spreadsheet, and image formats; up to 50 files per upload, text and spreadsheet files up to 20 MB, other types up to 1024 MB
- File statuses include ingested, deleting, and deletion failed; batch deletion allows up to 10 files per request
- Upload tasks are retained for 30 days with failure reasons and retry support
- The details page allows editing chunking, retrieval, and graph settings (disabling the graph is permanent), plus name, description, and permissions

### 1.4 Permissions

- **Creator**: has every permission on their own knowledge base
- **Private knowledge bases**: visible to the creator only (including admin roles)
- **Users**: can only see knowledge bases they created
- **Developers**: can see shared knowledge bases of their authorized user groups, with read-only or editable access per group settings
- **Admin roles** (Super Admin, Admin, Asset Owner): can view and edit all shared knowledge bases
- Uploading, deleting files, changing settings, and deleting the knowledge base all require edit permission

### 1.5 Using AIDP in agents and conversations

- In managed mode, the knowledge retrieval tool `aidp_search` is injected automatically into managed agents; it **does not appear in the tool pool** and requires no manual connection setup
- The retrieval scope is constrained twice: the agent's configured knowledge bases ∩ the current user's accessible knowledge bases; knowledge bases specified in the conversation scope are subject to the same permission check
- Runtime parameters: the LLM only provides **query** (the search term) and an optional **kds_list** (temporarily scoped knowledge bases, up to 10)

## 2. Standalone mode (ind_aidp)

Standalone mode connects directly to an independently deployed AIDP service without affecting local knowledge base features. The tool holds its own connection settings and does not participate in the managed permission system or the conversation knowledge scope.

### 2.1 Configuration steps

1. Open the Agent Configuration page and select the target agent
2. Add **ind_aidp_search** (local tool) to the agent in tool management
3. Select **Configure** on the tool row and fill in the parameters:

| Parameter | Description |
| --------- | ----------- |
| **server_url** | AIDP service address (must be an http/https URL without embedded credentials) |
| **api_key** | AIDP API key (shown as a password field) |
| **tenant_id** | AIDP tenant ID, `aidp` by default |
| **kds_list** | Select from the synced list of knowledge bases (up to 10) |

4. To adjust retrieval behavior, expand the **Retrieval settings** section (see below); it shows "Default configuration" initially and "Customized" after changes, with a "Reset to default" button
5. Select **Save Configuration**

### 2.2 Retrieval settings

| Group | Parameters |
| ----- | ---------- |
| **Search method** | Vector / full-text / graph search, combinable (all three enabled by default) |
| **Result control** | Result limit top_k (10 by default, 1–100); score threshold (0–1) |
| **Reranking** | reranking_enable (enabled by default); strategy: performance-first (default) / high-accuracy / jargon-coverage |
| **Retrieval details** | Vector and full-text candidates (1–500); per-channel score thresholds (0–1); per-channel result limits (0–100, not exceeding top_k); graph reranking |
| **Enhanced retrieval** | Query rewrite, query expansion, related-chunk retrieval (disabled by default); multimodal retrieval (enabled by default, may return image and table blocks) |

The knowledge base selector paginates server-side (10 per page), supports searching the current page by name, ID, or description, and allows up to 10 selections; select **Sync** to refetch the list.

### 2.3 Differences from the managed mode

| Aspect | Platform-managed | Standalone |
| ------ | ---------------- | ---------- |
| Enablement | Deployment switch, applies to everyone | Per-agent tool addition |
| Connection settings | Environment variables (backend-held) | Filled in the tool configuration |
| Permission control | Remote catalog ∩ user permissions, auto-shrinking | Not subject to platform permissions; searches the configured knowledge bases |
| Tool visibility | System-injected, not manually selectable | Added manually from the agent tool pool |
| Multimodal results | Images embedded as safe markers in answers | Images proxied through Nexent (keys never reach the browser) |

## 3. Runtime parameters

Both modes share the same runtime parameters:

- **query**: the search query
- **kds_list** (optional): knowledge base IDs for this call; defaults to the tool-configured knowledge bases, up to 10
