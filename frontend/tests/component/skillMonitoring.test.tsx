// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getSkillUsageCount } from "@/app/ops/dashboard/components/skill/skillMonitoringValues";
import { fetchWithAuth } from "@/lib/auth";
import {
  getSkillMonitoringSummary,
  getSkillMonitoringTrends,
} from "@/services/skillMonitoringService";
import type { SkillMonitoringSummary } from "@/types/skillMonitoring";

vi.mock("@/lib/auth", () => ({ fetchWithAuth: vi.fn() }));

const summary: SkillMonitoringSummary = {
  coverage_state: "partial",
  data_as_of: "2026-11-24T12:00:00Z",
  is_stale: false,
  data: { current_skill_count: 2, usage_count: 0, skill_count: 1 },
};

describe("Skill monitoring reads", () => {
  const fetch = vi.mocked(fetchWithAuth);
  const scope = {
    tenantId: "tenant/a",
    skillId: "uuid+1",
    groupIds: [3, 5],
    startDate: "2026-11-24",
    endDate: "2026-11-25",
  };
  const signal = new AbortController().signal;
  beforeEach(() => fetch.mockReset());

  it("uses the monitored scope for both authenticated, cancelable reads", async () => {
    const trend = {
      ...summary,
      data: [
        { statistic_date: "2026-11-24", usage_count: null },
        { statistic_date: "2026-11-25", usage_count: 0 },
      ],
    };
    fetch
      .mockResolvedValueOnce(new Response(JSON.stringify(summary)))
      .mockResolvedValueOnce(new Response(JSON.stringify(trend)));
    await expect(getSkillMonitoringSummary(scope, signal)).resolves.toEqual(
      summary
    );
    await expect(getSkillMonitoringTrends(scope, signal)).resolves.toEqual(
      trend
    );
    const params =
      "start_date=2026-11-24&end_date=2026-11-25&tenant_id=tenant%2Fa&skill_id=uuid%2B1&group_ids=3&group_ids=5";
    expect(fetch.mock.calls).toEqual([
      [`/api/ops/v1/monitoring/skills/summary?${params}`, { signal }],
      [`/api/ops/v1/monitoring/skills/trends?${params}`, { signal }],
    ]);
  });

  it("omits all-scope filters and propagates the request failure", async () => {
    const error = new Error("Skill statistics unavailable");
    fetch.mockRejectedValueOnce(error);
    await expect(
      getSkillMonitoringSummary(
        { ...scope, tenantId: null, skillId: null, groupIds: [] },
        signal
      )
    ).rejects.toBe(error);
    expect(fetch).toHaveBeenCalledWith(
      "/api/ops/v1/monitoring/skills/summary?start_date=2026-11-24&end_date=2026-11-25",
      { signal }
    );
  });
});

it("shows zero for published usage and hides the zero fallback when coverage is missing", () => {
  expect(getSkillUsageCount(summary)).toBe(0);
  const empty = { ...summary, data: { ...summary.data, skill_count: 0 } };
  expect(getSkillUsageCount(empty)).toBeNull();
  expect(
    getSkillUsageCount({ ...empty, coverage_state: "uncovered" })
  ).toBeNull();
  expect(getSkillUsageCount({ ...empty, coverage_state: "covered" })).toBe(0);
  expect(
    getSkillUsageCount({
      ...summary,
      data: { ...summary.data, usage_count: 9 },
    })
  ).toBe(9);
});
