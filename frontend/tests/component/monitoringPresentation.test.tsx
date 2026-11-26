// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MonitoringDashboard } from "@/app/ops/dashboard/MonitoringDashboard";
import * as agentService from "@/services/agentMonitoringService";
import * as operationsService from "@/services/operationsService";
import { getTenant, listTenants } from "@/services/tenantService";
import en from "@/public/locales/en/common.json";
import zh from "@/public/locales/zh/common.json";
import type { MonitoringPublication } from "@/types/operations";

const auth = vi.hoisted(() => ({
  user: { id: "operator", tenantId: "tenant-a", role: "OPS", roles: ["OPS"] },
  isLoading: false,
  hasPermission: () => true,
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => auth,
}));
vi.mock("@/services/tenantService", () => ({
  getTenant: vi.fn(),
  listTenants: vi.fn(),
}));
vi.mock("@/services/operationsService", () => ({
  checkOperationsScope: vi.fn(),
  listOperationsResources: vi.fn(),
  listOperationsMcpTools: vi.fn(),
}));
vi.mock("@/services/mcpMonitoringService", () => ({
  getMcpMonitoringCatalog: vi.fn(async () => []),
}));
vi.mock("@/services/groupService", () => ({
  listGroups: vi.fn(async () => ({ groups: [] })),
}));
vi.mock("@/services/agentMonitoringService", () => ({
  getAgentMonitoringSummary: vi.fn(),
  getAgentMonitoringTrends: vi.fn(),
  getAgentMonitoringList: vi.fn(),
  getAgentMonitoringRankings: vi.fn(),
}));
vi.mock("@/app/ops/dashboard/components/overview/MonitoringOverview", () => ({
  MonitoringOverview: ({ scopeLabel }: { scopeLabel: string }) => (
    <h2>{scopeLabel}</h2>
  ),
}));
vi.mock("@/app/ops/dashboard/components/model/ModelMonitoringPanels", () => ({
  ModelMonitoringPanels: () => null,
}));
vi.mock("@/app/ops/dashboard/components/model/ModelMonitoringDetails", () => ({
  ModelMonitoringDetails: () => null,
}));
vi.mock("@/app/ops/dashboard/components/mcp/McpMonitoring", () => ({
  McpMonitoring: () => null,
}));
vi.mock("@/app/ops/dashboard/components/skill/SkillMonitoring", () => ({
  SkillMonitoring: () => null,
}));

const unpublished: MonitoringPublication = {
  coverage_state: "uncovered",
  data_as_of: null,
  is_stale: false,
};
const published: MonitoringPublication = {
  coverage_state: "partial",
  data_as_of: "2026-11-24T06:00:00Z",
  is_stale: true,
};

async function mount(ui = <MonitoringDashboard />, language = "zh") {
  const i18n = createInstance();
  await i18n.init({
    lng: language,
    defaultNS: "common",
    resources: { zh: { common: zh }, en: { common: en } },
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={client}>{ui}</QueryClientProvider>
    </I18nextProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  auth.user = {
    id: "operator",
    tenantId: "tenant-a",
    role: "OPS",
    roles: ["OPS"],
  };
  vi.mocked(getTenant).mockResolvedValue({
    tenant_id: "tenant-a",
    tenant_name: "租户 A",
  });
  vi.mocked(operationsService.checkOperationsScope).mockImplementation(
    async (_, tenant) => ({
      tenant_id: tenant ?? null,
      scope: tenant ? "current_tenant" : "all_tenants",
    })
  );
  vi.mocked(operationsService.listOperationsResources).mockResolvedValue([]);
  vi.mocked(agentService.getAgentMonitoringSummary).mockResolvedValue({
    ...published,
    token_status: unpublished,
    data: {
      execution_count: null,
      succeeded_count: null,
      failed_count: null,
      success_rate: null,
    },
    tokens: { total_tokens: null },
  });
  vi.mocked(agentService.getAgentMonitoringTrends).mockResolvedValue({
    ...unpublished,
    token_status: unpublished,
    data: [],
  });
  vi.mocked(agentService.getAgentMonitoringRankings).mockResolvedValue({
    ...unpublished,
    token_status: unpublished,
    data: [],
  });
  vi.mocked(agentService.getAgentMonitoringList).mockResolvedValue({
    ...unpublished,
    token_status: unpublished,
    data: {
      items: [
        {
          tenant_id: "tenant-a",
          agent_id: 1,
          name: "Support",
          is_current: true,
          metrics: null,
          tokens: { total_tokens: null },
          token_status: unpublished,
        },
      ],
      total: 1,
      current_agent_count: 1,
    },
  });
});

describe("Monitoring tenant labels", () => {
  it("uses the current tenant name in the disabled selector and both page headings without listing other tenants", async () => {
    await mount();
    expect(
      await screen.findByRole("heading", { name: "租户 A" })
    ).toBeVisible();
    const selector = screen.getByRole("combobox", { name: "租户" });
    expect(selector).toBeDisabled();
    expect(selector.closest(".ant-select")).toHaveTextContent("租户 A");
    expect(getTenant).toHaveBeenCalledWith("tenant-a");
    expect(listTenants).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("tab", { name: "智能体" }));
    expect(
      await screen.findByRole("heading", { name: "全部智能体 · 租户 A" })
    ).toBeVisible();
    await waitFor(() =>
      expect(agentService.getAgentMonitoringSummary).toHaveBeenCalledWith(
        expect.objectContaining({ tenantId: "tenant-a" }),
        expect.any(AbortSignal)
      )
    );
  });

  it("keeps SU tenant selection and pagination while displaying names", async () => {
    auth.user = { ...auth.user, role: "SU", roles: ["SU"] };
    vi.mocked(listTenants).mockImplementation(async (params) => ({
      data: [
        {
          tenant_id: params?.page === 1 ? "tenant-a" : "tenant-b",
          tenant_name: params?.page === 1 ? "租户 A" : "租户 B",
        },
      ],
      page: params?.page ?? 1,
      page_size: 100,
      total: 101,
      total_pages: 2,
      message: "ok",
    }));
    await mount();
    await waitFor(() => expect(listTenants).toHaveBeenCalledTimes(2));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "租户" }));
    fireEvent.click(await screen.findByText("租户 B"));
    expect(
      await screen.findByRole("heading", { name: "租户 B" })
    ).toBeVisible();
    expect(getTenant).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(operationsService.checkOperationsScope).toHaveBeenCalledWith(
        "dashboard",
        "tenant-b"
      )
    );
  });

  it("shows loading and an unavailable label on failure without exposing the ID or blocking statistics", async () => {
    let reject!: (reason: Error) => void;
    vi.mocked(getTenant).mockReturnValue(
      new Promise((_, fail) => {
        reject = fail;
      })
    );
    const { container } = await mount();
    expect(screen.getByRole("heading", { name: "加载中" })).toBeVisible();
    await act(async () => reject(new Error("Unavailable")));
    expect(
      await screen.findByRole("heading", { name: "租户名称暂不可用" })
    ).toBeVisible();
    expect(container).not.toHaveTextContent("tenant-a");
    fireEvent.click(screen.getByRole("tab", { name: "智能体" }));
    await waitFor(() =>
      expect(agentService.getAgentMonitoringSummary).toHaveBeenCalled()
    );
  });

  it("uses the unavailable label when the API returns a blank name", async () => {
    vi.mocked(getTenant).mockResolvedValue({
      tenant_id: "tenant-a",
      tenant_name: "   ",
    });
    await mount();
    expect(
      await screen.findByRole("heading", { name: "租户名称暂不可用" })
    ).toBeVisible();
  });
});
