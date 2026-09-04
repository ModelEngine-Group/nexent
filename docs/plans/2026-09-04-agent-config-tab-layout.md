# Agent Configuration Tab Layout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Tools & Skills tab, remove Security Settings, and place the guardrail section under Advanced Settings.

**Architecture:** `agent-config.tsx` owns tab values, section placement, and NL2Agent focus routing. The locale files supply tab labels, so the new tab value must be represented in the component type and both supported locale files.

**Tech Stack:** Next.js, React, TypeScript, react-i18next, Radix Tabs.

---

### Task 1: Define the new tab label

**Files:**
- Modify: `frontend/public/locales/zh/common.json`
- Modify: `frontend/public/locales/en/common.json`

**Step 1: Add a failing automated test**

No frontend unit-test runner is configured in `frontend/package.json`; request explicit permission to use static validation instead of an automated RED-GREEN test.

**Step 2: Add the translations**

Add `agent.config.tab.toolsSkills` with `工具与技能` in Chinese and `Tools & Skills` in English, adjacent to the existing agent configuration tab labels.

**Step 3: Run static validation**

Run: `npm run type-check`

Expected: exit code 0.

### Task 2: Reorganize tab values, focus routing, and sections

**Files:**
- Modify: `frontend/app/[locale]/agents/agent-config.tsx`

**Step 1: Add a failing automated test**

No component test infrastructure is configured. With user approval, use a focused source review plus TypeScript validation in place of a RED-GREEN test.

**Step 2: Implement the minimal layout change**

- Replace the `security` tab value with `tools_skills`.
- Route `tools_skills` to its dedicated tab and `guardrail` to Advanced Settings.
- Render Tabs in the exact order Basic, Tools & Skills, Advanced.
- Render `AgentCapability` only in the Tools & Skills tab.
- Append the existing guardrail section, including its actions and ref, to Advanced Settings.

**Step 3: Verify the implementation**

Run: `npm run type-check`

Expected: exit code 0.

Run: `npm run format:check`

Expected: exit code 0 for the changed files.

### Task 3: Review and commit

**Files:**
- Verify: `frontend/app/[locale]/agents/agent-config.tsx`
- Verify: `frontend/public/locales/zh/common.json`
- Verify: `frontend/public/locales/en/common.json`

**Step 1: Review the diff**

Confirm no `security` tab trigger, tab value, or focus target remains; confirm the guardrail section still includes `GuardrailConfigActions` and `guardrailSectionRef`.

**Step 2: Run final verification**

Run: `npm run type-check && npm run format:check`

Expected: exit code 0.

**Step 3: Commit**

Commit the implementation as one AI coding delivery with the required trailers.
