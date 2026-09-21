# Skill Repository Card Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Skill repository and My Skills cards use the shared resource grid/card behavior requested by the product design.

**Architecture:** Keep search and server-side data ownership in the page components. Pass page state to `ResourceCardGrid` with local slicing disabled, and adapt domain-specific controls through `ResourceCard` slots.

**Tech Stack:** Next.js, React, TypeScript, Ant Design, Tailwind CSS, Node `node:test` layout checks.

---

### Task 1: Capture the repository-grid contract in a failing layout test

**Files:**
- Modify: `frontend/tests/skillSpaceLayout.test.ts`
- Modify: `frontend/app/[locale]/skill-space/components/RepositoryView.tsx`

**Step 1:** Add a static layout assertion that requires `ResourceCardGrid` to receive `page`, `total`, `onPageChange`, and `paginateItems={false}`, and that rejects the legacy `PaginationBar` in the repository view.

**Step 2:** Run `node --test frontend/tests/skillSpaceLayout.test.ts`; confirm it fails because the page state is not yet passed to the shared grid.

**Step 3:** Pass the existing server-page state into `ResourceCardGrid`, remove `PaginationBar`, and use the grid's default pagination display.

**Step 4:** Re-run the focused test; confirm it passes.

### Task 2: Adapt the repository card controls and click behavior

**Files:**
- Modify: `frontend/tests/skillSpaceLayout.test.ts`
- Modify: `frontend/app/[locale]/skill-space/components/RepositoryView.tsx`
- Modify: `frontend/app/[locale]/skill-space/components/SkillRepositoryCard.tsx`

**Step 1:** Add failing assertions for an `onClick` detail surface, a small text Copy footer, no Detail button, download metadata next to More, and a tag slot that is rendered even when there are no tags.

**Step 2:** Run the focused test and confirm the failure reflects missing behavior.

**Step 3:** Add the minimal `ResourceCard` slot mapping and event isolation needed for the specified controls.

**Step 4:** Re-run the focused test; confirm it passes.

### Task 3: Simplify My Skills card status and footer controls

**Files:**
- Modify: `frontend/tests/skillSpaceLayout.test.ts`
- Modify: `frontend/app/[locale]/skill-space/components/MineSkillsView.tsx`

**Step 1:** Add failing assertions that forbid Hub and source/custom display, place listing status under More, omit the listing-status footer button, and retain lower-right Edit or View.

**Step 2:** Run the focused test and confirm the failure reflects the legacy card layout.

**Step 3:** Make the smallest card-slot and menu changes that satisfy the requested layout without changing listing operations.

**Step 4:** Re-run the focused test; confirm it passes.

### Task 4: Verify and deliver

**Files:**
- Verify only the files above.

**Step 1:** Run `node --test frontend/tests/skillSpaceLayout.test.ts` and the relevant frontend type/lint command.

**Step 2:** Inspect the diff to confirm the scope excludes APIs, translations, and unrelated resource pages.

**Step 3:** Commit only this change with the required repository commit trailers, then hand it to the user for self-test before any PR action.
