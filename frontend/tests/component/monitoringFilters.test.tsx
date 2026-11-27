// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { describe, expect, it } from "vitest";
import {
  getMonitoringRange,
  initialMonitoringFilters,
  updateMonitoringFilters,
} from "@/app/ops/dashboard/monitoringFilters";

describe("monitoring dates", () => {
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

  it("clears the MCP service and tool on a different group selection", () => {
    expect(
      updateMonitoringFilters(selected, { type: "group", value: "8" })
    ).toBe(selected);
    expect(
      updateMonitoringFilters(selected, { type: "group", value: "9" })
    ).toEqual({
      ...selected,
      group: "9",
      resources: { ...selected.resources, mcp: "" },
      tool: "",
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
