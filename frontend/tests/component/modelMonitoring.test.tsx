// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getModelMetric } from "@/app/ops/dashboard/components/model/modelMonitoringValues";
import { fetchWithAuth } from "@/lib/auth";
import {
  getModelMonitoringList,
  getModelMonitoringSummary,
  getModelMonitoringTrends,
} from "@/services/modelMonitoringService";

vi.mock("@/lib/auth", () => ({ fetchWithAuth: vi.fn() }));

describe("Model monitoring list requests", () => {
  const fetch = vi.mocked(fetchWithAuth);
  const signal = new AbortController().signal;
  const scope = {
    tenantId: "a&b",
    startDate: "2026-11-17",
    endDate: "2026-11-23",
    modelId: 2,
    groupIds: [10, 20],
  };
  const list = { page: 1, pageSize: 10, search: "Qwen & DeepSeek" };

  beforeEach(() => fetch.mockReset());

  it("sends scoped paged search and returns the server payload", async () => {
    const payload = {
      data: { items: [], total: 0 },
      coverage_state: "partial",
    };
    fetch.mockResolvedValueOnce(new Response(JSON.stringify(payload)));
    await expect(getModelMonitoringList(scope, list, signal)).resolves.toEqual(
      payload
    );
    expect(fetch).toHaveBeenCalledWith(
      "/api/ops/v1/monitoring/models?start_date=2026-11-17&end_date=2026-11-23&tenant_id=a%26b&model_id=2&group_ids=10&group_ids=20&page=1&page_size=10&search=Qwen+%26+DeepSeek",
      { signal }
    );
  });

  it("omits cleared search and unselected filters and retains the request error", async () => {
    const error = new Error("Model list unavailable");
    fetch.mockRejectedValueOnce(error);
    await expect(
      getModelMonitoringList(
        { ...scope, tenantId: null, modelId: null, groupIds: [] },
        { ...list, search: "" },
        signal
      )
    ).rejects.toBe(error);
    expect(fetch).toHaveBeenCalledWith(
      "/api/ops/v1/monitoring/models?start_date=2026-11-17&end_date=2026-11-23&page=1&page_size=10",
      { signal }
    );
  });

  it("uses the same reporting scope for summary and trends", async () => {
    fetch.mockImplementation(
      async () => new Response(JSON.stringify({ data: [] }))
    );
    await getModelMonitoringSummary(scope, signal);
    await getModelMonitoringTrends(scope, signal);
    const params =
      "start_date=2026-11-17&end_date=2026-11-23&tenant_id=a%26b&model_id=2&group_ids=10&group_ids=20";
    expect(fetch.mock.calls).toEqual([
      [`/api/ops/v1/monitoring/models/summary?${params}`, { signal }],
      [`/api/ops/v1/monitoring/models/trends?${params}`, { signal }],
    ]);
  });
});

it("keeps known zero and exact Tokens and hides rates without eligible samples", () => {
  const counts = {
    request_count: 0,
    total_tokens: {
      value: "9007199254740993",
      known_count: 1,
      eligible_count: 1,
      coverage_rate: 1,
    },
    error_count: 0,
    error_eligible_count: 0,
    error_rate: 0,
  };
  expect(getModelMetric(counts, "tokens")).toBe("9007199254740993");
  expect(
    getModelMetric({ ...counts, total_tokens: null }, "tokens")
  ).toBeNull();
  expect(getModelMetric(counts, "requests")).toBe(0);
  expect(getModelMetric(counts, "errorRate")).toBeNull();
  expect(
    getModelMetric({ ...counts, error_eligible_count: 1 }, "errorRate")
  ).toBe(0);
});
