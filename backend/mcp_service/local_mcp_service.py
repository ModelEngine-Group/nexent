from fastmcp import FastMCP

# Create MCP server
local_mcp_service = FastMCP("local")

@local_mcp_service.tool(name="test_tool_name",
                        description="test_tool_description")
async def demo_tool(para_1: str, para_2: int) -> str:
    print("tool is called successfully")
    return "success"

