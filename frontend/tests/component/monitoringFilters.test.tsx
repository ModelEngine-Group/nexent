// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getMonitoringRange,
  initialMonitoringFilters,
  matchesGroupScope,
  matchesMcpGroupScope,
  UNGROUPED_GROUP,
  updateMonitoringFilters,
} from "@/app/ops/dashboard/monitoringFilters";

describe("MCP group scope", () => {
  it.each([
    [{ type: "remote", group_ids: null }, true, false],
    [{ type: "container", group_ids: [] }, true, false],
    [{ type: "remote", group_ids: [12] }, false, true],
    [{ type: "builtin", group_ids: null }, false, false],
  ] as const)(
    "matches registered service %j",
    (service, ungrouped, assigned) => {
      expect(matchesMcpGroupScope(service, "")).toBe(true);
      expect(matchesMcpGroupScope(service, UNGROUPED_GROUP)).toBe(ungrouped);
      expect(matchesMcpGroupScope(service, "12")).toBe(assigned);
      expect(matchesMcpGroupScope(service, "99")).toBe(false);
    }
  );

  it("preserves the shared null handling outside MCP", () => {
    expect(matchesGroupScope(null, UNGROUPED_GROUP)).toBe(false);
  });
});

describe("monitoring dates", () => {
  afterEach(() => vi.useRealTimers());

  it("allows UTC today and rejects future custom dates after local midnight", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2027-01-01T00:15:00+08:00"));
    const today = updateMonitoringFilters(initialMonitoringFilters, {
      type: "customRange",
      value: ["2026-12-31", "2026-12-31"],
    });
    expect(today.customRange).toEqual(["2026-12-31", "2026-12-31"]);
    expect(
      updateMonitoringFilters(today, {
        type: "customRange",
        value: ["2026-12-31", "2027-01-01"],
      })
    ).toBe(today);
    expect(
      updateMonitoringFilters(today, {
        type: "customRange",
        value: ["2027-01-01", "2027-01-01"],
      })
    ).toBe(today);
  });

  it("counts seven and thirty inclusive UTC dates across a year boundary", () => {
    const now = new Date("2027-01-01T00:15:00+08:00");
    expect(getMonitoringRange("week", null, now)).toEqual([
      "2026-12-25",
      "2026-12-31",
    ]);
    expect(getMonitoringRange("month", null, now)).toEqual([
      "2026-12-02",
      "2026-12-31",
    ]);
    expect(getMonitoringRange("custom", null, now)).toBeNull();
  });

  it("accepts same-day and 366-day ranges and rejects inverted or oversized ranges", () => {
    const state = updateMonitoringFilters(initialMonitoringFilters, {
      type: "datePreset",
      value: "custom",
    });
    const longest = updateMonitoringFilters(state, {
      type: "customRange",
      value: ["2024-01-01", "2024-12-31"],
    });
    expect(getMonitoringRange(longest.datePreset, longest.customRange)).toEqual(
      ["2024-01-01", "2024-12-31"]
    );
    expect(
      updateMonitoringFilters(longest, {
        type: "customRange",
        value: ["2024-01-01", "2025-01-01"],
      })
    ).toBe(longest);
    expect(
      updateMonitoringFilters(longest, {
        type: "customRange",
        value: ["2024-12-31", "2024-01-01"],
      })
    ).toBe(longest);
    expect(
      updateMonitoringFilters(state, {
        type: "customRange",
        value: ["2024-12-31", "2024-12-31"],
      }).customRange
    ).toEqual(["2024-12-31", "2024-12-31"]);
  });
});

describe("monitoring filter dependencies", () => {
  const selected = {
    ...initialMonitoringFilters,
    tenant: "a",
    group: "8",
    resources: { agent: "agent-a", skill: "skill-a", mcp: "service-a" },
    tool: "query",
    datePreset: "custom" as const,
    customRange: ["2026-11-04", "2026-11-10"] as [string, string],
  };

  it("clears all tenant-dependent filters while preserving dates", () => {
    expect(
      updateMonitoringFilters(selected, { type: "tenant", value: "a" })
    ).toBe(selected);
    expect(
      updateMonitoringFilters(selected, { type: "tenant", value: "b" })
    ).toEqual({
      ...selected,
      tenant: "b",
      group: "",
      resources: {},
      tool: "",
    });
  });

  it("keeps candidate resources until the destination group is checked", () => {
    expect(
      updateMonitoringFilters(selected, { type: "group", value: "8" })
    ).toEqual(selected);
    expect(
      updateMonitoringFilters(selected, { type: "group", value: "9" })
    ).toEqual({
      ...selected,
      group: "9",
    });
  });

  it("only clears the tool on a different MCP service selection", () => {
    expect(
      updateMonitoringFilters(selected, {
        type: "resource",
        tab: "mcp",
        value: "service-a",
      })
    ).toBe(selected);
    expect(
      updateMonitoringFilters(selected, {
        type: "resource",
        tab: "model",
        value: "model-a",
      }).tool
    ).toBe("query");
    expect(
      updateMonitoringFilters(selected, {
        type: "resource",
        tab: "mcp",
        value: "",
      })
    ).toEqual({
      ...selected,
      resources: { ...selected.resources, mcp: "" },
      tool: "",
    });
  });

  it("selects and clears a Skill without changing the other filters", () => {
    const anotherSkill = updateMonitoringFilters(selected, {
      type: "resource",
      tab: "skill",
      value: "another-skill-a",
    });
    expect(anotherSkill).toEqual({
      ...selected,
      resources: { ...selected.resources, skill: "another-skill-a" },
    });
    expect(
      updateMonitoringFilters(anotherSkill, {
        type: "resource",
        tab: "skill",
        value: "",
      })
    ).toEqual({
      ...selected,
      resources: { ...selected.resources, skill: "" },
    });
  });
});
