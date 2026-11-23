// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  agentMonitoringSelection,
  formatAgentMetric,
  getAgentSuccessRate,
  getAgentTrendValue,
  successSampleCount,
} from "@/app/ops/dashboard/agentMonitoringValues";
import { fetchWithAuth } from "@/lib/auth";
import {
  getAgentMonitoringSummary,
  getAgentMonitoringTrends,
} from "@/services/agentMonitoringService";
import type { AgentMonitoringDay } from "@/types/agentMonitoring";

vi.mock("@/lib/auth", () => ({ fetchWithAuth: vi.fn() }));

const range = ["2026-11-17", "2026-11-23"] as [string, string];
const noExecutions: AgentMonitoringDay = {
  statistic_date: range[0],
  execution_count: 0,
  succeeded_count: 0,
  failed_count: 0,
  success_rate: null,
  coverage_state: "covered",
  tokens: { total_tokens: null },
  token_status: {
    coverage_state: "uncovered",
    data_as_of: null,
    is_stale: false,
  },
};

describe("Agent monitoring values", () => {
  it("uses a selected Agent's tenant and suppresses invalid request scopes", () => {
    expect(agentMonitoringSelection(undefined, range, "")).toBeNull();
    expect(agentMonitoringSelection("a", null, "")).toBeNull();
    expect(
      agentMonitoringSelection(null, range, "12", { id: 8, tenant_id: "b" })
    ).toEqual({
      tenantId: "b",
      agentId: 8,
      groupIds: [12],
      startDate: range[0],
      endDate: range[1],
    });
    expect(agentMonitoringSelection(null, range, "")?.tenantId).toBeNull();
  });

  it("preserves exact Token values, unknown values, and known zero", () => {
    expect(formatAgentMetric("9007199254740993", "total_tokens", "en")).toBe(
      "9,007,199,254,740,993"
    );
    expect(formatAgentMetric("0", "total_tokens", "en")).toBe("0");
    expect(formatAgentMetric(null, "total_tokens", "en")).toBe("—");
    expect(getAgentTrendValue(noExecutions, "total_tokens")).toBeNull();
    expect(getAgentTrendValue(noExecutions, "execution_count")).toBe(0);
    expect(
      getAgentTrendValue(
        { ...noExecutions, execution_count: null },
        "execution_count"
      )
    ).toBeNull();
  });

  it("shows no rate for zero or missing samples and retains a true 0% rate", () => {
    expect(successSampleCount(noExecutions)).toBe(0);
    expect(
      getAgentSuccessRate({ ...noExecutions, success_rate: 0 })
    ).toBeNull();
    expect(
      getAgentSuccessRate({
        ...noExecutions,
        failed_count: null,
        success_rate: 0,
      })
    ).toBeNull();
    const failed = { ...noExecutions, failed_count: 2, success_rate: 0 };
    expect(successSampleCount(failed)).toBe(2);
    expect(getAgentTrendValue(failed, "success_rate")).toBe(0);
    expect(formatAgentMetric(0, "success_rate", "en")).toBe("0%");
  });
});

describe("Agent monitoring requests", () => {
  const fetch = vi.mocked(fetchWithAuth);
  const signal = new AbortController().signal;
  const selection = agentMonitoringSelection("a&b", range, "12", {
    id: 8,
    tenant_id: "a&b",
  })!;

  beforeEach(() => fetch.mockReset());

  it("uses the existing summary and trend paths with the complete scope and cancellation", async () => {
    const payload = { data: [], coverage_state: "partial", is_stale: true };
    fetch.mockImplementation(async () => new Response(JSON.stringify(payload)));
    expect(
      await getAgentMonitoringSummary(
        { ...selection, groupIds: [12, 14] },
        signal
      )
    ).toEqual(payload);
    expect(
      await getAgentMonitoringTrends(
        agentMonitoringSelection(null, range, "")!,
        signal
      )
    ).toEqual(payload);
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/ops/v1/monitoring/agents/summary?start_date=2026-11-17&end_date=2026-11-23&tenant_id=a%26b&agent_id=8&group_ids=12&group_ids=14",
      { signal }
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/ops/v1/monitoring/agents/trends?start_date=2026-11-17&end_date=2026-11-23",
      { signal }
    );
  });

  it("preserves authenticated request errors for the corresponding query", async () => {
    const error = new Error("Service unavailable");
    fetch.mockRejectedValueOnce(error);
    await expect(getAgentMonitoringSummary(selection, signal)).rejects.toBe(
      error
    );
  });
});
