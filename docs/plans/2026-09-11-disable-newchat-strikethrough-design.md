# Disable Newchat Strikethrough Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Render content written with Markdown strikethrough markers as ordinary text in `/newchat` without removing other GFM Markdown features.

**Architecture:** `/newchat` passes `defaultComponents` to `MarkdownTextPrimitive`. Add a `del` component to that page-specific component map which emits a semantic-neutral `span` with the parsed children. `remark-gfm` stays enabled, so tables, task lists, and other supported GFM constructs are unaffected.

**Tech Stack:** Next.js, React, TypeScript, `@assistant-ui/react-markdown`, `remark-gfm`, Node built-in test runner.

---

### Task 1: Prove the newchat renderer maps strikethrough to plain text

**Files:**
- Create: `frontend/tests/newchatMarkdownRendering.test.ts`
- Modify: none

**Step 1: Write the failing test**

Read `app/[locale]/newchat/ui/markdown-text.tsx` and assert that `defaultComponents` declares a `del` renderer which returns a `span`, and that the existing `remarkGfm` plugin remains present. The test should use `node:test`, `node:assert/strict`, and `readFile`, matching the existing `frontend/tests/newchatThreadAgentBinding.test.ts` style.

**Step 2: Run test to verify it fails**

Run: `node --test tests/newchatMarkdownRendering.test.ts`

Expected: FAIL because `defaultComponents` does not currently define `del`.

### Task 2: Render the parsed delete node as ordinary text

**Files:**
- Modify: `frontend/app/[locale]/newchat/ui/markdown-text.tsx` in `defaultComponents`
- Test: `frontend/tests/newchatMarkdownRendering.test.ts`

**Step 1: Write minimal implementation**

Add a `del` component next to the other inline element renderers. It accepts `className`, `children`, and remaining props, then returns `<span>` containing `children`; do not forward the Markdown `del` styling or retain the `del` HTML element.

**Step 2: Run test to verify it passes**

Run: `node --test tests/newchatMarkdownRendering.test.ts`

Expected: PASS. The test confirms the custom plain-text renderer is active and `remarkGfm` remains enabled.

**Step 3: Check formatting and types for changed code**

Run: `npx prettier --check app/[locale]/newchat/ui/markdown-text.tsx tests/newchatMarkdownRendering.test.ts; npm run type-check`

Expected: both commands exit successfully.

**Step 4: Commit**

Create one commit for the code and test with the workspace-required commit trailers.
