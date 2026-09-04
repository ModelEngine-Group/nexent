# Agent Capability Collapsibles Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the Tools & Skills inner tabs with direct Tools and Skills collapsibles.

**Architecture:** `agent-config.tsx` owns the two top-level collapsibles and their open state. `agent-capability.tsx` supplies reusable tool and skill content while retaining its existing modal state and callbacks.

**Tech Stack:** React, TypeScript, Next.js, Ant Design, Radix Collapsible.

---

### Task 1: Extract independent capability content

**Files:**
- Modify: `frontend/app/[locale]/agents/components/agent-capability.tsx`

**Step 1: Automated test decision**

No component-test runner is configured. The user approved static validation,
so document TypeScript validation and manual interaction testing instead of a
RED-GREEN test.

**Step 2: Split the existing views**

Export a tools content component and a skills content component. Preserve
their current actions, lists, badges, callbacks, and modal state.

### Task 2: Render direct collapsibles

**Files:**
- Modify: `frontend/app/[locale]/agents/agent-config.tsx`

**Step 1: Add section state and refs**

Add separate `tools` and `skills` section keys, defaults, and refs.

**Step 2: Replace the outer capability section**

Render Tools then Skills as direct `ConfigSection` siblings in the Tools &
Skills tab. Route capability focus requests to the matching section.

### Task 3: Validate and commit

**Files:**
- Verify: `frontend/app/[locale]/agents/agent-config.tsx`
- Verify: `frontend/app/[locale]/agents/components/agent-capability.tsx`

**Step 1: Run verification**

Run: `npm run type-check`

Expected: exit code 0.

**Step 2: Review the diff**

Confirm only two direct collapsibles remain in the Tools & Skills tab and no
internal capability tab controls remain.

**Step 3: Commit**

Create one AI coding-delivery commit with required trailers.
