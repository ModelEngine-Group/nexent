// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SkillMonitoring } from "@/app/ops/dashboard/components/skill/SkillMonitoring";
import { getSkillUsageCount } from "@/app/ops/dashboard/components/skill/skillMonitoringValues";
import { fetchWithAuth } from "@/lib/auth";
import zh from "@/public/locales/zh/common.json";
import {
  getSkillMonitoringList,
  getSkillMonitoringRankings,
  getSkillMonitoringSummary,
  getSkillMonitoringTrends,
} from "@/services/skillMonitoringService";
import type {
  SkillMonitoringQueryKey,
  SkillMonitoringSummary,
} from "@/types/skillMonitoring";

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

  it("reads Skill rankings and sends search, paging and sorting only to the list", async () => {
    const row = {
      tenant_id: "tenant/a",
      skill_id: "uuid+1",
      skill_name: "Summarize",
      source: "official",
      metrics: null,
    };
    const listing = { ...summary, data: { items: [row], total: 14 } };
    const ranking = {
      ...summary,
      data: [{ ...row, metrics: { usage_count: 3 } }],
    };
    fetch
      .mockResolvedValueOnce(new Response(JSON.stringify(listing)))
      .mockResolvedValueOnce(new Response(JSON.stringify(ranking)));
    const options = {
      page: 2,
      pageSize: 10,
      search: "a+b c",
      sortBy: "name" as const,
      descending: false,
    };
    const allSkills = { ...scope, skillId: null };
    await expect(
      getSkillMonitoringList(allSkills, options, signal)
    ).resolves.toEqual(listing);
    await expect(
      getSkillMonitoringRankings(allSkills, signal)
    ).resolves.toEqual(ranking);
    expect(fetch.mock.calls).toEqual([
      [
        "/api/ops/v1/monitoring/skills?start_date=2026-11-24&end_date=2026-11-25&page=2&page_size=10&search=a%2Bb+c&sort_by=name&descending=false&tenant_id=tenant%2Fa&group_ids=3&group_ids=5",
        { signal },
      ],
      [
        "/api/ops/v1/monitoring/skills/rankings?start_date=2026-11-24&end_date=2026-11-25&tenant_id=tenant%2Fa&group_ids=3&group_ids=5",
        { signal },
      ],
    ]);
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

describe("Skill monitoring detail total", () => {
  const queryKey: SkillMonitoringQueryKey = [
    "skillMonitoring",
    "operator",
    "tenant-a",
    {
      tenantId: "tenant-a",
      skillId: null,
      groupIds: [],
      startDate: "2026-11-24",
      endDate: "2026-11-25",
    },
  ];

  async function mountList(initialTotal: number) {
    let total = initialTotal;
    const fetch = vi.mocked(fetchWithAuth);
    fetch.mockReset().mockImplementation(async (request) => {
      const url = new URL(String(request), "http://localhost");
      if (url.pathname.endsWith("/skills")) {
        const page = Number(url.searchParams.get("page"));
        const pageSize = Number(url.searchParams.get("page_size"));
        const items =
          (page - 1) * pageSize < total
            ? [
                {
                  tenant_id: "tenant-a",
                  skill_id: String(page),
                  skill_name: `Skill ${page}`,
                },
              ]
            : [];
        return new Response(
          JSON.stringify({ ...summary, data: { total, items } })
        );
      }
      const data = url.pathname.endsWith("/summary") ? summary.data : [];
      return new Response(JSON.stringify({ ...summary, data }));
    });
    const i18n = createInstance();
    await i18n.init({ lng: "zh", resources: { zh: { common: zh } } });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    render(
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={client}>
          <SkillMonitoring
            queryKey={queryKey}
            singleSkill={false}
            scopeLoading={false}
            hasRange
            onView={vi.fn()}
          />
        </QueryClientProvider>
      </I18nextProvider>
    );
    return {
      client,
      details: within(screen.getByRole("region", { name: "Skill 明细" })),
      setTotal: (nextTotal: number) => {
        total = nextTotal;
      },
    };
  }

  it("shows a zero total for a successful empty response", async () => {
    const { details } = await mountList(0);
    expect(await details.findByText("共 0 个技能")).toBeVisible();
  });

  it("keeps the filtered total on page two and hides it when a refetch fails", async () => {
    const { client, details } = await mountList(23);
    expect(await details.findByText("共 23 个技能")).toBeVisible();
    fireEvent.click(details.getByRole("button", { name: "Next Page" }));
    expect(await details.findByRole("cell", { name: "Skill 2" })).toBeVisible();
    expect(details.getByText("共 23 个技能")).toBeVisible();

    vi.mocked(fetchWithAuth).mockRejectedValueOnce(
      new Error("List unavailable")
    );
    await act(() =>
      client.refetchQueries({ queryKey: [...queryKey, "list"], type: "active" })
    );
    expect(await details.findByText("加载失败，请重试")).toBeVisible();
    expect(details.queryByText("共 23 个技能")).not.toBeInTheDocument();
  });

  it("jumps to a page and reloads the last valid page when the total shrinks", async () => {
    const { client, details, setTotal } = await mountList(23);
    await details.findByText("共 23 个技能");
    const pageInput = details.getByRole("textbox", { name: "Page" });
    fireEvent.change(pageInput, { target: { value: "3" } });
    fireEvent.keyUp(pageInput, { key: "Enter", keyCode: 13 });
    expect(await details.findByRole("cell", { name: "Skill 3" })).toBeVisible();

    setTotal(16);
    await act(() =>
      client.refetchQueries({ queryKey: [...queryKey, "list"], type: "active" })
    );
    expect(await details.findByRole("cell", { name: "Skill 2" })).toBeVisible();
    expect(details.getByText("共 16 个技能")).toBeVisible();
  });
});
