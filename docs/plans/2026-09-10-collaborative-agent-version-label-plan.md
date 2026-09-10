# Collaborative Agent Version Label Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Display a related internal agent's user-provided version name beside
its name on the agent configuration page.

**Architecture:** `CollaborativeAgent` already resolves `version_name` from the
saved relation or published-agent record. Extend the presentational list-item
shape to carry that optional value, then render it as a muted, smaller inline
label. The value is rendered verbatim after a capital `V`.

**Tech Stack:** Next.js, React, TypeScript, Tailwind CSS, Ant Design.

---

### Task 1: Render the internal-agent version-name label

**Files:**
- Modify: `frontend/app/[locale]/agents/components/collaborative-agent.tsx:17-22,68-69,389-392`
- Test: no component-test harness is configured for this component; validate with the frontend compiler and formatter.

**Step 1: Update the list-item data shape**

Add an optional `versionName?: string` field to `CollaborativeAgentListItem`.

**Step 2: Render the label**

After the agent-name span, conditionally render a non-shrinking muted
`text-xs` span containing `V{agent.versionName}`. Do not normalize or validate
the version name.

**Step 3: Pass the resolved version name**

When mapping `relatedInternalAgents` into `CollaborativeAgentList` items, pass
`agent.version_name` as `versionName`. Do not add this property to the external
agent list.

**Step 4: Run targeted validation**

Run:

```powershell
npm run type-check
npx prettier --check 'app/[locale]/agents/components/collaborative-agent.tsx'
```

Expected: both commands exit with status `0`.

**Step 5: Commit**

Commit the implementation and its design/plan records as one delivery commit,
using the workspace-required conventional commit trailers.
