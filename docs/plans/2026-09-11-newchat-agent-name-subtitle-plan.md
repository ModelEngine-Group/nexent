# Newchat Agent Name Subtitle Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show the selected agent's name beneath a populated new-chat conversation title instead of the fixed conversation label.

**Architecture:** The thread header already derives `displayName` from the selected agent with a `name` fallback. Reuse this value in the populated-conversation subtitle and retain the generated or user-defined conversation title on the first line.

**Tech Stack:** Next.js, React, TypeScript, Node.js built-in test runner.

---

### Task 1: Cover and implement the populated-conversation subtitle

**Files:**
- Modify: `frontend/tests/newchatThreadAgentBinding.test.ts`
- Modify: `frontend/app/[locale]/newchat/assistant-ui/thread.tsx:640-642`

**Step 1: Write the failing test**

Add a source-level regression assertion proving that the populated-conversation subtitle renders the existing `displayName` value rather than the fixed translation key.

**Step 2: Run test to verify it fails**

Run: `node --test frontend/tests/newchatThreadAgentBinding.test.ts`

Expected: FAIL because the header still renders `t("chat.thread.conversation")`.

**Step 3: Write minimal implementation**

Replace only the subtitle expression with `{displayName}`. Do not alter the first-line title, sharing controls, or empty-conversation header.

**Step 4: Run test to verify it passes**

Run: `node --test frontend/tests/newchatThreadAgentBinding.test.ts`

Expected: PASS.

**Step 5: Commit**

Commit the test and header adjustment as one `fix(newchat)` commit with the required AI trailers.
