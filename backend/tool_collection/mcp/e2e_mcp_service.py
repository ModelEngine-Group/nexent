from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from tool_collection.mcp import e2e_test_tools

# Create the dedicated E2E MCP server.
e2e_mcp_service = FastMCP("e2e")


@e2e_mcp_service.tool(
    name="delay_echo",
    description="E2E-only: wait for a bounded delay and return nonce-tagged timing evidence.",
)
async def delay_echo(
    name: Annotated[str, Field(description="Logical task or agent name included in the result.")],
    nonce: Annotated[str, Field(description="Unique test-run token used to detect cross-run contamination.")],
    delay_ms: Annotated[int, Field(
        description="Delay in milliseconds, from 0 through 300000.",
        ge=0,
        le=300_000,
    )] = 0,
    payload: Annotated[str, Field(description="Optional text copied unchanged into the result.")] = "",
) -> dict[str, Any]:
    """Wait for a bounded delay and echo deterministic timing evidence."""
    return await e2e_test_tools.delay_echo(name, nonce, delay_ms, payload)


@e2e_mcp_service.tool(
    name="require_upstream",
    description="E2E-only: validate a token in an upstream result for serial tests.",
)
async def require_upstream(
    upstream_result: Annotated[str, Field(description="Text returned by the upstream task.")],
    expected_token: Annotated[str, Field(description="Token that must occur in the upstream result.")],
    nonce: Annotated[str, Field(description="Unique test-run token returned with the validation result.")],
) -> dict[str, Any]:
    """Validate a serial dependency and wrap the upstream result."""
    return await e2e_test_tools.require_upstream(upstream_result, expected_token, nonce)


@e2e_mcp_service.tool(
    name="fast_fail",
    description="E2E-only: fail deterministically after a bounded delay.",
)
async def fast_fail(
    nonce: Annotated[str, Field(description="Unique test-run token included in the raised error.")],
    delay_ms: Annotated[int, Field(
        description="Delay before failure in milliseconds, from 0 through 10000.",
        ge=0,
        le=10_000,
    )] = 1000,
) -> None:
    """Raise a deterministic runtime error after a bounded delay."""
    await e2e_test_tools.fast_fail(nonce, delay_ms)


@e2e_mcp_service.tool(
    name="slow_timeout",
    description="E2E-only: sleep long enough for a caller-configured timeout test.",
)
async def slow_timeout(
    nonce: Annotated[str, Field(description="Unique test-run token returned with the result.")],
    delay_ms: Annotated[int, Field(
        description="Delay in milliseconds, from 0 through 300000.",
        ge=0,
        le=300_000,
    )] = 130000,
) -> dict[str, Any]:
    """Wait for a controllable duration for timeout and cancellation tests."""
    return await e2e_test_tools.slow_timeout(nonce, delay_ms)


@e2e_mcp_service.tool(name="return_empty", description="E2E-only: return an empty string.")
async def return_empty() -> str:
    """Return an empty string for empty-result handling tests."""
    return await e2e_test_tools.return_empty()


@e2e_mcp_service.tool(
    name="return_large_text",
    description="E2E-only: return deterministic text with a bounded character count.",
)
async def return_large_text(
    length: Annotated[int, Field(
        description="Number of characters to return, from 0 through 1000000.",
        ge=0,
        le=1_000_000,
    )],
    character: Annotated[str, Field(
        description="Exactly one character repeated in the result.",
        min_length=1,
        max_length=1,
    )] = "X",
) -> str:
    """Return deterministic text of an exact bounded length."""
    return await e2e_test_tools.return_large_text(length, character)


@e2e_mcp_service.tool(
    name="make_xlsx",
    description="E2E-only: create a structurally valid Excel workbook for download tests.",
)
async def make_xlsx(
    nonce: Annotated[str, Field(description="Unique test-run token embedded in the workbook.")],
    file_name: Annotated[str, Field(description="Optional output filename; unsafe path components are removed.")] = "",
) -> dict[str, Any]:
    """Create a valid Excel workbook beneath the E2E artifact directory."""
    return await e2e_test_tools.make_xlsx(nonce, file_name)


@e2e_mcp_service.tool(
    name="make_docx",
    description="E2E-only: create a structurally valid Word document for download tests.",
)
async def make_docx(
    nonce: Annotated[str, Field(description="Unique test-run token embedded in the document.")],
    file_name: Annotated[str, Field(description="Optional output filename; unsafe path components are removed.")] = "",
) -> dict[str, Any]:
    """Create a valid Word document beneath the E2E artifact directory."""
    return await e2e_test_tools.make_docx(nonce, file_name)


@e2e_mcp_service.tool(
    name="make_csv",
    description="E2E-only: create a UTF-8 BOM CSV with quoting and multiline fields.",
)
async def make_csv(
    nonce: Annotated[str, Field(description="Unique test-run token embedded in the CSV rows.")],
    file_name: Annotated[str, Field(description="Optional output filename; unsafe path components are removed.")] = "",
) -> dict[str, Any]:
    """Create a CSV containing quoting, multiline, empty, and Unicode fields."""
    return await e2e_test_tools.make_csv(nonce, file_name)


@e2e_mcp_service.tool(
    name="make_pdf",
    description="E2E-only: create a valid deterministic multi-page PDF.",
)
async def make_pdf(
    nonce: Annotated[str, Field(description="Unique test-run token embedded in every page.")],
    file_name: Annotated[str, Field(description="Optional output filename; unsafe path components are removed.")] = "",
    page_count: Annotated[int, Field(
        description="Number of PDF pages, from 1 through 20.",
        ge=1,
        le=20,
    )] = 2,
) -> dict[str, Any]:
    """Create a valid bounded multi-page PDF beneath the artifact directory."""
    return await e2e_test_tools.make_pdf(nonce, file_name, page_count)


@e2e_mcp_service.tool(
    name="return_mermaid",
    description="E2E-only: return deterministic valid Mermaid source for a supported chart kind.",
)
async def return_mermaid(
    chart_kind: Annotated[str, Field(
        description="One of flowchart, sequence, pie, xy, gantt, or quadrant.",
    )] = "flowchart",
) -> dict[str, str]:
    """Return valid Mermaid source for a supported chart kind."""
    return await e2e_test_tools.return_mermaid(chart_kind)


@e2e_mcp_service.tool(
    name="return_unsafe_mermaid",
    description="E2E-only: return inert unsafe Mermaid text for sanitization tests.",
)
async def return_unsafe_mermaid(
    nonce: Annotated[str, Field(description="Unique test-run token embedded after filename-safe sanitization.")],
) -> dict[str, str]:
    """Return inert malicious-looking Mermaid text for frontend security tests."""
    return await e2e_test_tools.return_unsafe_mermaid(nonce)
