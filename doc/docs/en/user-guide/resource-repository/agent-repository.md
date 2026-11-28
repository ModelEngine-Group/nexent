# Agent Space

The Agent Space is the hub for sharing, managing, and reviewing agents within the same tenant. Browse listed agents and copy them into your workspace, manage agents you can edit, and—if you are an admin—review listing applications.

## 👥 UI Differences Between Admins and Developers

After you open **Agent Repository**, the top tabs differ by role:

| Role | Visible tabs | Extra capabilities |
|------|--------------|-------------------|
| **Developer** | Repository, My Agents | Browse the shared repository, copy agents, manage your agents, and apply for listing |
| **Admin** | Repository, My Agents, Review Center | Everything developers can do, plus review listing applications and take agents down directly from the repository |

> Note: The Review Center tab is visible to admins only (including multi-role users who hold the Admin role). Developers track their own applications via **View review progress** in **My Agents**.

**Developer view** (Repository / My Agents):

<div style="display: flex; justify-content: left;">
  <img src="../assets/resource-repository/developer-tabs.png" style="width: 80%; height: auto;" alt="Developer tabs" />
</div>

**Admin view** (Repository / My Agents / Review Center):

<div style="display: flex; justify-content: left;">
  <img src="../assets/resource-repository/admin-tabs.png" style="width: 80%; height: auto;" alt="Admin tabs" />
</div>

---

## 📦 Repository

The **Repository** tab shows agents that are listed (shared) in the current tenant. Tenant members can browse them, open details, and copy them into **My Agents** before editing.

> Agents shared in the same tenant must be copied as your own agent before you can edit them.

### Browse and Search

- Browse listed agents as cards
- Search by **agent name, description, or tags**, with structured filtering against the tag library
- Toggle the list sorting between **default order / recently updated**
- Each card shows: icon, name, author, description, tags, tool count, version, and install count; platform-provided official agents carry an "Official" badge

<div style="display: flex; justify-content: left;">
  <img src="../assets/resource-repository/repository-list.png" style="width: 80%; height: auto;" alt="Repository list" />
</div>

### View Details

Click **Details** on a card to view the full agent information, including:

- **Basic information**: name, icon, author, version, model, install count, and created time
- **Agent introduction**: description
- **Built-in tools**: enabled tools
- **Agent role**: role settings (Duty Prompt) and related configuration

<div style="display: flex; justify-content: left;">
  <img src="../assets/resource-repository/repository-detail.png" style="width: 80%; height: auto;" alt="Agent details" />
</div>

### Copy an Agent

Click **Copy** on a card. The system runs a dependency precheck and shows a configuration checklist:

1. Review the **copyable percentage**, plus available and pending item counts
2. If there are abnormal items (for example, model not activated, knowledge base not activated, MCP not activated, Skill name conflict, or tool unavailable), follow the prompts to activate or resolve them
3. After fixing issues, refresh to re-run the precheck; you can also continue copying if you accept the risk
4. After a successful copy, the agent appears in **My Agents** for editing and use

Dependency types usually include: **Model**, **Knowledge Base**, **MCP Service**, **Skill**, and **Tool**.

<div style="display: flex; justify-content: left;">
  <img src="../assets/resource-repository/copy-precheck.png" style="width: 80%; height: auto;" alt="Copy configuration checklist" />
</div>

### Admin Take-Down

Admins can choose **Take down** from the more menu at the top-right of a repository card. After take-down, the agent is no longer visible to tenant members and can no longer be copied. Official agents provided by the platform cannot be taken down.

If a developer needs to take down an agent they listed, use the **View review progress** dialog in **My Agents**.

### Official Agents

The repository also shows built-in official agents with an "Official" badge, covering industry scenarios such as education, finance, government, human resources, legal, marketing, and healthcare (e.g., Intelligent Teaching Assistant, Financial Report Generation Assistant, Lung CT Diagnosis Assistant). Official agents are maintained by the platform, require no application, and are ready to use after copying; admins cannot take them down.

---

## 🧑 My Agents

The **My Agents** tab manages agents you can edit, including agents you created and agents copied from the repository.

> 💡 **Entry note**: The "Apply for listing" and "Evaluate" entries have moved to the "..." menu at the top-right of agent cards on the **[Agent Configuration](../agent-configuration)** page — see the "Listing" section there for the application form; this tab handles listing status tracking and review progress management (canceling applications and taking down).

### Filter and Search

- **All / Created by me / Others**: filter by ownership
- Search by agent name or description, with structured filtering against the tag library
- Toggle the list sorting between **default order / recently updated**
- Agents are shown as cards with pagination

### Create an Agent

When the filter is **All** and there is no search query, the page provides a **Create agent** entry that jumps to the Agent Configuration page.

> 💡 To import an existing agent configuration (JSON/ZIP), use the import wizard on the Agent Configuration page; the My Agents page no longer provides an import entry.

<div style="display: flex; justify-content: left;">
  <img src="../assets/resource-repository/mine-list.png" style="width: 80%; height: auto;" alt="My Agents list" />
</div>

### Agent Card Status

Each card shows lifecycle and listing status for quick recognition:

| Badge | Description |
|------|-------------|
| **Draft / Published** | Whether the agent has a published version (only published versions can apply for listing) |
| **Hub** | The agent has repository-related records (previously applied or currently listed) |
| **Under review** | First listing application waiting for admin review |
| **Update under review** | A listed version already exists; a new version is waiting for review |
| **Listed** | Currently shared in the repository |
| **Rejected** | Listing application was rejected; you can revise and re-apply |

### Common Actions

On an agent card, you can:

- **Edit**: open the Agent Configuration page to change configuration (not available with read-only permission)
- **View**: view details of the published version
- **View review progress / View update review progress**: check application status, and cancel the application or take the agent down
- **Delete**: delete the agent

### View Review Progress

Open the review status dialog from an agent card in **My Agents** to see:

- Current status: Under review / Approved / Rejected
- Review version, submitted time, listing note, and review comments (if any)

Depending on the status, you can also:

- **Cancel listing application**: withdraw a pending or rejected application
- **Take down**: remove a listed agent from the repository

Review results (approved / rejected) are pushed to the applicant via **in-app notifications**; selecting the notification opens the review status dialog of the corresponding agent directly.

<div style="display: flex; justify-content: left;">
  <img src="../assets/resource-repository/review-status.png" style="width: 80%; height: auto;" alt="Review progress" />
</div>

---

## ✅ Review Center

**Review Center** is visible to **admins** only. It is used to process listing applications submitted by users in the same tenant.

### Pending Review Queue

Pending applications are shown as a list, including:

- Agent name and icon
- Applied version
- Submitter
- Listing note
- Actions: Details, Approve, Reject

The tab shows a pending-count badge so admins can handle applications promptly.

### Review Actions

1. Click **Details** to preview the agent configuration and confirm capabilities and tools
2. Click **Approve**: optionally add a review comment; after confirmation, the agent is listed in **Repository**
3. Click **Reject**: optionally add a review comment; after rejection, the submitter can revise the agent in **My Agents** and re-apply

<div style="display: flex; justify-content: left;">
  <img src="../assets/resource-repository/review-confirm.png" style="width: 80%; height: auto;" alt="Review confirmation" />
</div>

---

## 🚀 Next Steps

After managing agents in the Agent Repository, you can:

1. Interact with agents in **[Agent Chat](../start-chat)**
2. Continue creating or iterating agents in **[Agent Configuration](../agent-configuration)**
3. Configure **[Memory Configuration](../memory-configuration)** to improve agent memory

If you run into any issues, check the **[FAQ](../../quick-start/faq)** or ask in [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions).
