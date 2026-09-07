# NL2Agent MCP Gap Content Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use `test-driven-development` to implement this plan task-by-task.

**Goal:** Return an NL2A resource-gap payload as MCP text content without violating FastMCP's structured-content contract.

**Architecture:** `search_uninstalled_resources` currently returns dictionaries on ordinary discovery paths but an NL2A wrapper string for the resource-gap path. FastMCP derives an object output schema from the function annotation and rejects that string as structured content. The resource-gap branch will return an explicit FastMCP `ToolResult` containing the existing serialized wrapper as text, so the client-visible NL2A payload is preserved while `structured_content` remains absent.

**Tech Stack:** Python 3.11, FastMCP, pytest, pytest-asyncio.

---

### Task 1: Reproduce the registered-tool resource-gap response

**Files:**

- Modify: `test/backend/services/test_mcp_internal_tool_search.py`
- Test: `test/backend/services/test_mcp_internal_tool_search.py`

**Step 1: Write the failing test**

Mock the uninstalled and installed search implementations so both return no candidates and the requirement remains uncovered. Invoke the registered `search_uninstalled_resources` FastMCP tool, then assert the result contains the existing `<nl2a>` resource-gap payload as text and has no structured content.

**Step 2: Run test to verify it fails**

Run: `backend/.venv/Scripts/python.exe -m pytest test/backend/services/test_mcp_internal_tool_search.py -k registered_resource_gap -v`

Expected: FAIL with FastMCP's `structured_content must be a dict or None` error.

### Task 2: Preserve the NL2A payload as explicit text content

**Files:**

- Modify: `backend/tool_collection/mcp/nl2agent_mcp_tools.py`
- Test: `test/backend/services/test_mcp_internal_tool_search.py`

**Step 1: Write minimal implementation**

Import FastMCP's `ToolResult` and return it only from the resource-gap branch, with the existing wrapper string passed as content. Do not modify search ranking, coverage calculation, or payload serialization.

**Step 2: Run targeted regression test**

Run: `backend/.venv/Scripts/python.exe -m pytest test/backend/services/test_mcp_internal_tool_search.py -k registered_resource_gap -v`

Expected: PASS.

### Task 3: Verify the affected resource-tool suite

**Files:**

- Verify: `test/backend/services/test_mcp_internal_tool_search.py`

**Step 1: Run the complete affected module**

Run: `backend/.venv/Scripts/python.exe -m pytest test/backend/services/test_mcp_internal_tool_search.py -v`

Expected: PASS with no FastMCP structured-content error.

**Step 2: Commit the delivery**

Commit the test, implementation, and this plan in one Light-mode delivery commit using the repository's required trailers.
