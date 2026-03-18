import type { McpServer } from "@/types/agentConfig";
import type { McpServiceItem } from "@/types/mcpTools";
import {
  MCP_HEALTH_STATUS,
  MCP_SERVER_TYPE,
  MCP_SERVICE_STATUS,
  MCP_TAB,
} from "@/const/mcpTools";

export const VERSION_PATTERN = /^\d+\.\d+\.\d+$/;

export const mapServersToServiceCards = (
  serverList: McpServer[] | undefined,
  t: (key: string) => string
): McpServiceItem[] => {
  return (serverList ?? []).map((server) => {
    const normalizedUrl = typeof server.mcp_url === "string" ? server.mcp_url : "";
    const inferredType = normalizedUrl.startsWith("container://")
      ? MCP_SERVER_TYPE.CONTAINER
      : MCP_SERVER_TYPE.HTTP;

    return {
      name: typeof server.service_name === "string" ? server.service_name : "",
      description: t("mcpTools.service.defaultDescription"),
      source: MCP_TAB.LOCAL,
      status: server.status ? MCP_SERVICE_STATUS.ENABLED : MCP_SERVICE_STATUS.DISABLED,
      updatedAt: "",
      tags: [],
      serverType: inferredType,
      serverUrl: normalizedUrl,
      tools: [],
      healthStatus: server.status ? MCP_HEALTH_STATUS.HEALTHY : MCP_HEALTH_STATUS.UNCHECKED,
      authorizationToken: typeof server.authorization_token === "string" ? server.authorization_token : undefined,
    };
  });
};

export const filterServiceCards = (services: McpServiceItem[], searchValue: string): McpServiceItem[] => {
  const keyword = searchValue.trim().toLowerCase();
  if (!keyword) {
    return services;
  }

  return services.filter((item) => {
    return (
      item.name.toLowerCase().includes(keyword) ||
      item.description.toLowerCase().includes(keyword) ||
      item.tags.some((tag) => tag.toLowerCase().includes(keyword))
    );
  });
};

export const formatMarketDate = (value: string): string => {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`;
};

export const formatMarketVersion = (value: string): string => {
  const version = (value || "").trim();
  if (!version) return "-";
  return /^v/i.test(version) ? version : `v${version}`;
};
