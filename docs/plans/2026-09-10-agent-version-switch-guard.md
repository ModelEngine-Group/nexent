# Agent Version Switch Guard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent a stale, unpublished Agent from issuing a version-detail request while the user switches to another Agent.

**Architecture:** The Agents page already knows both the requested URL Agent and the loaded store Agent, and it fetches the version list for the latter. Reuse those values to enable the version-detail query only when no switch is in progress and the list confirms at least one published version.

**Tech Stack:** Next.js, React, TanStack Query, Node.js built-in test runner.

---

### Task 1: Guard version-detail loading during a switch and for unpublished Agents

**Files:**
- Create: `frontend/tests/agentVersionSwitchGuard.test.ts`
- Modify: `frontend/app/[locale]/agents/page.tsx:130-158`

**Step 1: Write the failing test**

Add a source-level regression test that requires the page to calculate an explicit boolean guard from `isRequestedAgentLoading` and `total > 0`, and pass it as the third argument to `useAgentVersionDetail`.

**Step 2: Run test to verify it fails**

Run: `npx tsx --test tests/agentVersionSwitchGuard.test.ts`

Expected: FAIL because the hook currently receives only two arguments.

**Step 3: Write minimal implementation**

Compute `shouldFetchVersionDetail` after `isRequestedAgentLoading` is derived, then pass it as the hook's `enabled` argument. Keep existing query keys and backend API unchanged.

**Step 4: Run test to verify it passes**

Run: `npx tsx --test tests/agentVersionSwitchGuard.test.ts`

Expected: PASS.

**Step 5: Run type verification**

Run: `npm run type-check`

Expected: exit code 0.

**Step 6: Commit**

Commit the plan, regression test, and page change together. Do not stage the pre-existing deletion of `frontend/tests/collaborativeAgentVersionLabel.test.ts`.
