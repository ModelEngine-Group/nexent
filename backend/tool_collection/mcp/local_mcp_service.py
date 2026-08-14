from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from tool_collection.mcp import e2e_test_tools
from tool_collection.mcp.nl2agent_mcp_tools import (
    NL2AGENT_MCP_TOOL_META,
    NL2A_WRAPPER_DESCRIPTION,
    NL2A_WRAPPER_NAME,
    SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION,
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    nl2a_wrapper as _nl2a_wrapper,
    search_installed_mcp_tools as _search_installed_mcp_tools,
)

LOCAL_MCP_TOOL_NAME_OVERRIDES = {
    SEARCH_INSTALLED_MCP_TOOLS_NAME: SEARCH_INSTALLED_MCP_TOOLS_NAME,
    NL2A_WRAPPER_NAME: NL2A_WRAPPER_NAME,
}

E2EText = Annotated[str, Field(description="Text input used by an E2E test fixture.")]
E2EInteger = Annotated[int, Field(description="Integer input used by an E2E test fixture.")]

# Create MCP server
local_mcp_service = FastMCP("local")
local_mcp_service.tool(
    _search_installed_mcp_tools,
    name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
    description=SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION,
    meta=NL2AGENT_MCP_TOOL_META,
)
local_mcp_service.tool(
    _nl2a_wrapper,
    name=NL2A_WRAPPER_NAME,
    description=NL2A_WRAPPER_DESCRIPTION,
    meta=NL2AGENT_MCP_TOOL_META,
)


@local_mcp_service.tool(name="test_tool_name",
                        description="test_tool_description")
async def demo_tool(para_1: str, para_2: int) -> str:
    print("tool is called successfully")
    print(para_1, para_2)
    return "success"


# E2E test tool: deterministic delayed response
@local_mcp_service.tool(
    name="e2e_delay_echo",
    description="E2E-only: return a delayed deterministic response for scheduling tests.",
)
async def e2e_delay_echo(
    name: E2EText,
    nonce: E2EText,
    delay_ms: E2EInteger = 0,
    payload: E2EText = "",
) -> dict:
    """Return an echo after a controlled delay.

    Args:
        name: Logical caller name included in the response.
        nonce: Unique test token included in the response.
        delay_ms: Delay in milliseconds before returning.
        payload: Optional text copied into the response.
    """
    return await e2e_test_tools.delay_echo(name, nonce, delay_ms, payload)


# E2E test tool: upstream dependency validation
@local_mcp_service.tool(
    name="e2e_require_upstream",
    description="E2E-only: validate that an upstream result contains an expected token.",
)
async def e2e_require_upstream(
    upstream_result: E2EText,
    expected_token: E2EText,
    nonce: E2EText,
) -> dict:
    """Validate a dependency result.

    Args:
        upstream_result: Serialized output received from an upstream tool.
        expected_token: Token that must occur in the upstream output.
        nonce: Unique test token included in the response.
    """
    return await e2e_test_tools.require_upstream(upstream_result, expected_token, nonce)


# E2E test tool: intentional fast failure
@local_mcp_service.tool(
    name="e2e_fast_fail",
    description="E2E-only: raise a deterministic error after a short delay.",
)
async def e2e_fast_fail(nonce: E2EText, delay_ms: E2EInteger = 1000) -> None:
    """Raise an intentional test failure.

    Args:
        nonce: Unique test token included in the error.
        delay_ms: Delay in milliseconds before raising the error.
    """
    await e2e_test_tools.fast_fail(nonce, delay_ms)


# E2E test tool: controlled slow response
@local_mcp_service.tool(
    name="e2e_slow_timeout",
    description="E2E-only: produce a slow response for timeout and cancellation tests.",
)
async def e2e_slow_timeout(nonce: E2EText, delay_ms: E2EInteger = 130_000) -> dict:
    """Return after a timeout-sized delay.

    Args:
        nonce: Unique test token included in the response.
        delay_ms: Delay in milliseconds before returning.
    """
    return await e2e_test_tools.slow_timeout(nonce, delay_ms)


# E2E test tool: empty text response
@local_mcp_service.tool(
    name="e2e_return_empty",
    description="E2E-only: return an empty string to exercise empty-result handling.",
)
async def e2e_return_empty() -> str:
    """Return an empty string fixture."""
    return await e2e_test_tools.return_empty()


# E2E test tool: large text response
@local_mcp_service.tool(
    name="e2e_return_large_text",
    description="E2E-only: return deterministic text with a requested length.",
)
async def e2e_return_large_text(length: E2EInteger, character: E2EText = "X") -> str:
    """Return repeated text.

    Args:
        length: Number of characters to return.
        character: Single character repeated in the result.
    """
    return await e2e_test_tools.return_large_text(length, character)


# E2E test tool: XLSX artifact
@local_mcp_service.tool(
    name="e2e_make_xlsx",
    description="E2E-only: create a deterministic XLSX artifact.",
)
async def e2e_make_xlsx(nonce: E2EText, file_name: E2EText = "") -> dict:
    """Create an XLSX fixture.

    Args:
        nonce: Unique test token embedded in the workbook.
        file_name: Optional output file name.
    """
    return await e2e_test_tools.make_xlsx(nonce, file_name)


# E2E test tool: DOCX artifact
@local_mcp_service.tool(
    name="e2e_make_docx",
    description="E2E-only: create a deterministic DOCX artifact.",
)
async def e2e_make_docx(nonce: E2EText, file_name: E2EText = "") -> dict:
    """Create a DOCX fixture.

    Args:
        nonce: Unique test token embedded in the document.
        file_name: Optional output file name.
    """
    return await e2e_test_tools.make_docx(nonce, file_name)


# E2E test tool: CSV artifact
@local_mcp_service.tool(
    name="e2e_make_csv",
    description="E2E-only: create a deterministic CSV artifact.",
)
async def e2e_make_csv(nonce: E2EText, file_name: E2EText = "") -> dict:
    """Create a CSV fixture.

    Args:
        nonce: Unique test token embedded in the data.
        file_name: Optional output file name.
    """
    return await e2e_test_tools.make_csv(nonce, file_name)


# E2E test tool: PDF artifact
@local_mcp_service.tool(
    name="e2e_make_pdf",
    description="E2E-only: create a deterministic multi-page PDF artifact.",
)
async def e2e_make_pdf(
    nonce: E2EText,
    file_name: E2EText = "",
    page_count: E2EInteger = 2,
) -> dict:
    """Create a PDF fixture.

    Args:
        nonce: Unique test token embedded in the PDF.
        file_name: Optional output file name.
        page_count: Number of pages to generate.
    """
    return await e2e_test_tools.make_pdf(nonce, file_name, page_count)


# E2E test tool: safe Mermaid response
@local_mcp_service.tool(
    name="e2e_return_mermaid",
    description="E2E-only: return a deterministic Mermaid chart fixture.",
)
async def e2e_return_mermaid(chart_kind: E2EText = "flowchart") -> dict:
    """Return a Mermaid fixture.

    Args:
        chart_kind: Supported Mermaid chart fixture kind.
    """
    return await e2e_test_tools.return_mermaid(chart_kind)


# E2E test tool: unsafe Mermaid response
@local_mcp_service.tool(
    name="e2e_return_unsafe_mermaid",
    description="E2E-only: return inert unsafe Mermaid text for sanitization tests.",
)
async def e2e_return_unsafe_mermaid(nonce: E2EText) -> dict:
    """Return an unsafe Mermaid text fixture.

    Args:
        nonce: Unique test token embedded in the fixture.
    """
    return await e2e_test_tools.return_unsafe_mermaid(nonce)
