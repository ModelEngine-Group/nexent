// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import type { McpMonitoringRow, McpServiceFilter } from "@/types/mcpMonitoring";

export function mcpRowKey(row: McpMonitoringRow): string {
  return JSON.stringify([
    row.tenant_id,
    row.mcp_server_id,
    row.mcp_server_name,
    row.mcp_server_type,
    row.tool_name,
  ]);
}

function mcpServiceName(row: McpMonitoringRow): string {
  return (
    row.mcp_server_name ||
    (row.mcp_server_id === null ? "—" : `#${row.mcp_server_id}`)
  );
}

export function mcpRowName(row: McpMonitoringRow): string {
  return row.tool_name || mcpServiceName(row);
}

export function getMcpDrilldownService(
  row: McpMonitoringRow
): McpServiceFilter | undefined {
  const type = row.mcp_server_type;
  if (
    !row.tenant_id ||
    (row.tool_name !== undefined &&
      (!row.tool_name || row.tool_name.length > 200)) ||
    (row.mcp_server_id === null && type !== "builtin" && type !== "api_convert")
  )
    return undefined;

  return {
    service_id: row.mcp_server_id,
    name: mcpServiceName(row),
    type:
      row.mcp_server_id === null &&
      row.mcp_server_name === "outer-apis" &&
      type === "api_convert"
        ? "builtin"
        : type,
  };
}
