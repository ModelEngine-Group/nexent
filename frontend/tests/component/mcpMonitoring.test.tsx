// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchWithAuth } from "@/lib/auth";
import {
  getMcpMonitoringCatalog,
  getMcpMonitoringSummary,
  getMcpMonitoringTrends,
} from "@/services/mcpMonitoringService";
import type { McpMonitoringSelection } from "@/types/mcpMonitoring";

vi.mock("@/lib/auth", () => ({ fetchWithAuth: vi.fn() }));

describe("MCP monitoring reads", () => {
  const fetch = vi.mocked(fetchWithAuth);
  const endpoint = "/api/ops/v1/monitoring/mcp-tools";
  const scope: McpMonitoringSelection = {
    tenantId: "tenant/a",
    groupIds: [3, 5],
    serviceId: 12,
    builtin: false,
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

  it("reads the registered catalog independently of calendar, group and resource filters", async () => {
    const data = [
      { service_id: 12, name: "Registered service", type: "remote" },
      { service_id: null, name: "Builtin", type: "builtin" },
    ];
    fetch.mockImplementation(async () => Response.json({ data }));

    await expect(
      getMcpMonitoringCatalog(scope.tenantId, signal)
    ).resolves.toEqual(data);
    await expect(getMcpMonitoringCatalog(null, signal)).resolves.toEqual(data);
    expect(fetch.mock.calls).toEqual([
      [`${endpoint}/catalog?tenant_id=tenant%2Fa`, { signal }],
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
      getMcpMonitoringTrends({ ...allServices, builtin: true }, signal)
    ).resolves.toEqual({ ...publication, data: [] });
    const dates = "start_date=2026-11-24&end_date=2026-11-25";
    expect(fetch.mock.calls).toEqual([
      [`${endpoint}/summary?${dates}`, { signal }],
      [`${endpoint}/trends?${dates}&server_type=builtin`, { signal }],
    ]);
  });
});
