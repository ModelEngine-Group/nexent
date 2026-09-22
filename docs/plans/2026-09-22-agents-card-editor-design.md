# Agents Card Editor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn `/agents` into an independent card-based Agent chooser with a centered details modal and keep the existing editor reachable by `agent_id`.

**Architecture:** Keep `page.tsx` as the route entry and card-list coordinator. Move the current editor orchestration to `agents.tsx`, remove its selector header, and compose it from `page.tsx` only when an `agent_id` query parameter is present. Add an agents-owned detail modal that owns the selected-card action surface.

**Tech Stack:** Next.js App Router, React, TypeScript, Ant Design, TanStack React Query, existing shared `ResourceCardGrid` and `ResourceCard`.

---

### Task 1: Establish the card-list route contract

**Files:**
- Modify: `frontend/app/[locale]/agents/page.tsx`
- Create: `frontend/app/[locale]/agents/agent-detail.tsx`
- Test: `frontend` type check

**Step 1: Write the failing test**

Use the TypeScript compiler to establish that the current route has no card-list implementation or detail-modal interface.

**Step 2: Run test to verify it fails**

Run: `npm run type-check`

Expected: the new imports/types are absent before the implementation.

**Step 3: Write minimal implementation**

Render independent Agent cards with shared resource-card primitives. A card click selects an Agent and opens the centered `agent-detail.tsx` modal; its edit action sets `agent_id` in the route URL. Keep copy, relationship, export, and version-management actions associated with the selected Agent.

**Step 4: Run test to verify it passes**

Run: `npm run type-check`

Expected: PASS.

### Task 2: Extract the existing editor and remove its selector header

**Files:**
- Create: `frontend/app/[locale]/agents/agents.tsx`
- Modify: `frontend/app/[locale]/agents/page.tsx`
- Modify: `frontend/app/[locale]/agents/agent-selector-header.tsx` or remove its call site
- Test: `frontend` type check and lint

**Step 1: Write the failing test**

Compile the page after changing its editor import target; it must fail until the extracted component exists.

**Step 2: Run test to verify it fails**

Run: `npm run type-check`

Expected: missing `agents.tsx` module or export.

**Step 3: Write minimal implementation**

Move the current editor orchestration into `agents.tsx`; remove `AgentSelectorHeader` and its selector-bound callbacks. Preserve configuration, generation, debugging, version panels, loading state, and autosave behavior for the Agent identified by `agent_id`.

**Step 4: Run test to verify it passes**

Run: `npm run type-check && npm run lint`

Expected: PASS.

### Task 3: Verify the delivered route behavior

**Files:**
- Verify: `frontend/app/[locale]/agents/page.tsx`
- Verify: `frontend/app/[locale]/agents/agents.tsx`
- Verify: `frontend/app/[locale]/agents/agent-detail.tsx`

**Step 1: Run focused verification**

Run: `npm run type-check && npm run lint`

Expected: PASS.

**Step 2: Review scope**

Confirm that only the `/agents` feature and its directly needed localization/shared types were changed, cards open a centered details modal, and edit navigation uses only `agent_id`.

**Step 3: Commit**

Commit one implementation delivery using the repository's required trailer format.
