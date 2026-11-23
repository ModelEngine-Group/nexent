// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { countOverviewResources } from "@/app/ops/dashboard/components/overview/overviewCounts";
import { fetchWithAuth } from "@/lib/auth";
import { getModelMonitoringTrends } from "@/services/modelMonitoringService";
import { listOperationsResources } from "@/services/operationsService";
import type { OperationsResource } from "@/types/operations";

vi.mock("@/lib/auth", () => ({ fetchWithAuth: vi.fn() }));

const agent: OperationsResource = {
  kind: "agent",
  tenant_id: "a",
  id: 1,
  name: "Support",
};
const model: OperationsResource = {
  kind: "model",
  tenant_id: "a",
  id: 1,
  name: "Text",
};

describe("Overview current resources", () => {
  it("counts each tenant-qualified identity once within its kind", () => {
    expect(
      countOverviewResources([
        agent,
        { ...agent, name: "Renamed" },
        { ...agent, tenant_id: "b" },
        model,
        { ...agent, kind: "mcp" },
        { ...agent, kind: "knowledge" },
      ])
    ).toEqual({ agent: 2, model: 1 });
    expect(countOverviewResources([])).toEqual({ agent: 0, model: 0 });
  });
});

describe("Overview requests", () => {
  const fetch = vi.mocked(fetchWithAuth);
  const signal = new AbortController().signal;
  const scope = {
    tenantId: "a&b",
    startDate: "2026-11-17",
    endDate: "2026-11-23",
  };

  beforeEach(() => fetch.mockReset());

  it("reads every inventory page by tenant with no date filter", async () => {
    fetch
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ data: { items: [agent], total: 101 } }))
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ data: { items: [model], total: 101 } }))
      );
    const data = await listOperationsResources(scope.tenantId, signal);
    expect(countOverviewResources(data)).toEqual({ agent: 1, model: 1 });
    expect(fetch.mock.calls).toEqual([
      ["/api/ops/resources?page_size=100&tenant_id=a%26b&page=1", { signal }],
      ["/api/ops/resources?page_size=100&tenant_id=a%26b&page=2", { signal }],
    ]);
  });

  it("reads daily request counts and retains missing values, zero and publication metadata", async () => {
    const payload = {
      coverage_state: "partial",
      data_as_of: "2026-11-23T06:01:02Z",
      is_stale: true,
      data: [
        { statistic_date: "2026-11-17", request_count: null },
        { statistic_date: "2026-11-18", request_count: 0 },
      ],
    };
    fetch.mockResolvedValueOnce(new Response(JSON.stringify(payload)));
    await expect(getModelMonitoringTrends(scope, signal)).resolves.toEqual(
      payload
    );
    expect(fetch).toHaveBeenCalledWith(
      "/api/ops/v1/monitoring/models/trends?start_date=2026-11-17&end_date=2026-11-23&tenant_id=a%26b",
      { signal }
    );
  });

  it("omits the tenant for all-tenant reads and propagates failures", async () => {
    const error = new Error("Model monitoring unavailable");
    fetch.mockRejectedValueOnce(error);
    await expect(
      getModelMonitoringTrends({ ...scope, tenantId: null }, signal)
    ).rejects.toBe(error);
    expect(fetch).toHaveBeenCalledWith(
      "/api/ops/v1/monitoring/models/trends?start_date=2026-11-17&end_date=2026-11-23",
      { signal }
    );
  });
});
