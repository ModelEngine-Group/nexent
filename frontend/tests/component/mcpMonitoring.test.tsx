// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getMcpDrilldownService,
  mcpRowKey,
} from "@/app/ops/dashboard/components/mcp/mcpMonitoringValues";
import { fetchWithAuth } from "@/lib/auth";
import {
  getMcpMonitoringCatalog,
  getMcpMonitoringList,
  getMcpMonitoringOverview,
  getMcpMonitoringRankings,
  getMcpMonitoringSummary,
  getMcpMonitoringTrends,
} from "@/services/mcpMonitoringService";
import type {
  McpMonitoringRow,
  McpMonitoringSelection,
} from "@/types/mcpMonitoring";

vi.mock("@/lib/auth", () => ({ fetchWithAuth: vi.fn() }));

describe("MCP monitoring reads", () => {
  const fetch = vi.mocked(fetchWithAuth);
  const endpoint = "/api/ops/v1/monitoring/mcp-tools";
  const scope: McpMonitoringSelection = {
    tenantId: "tenant/a",
    groupIds: [3, 5],
    serviceId: 12,
    serverType: null,
    toolName: "find + list",
    startDate: "2026-11-24",
    endDate: "2026-11-25",
  };
  const signal = new AbortController().signal;
  const publication = {
    coverage_state: "partial",
    data_as_of: "2026-11-24T12:00:00Z",
    is_stale: true,
  };

  beforeEach(() => fetch.mockReset());

  it("sends the group filter with the registered catalog request", async () => {
    const data = [
      { service_id: 12, name: "Registered service", type: "remote" },
      { service_id: null, name: "Builtin", type: "builtin" },
    ];
    fetch.mockImplementation(async () => Response.json({ data }));

    await expect(
      getMcpMonitoringCatalog(scope.tenantId, scope.groupIds, signal)
    ).resolves.toEqual(data);
    await expect(getMcpMonitoringCatalog(null, [], signal)).resolves.toEqual(data);
    expect(fetch.mock.calls).toEqual([
      [
        `${endpoint}/catalog?tenant_id=tenant%2Fa&group_ids=3&group_ids=5`,
        { signal },
      ],
      [`${endpoint}/catalog`, { signal }],
    ]);
  });

  it("uses the same scoped parameters for summary and trends and keeps null and zero", async () => {
    const summary = {
      ...publication,
      data: { tool_count: 0, request_count: 0 },
    };
    const trend = {
      ...publication,
      data: [
        { statistic_date: "2026-11-24", request_count: null },
        { statistic_date: "2026-11-25", request_count: 0 },
      ],
    };
    fetch
      .mockResolvedValueOnce(Response.json(summary))
      .mockResolvedValueOnce(Response.json(trend));

    await expect(getMcpMonitoringSummary(scope, signal)).resolves.toEqual(
      summary
    );
    await expect(getMcpMonitoringTrends(scope, signal)).resolves.toEqual(trend);
    const params =
      "start_date=2026-11-24&end_date=2026-11-25&tenant_id=tenant%2Fa&group_ids=3&group_ids=5&server_id=12&tool_name=find+%2B+list";
    expect(fetch.mock.calls).toEqual([
      [`${endpoint}/summary?${params}`, { signal }],
      [`${endpoint}/trends?${params}`, { signal }],
    ]);
  });

  it("sends only server type for the synthetic service and propagates read errors", async () => {
    const failure = new Error("Monitoring unavailable");
    const allServices = {
      ...scope,
      tenantId: null,
      groupIds: [],
      serviceId: null,
      toolName: null,
    };
    fetch
      .mockRejectedValueOnce(failure)
      .mockResolvedValueOnce(Response.json({ ...publication, data: [] }));

    await expect(getMcpMonitoringSummary(allServices, signal)).rejects.toBe(
      failure
    );
    await expect(
      getMcpMonitoringTrends({ ...allServices, serverType: "builtin" }, signal)
    ).resolves.toEqual({ ...publication, data: [] });
    const dates = "start_date=2026-11-24&end_date=2026-11-25";
    expect(fetch.mock.calls).toEqual([
      [`${endpoint}/summary?${dates}`, { signal }],
      [`${endpoint}/trends?${dates}&server_type=builtin`, { signal }],
    ]);
  });

  it("uses server-side list controls and leaves their parameters off rankings", async () => {
    fetch
      .mockResolvedValueOnce(
        Response.json({ ...publication, data: { items: [], total: 0 } })
      )
      .mockResolvedValueOnce(Response.json({ ...publication, data: [] }));
    await expect(
      getMcpMonitoringList(
        scope,
        "tools",
        {
          page: 2,
          pageSize: 10,
          search: "x & y",
          sortBy: "avg_duration_ms",
          descending: false,
        },
        signal
      )
    ).resolves.toEqual({ ...publication, data: { items: [], total: 0 } });
    await expect(
      getMcpMonitoringRankings(scope, "tools", signal)
    ).resolves.toEqual({ ...publication, data: [] });
    expect(fetch.mock.calls).toEqual([
      [
        `${endpoint}?start_date=2026-11-24&end_date=2026-11-25&tenant_id=tenant%2Fa&group_ids=3&group_ids=5&server_id=12&tool_name=find+%2B+list&dimension=tools&page=2&page_size=10&search=x+%26+y&sort_by=avg_duration_ms&descending=false`,
        { signal },
      ],
      [
        `${endpoint}/rankings?start_date=2026-11-24&end_date=2026-11-25&tenant_id=tenant%2Fa&group_ids=3&group_ids=5&server_id=12&tool_name=find+%2B+list&dimension=tools&metric=request_count`,
        { signal },
      ],
    ]);
  });

  it("reads the platform overview with tenant and dates only", async () => {
    const data = {
      calls_trend: [{ statistic_date: "2026-11-24", request_count: 0 }],
    };
    fetch.mockResolvedValueOnce(Response.json({ ...publication, data }));
    await expect(getMcpMonitoringOverview(scope, signal)).resolves.toEqual({
      ...publication,
      data,
    });
    expect(fetch).toHaveBeenCalledWith(
      `${endpoint}/overview?start_date=2026-11-24&end_date=2026-11-25&tenant_id=tenant%2Fa`,
      { signal }
    );
  });
});

it("keeps tenant-qualified rows distinct and only drills into addressable service identities", () => {
  const row: McpMonitoringRow = {
    tenant_id: "a",
    mcp_server_id: 12,
    mcp_server_name: null,
    mcp_server_type: "remote",
    tool_name: "Search",
    metrics: { request_count: 0, avg_duration_ms: null },
  };
  expect(mcpRowKey(row)).not.toEqual(mcpRowKey({ ...row, tenant_id: "b" }));
  expect(getMcpDrilldownService(row)).toEqual({
    service_id: 12,
    type: "remote",
    name: "#12",
  });
  expect(
    getMcpDrilldownService({ ...row, mcp_server_id: null })
  ).toBeUndefined();
  expect(
    getMcpDrilldownService({ ...row, tool_name: "x".repeat(201) })
  ).toBeUndefined();
  expect(
    getMcpDrilldownService({
      ...row,
      mcp_server_id: null,
      mcp_server_type: "api_convert",
      mcp_server_name: "Local",
    })
  ).toEqual({
    service_id: null,
    type: "api_convert",
    name: "Local",
  });
});
