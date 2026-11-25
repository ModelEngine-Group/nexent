// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MonitoringOverview } from "@/app/ops/dashboard/components/overview/MonitoringOverview";
import { countOverviewResources } from "@/app/ops/dashboard/components/overview/overviewCounts";
import { fetchWithAuth } from "@/lib/auth";
import { getModelMonitoringTrends } from "@/services/modelMonitoringService";
import { listOperationsResources } from "@/services/operationsService";
import type { OperationsResource } from "@/types/operations";

vi.mock("@/lib/auth", () => ({ fetchWithAuth: vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));

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

  it("replaces a cached Skill count with the error state after a failed refresh", async () => {
    const fetch = vi.mocked(fetchWithAuth);
    fetch.mockReset();
    fetch
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ data: { current_skill_count: 0 } }))
      )
      .mockRejectedValueOnce(new Error("Skill count unavailable"));
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const directories = {
      tenant: "a",
      mcpCatalog: { isError: false, isFetching: false },
      mcpServiceCount: 0,
      scope: { isError: false },
      inventory: {
        data: [agent, model],
        isError: false,
        isPending: false,
        isFetching: false,
      },
    } as ComponentProps<typeof MonitoringOverview>["directories"];
    render(
      <QueryClientProvider client={queryClient}>
        <MonitoringOverview
          userId="operator"
          userTenant="a"
          directories={directories}
          canReadInventory
          scopeLabel="tenant-a"
          range={null}
          dateControls={null}
          dateLabel={null}
        />
      </QueryClientProvider>
    );
    const card = within(
      screen.getByText("ops.monitoring.count.skill").parentElement!
    );
    expect(await card.findByText("0")).toBeVisible();
    const mcpCard = within(
      screen.getByText("ops.monitoring.count.mcp").parentElement!
    );
    expect(mcpCard.getByText("0")).toBeVisible();
    await act(async () => {
      await queryClient.refetchQueries({ queryKey: ["monitoringOverview"] });
    });
    expect(await card.findByText("ops.loadError")).toBeVisible();
    expect(card.queryByText("0")).not.toBeInTheDocument();
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
