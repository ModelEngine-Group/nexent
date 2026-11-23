import type { McpTool } from "@/types/agentConfig";
import type { CommunityMcpCard } from "@/types/mcpTools";

type ToolSource = Pick<
  CommunityMcpCard,
  "registryJson" | "packages" | "remotes"
>;

export function resolveRepositoryMcpToolCount(service: ToolSource): number {
  const registryTools = service.registryJson?.tools;
  if (Array.isArray(registryTools)) return registryTools.length;
  const toolNames = service.registryJson?._toolNames;
  if (Array.isArray(toolNames)) return toolNames.length;
  if (service.packages?.length) return service.packages.length;
  if (service.remotes?.length) return service.remotes.length;
  return 0;
}

export function resolveRepositoryMcpTools(service: ToolSource): McpTool[] {
  const registryTools = service.registryJson?.tools;
  if (Array.isArray(registryTools)) {
    return registryTools
      .map((tool) => {
        if (typeof tool === "string") return { name: tool, description: "" };
        if (!tool || typeof tool !== "object") return null;
        const value = tool as Record<string, unknown>;
        const name = typeof value.name === "string" ? value.name : "";
        if (!name) return null;
        return {
          name,
          description:
            typeof value.description === "string" ? value.description : "",
        };
      })
      .filter((tool): tool is McpTool => tool !== null);
  }

  const toolNames = service.registryJson?._toolNames;
  if (!Array.isArray(toolNames)) return [];
  return toolNames
    .filter(
      (name): name is string => typeof name === "string" && name.length > 0
    )
    .map((name) => ({ name, description: "" }));
}
