// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, expect, it } from "vitest";
import {
  BodyCache,
  filterTree,
  formatMetric,
  resetFilters,
} from "@/lib/trajectory";
import type { TrajectoryNode } from "@/types/trajectory";

const node = (
  id: string,
  parent_id: string | null,
  name: string,
  kind = "agent"
) =>
  ({
    id,
    parent_id,
    name,
    kind,
    input: { text: "retention_days" },
    output: { text: "" },
  }) as TrajectoryNode;

describe("trajectory state boundaries", () => {
  it("retains matching ancestors, intersects type and text, and tolerates cycles", () => {
    const nodes = [
      node("r", null, "root"),
      node("a", "r", "model", "model"),
      node("t", "a", "tool", "tool"),
    ];
    expect([...filterTree(nodes, "retention_days", "tool")]).toEqual([
      "t",
      "a",
      "r",
    ]);
    expect(filterTree(nodes, "missing", "tool").size).toBe(0);
    expect(
      filterTree([node("a", "b", "a"), node("b", "a", "b")], "a", "").size
    ).toBe(2);
  });

  it("distinguishes unknown, invalid, and valid zero metrics", () => {
    expect(formatMetric(null)).toBe("—");
    expect(formatMetric(Number.NaN)).toBe("—");
    expect(formatMetric(-1)).toBe("—");
    expect(formatMetric(0)).toBe("0");
  });

  it("clears dependent identifiers without coercing large conversation IDs", () => {
    const f = {
      tenant_id: "t",
      target_user_id: "u",
      agent_id: "2",
      conversation_id: "9223372036854775806",
      id_query: "abc",
    };
    expect(resetFilters(f, "target_user_id", "v")).toEqual({
      tenant_id: "t",
      target_user_id: "v",
      id_query: "",
    });
    expect(resetFilters(f, "agent_id", "3").conversation_id).toBeUndefined();
    expect(
      resetFilters(f, "conversation_id", f.conversation_id).conversation_id
    ).toBe(f.conversation_id);
  });

  it("evicts least recently used content and refuses oversized values", () => {
    const cache = new BodyCache(12);
    cache.set("a", "aaa");
    cache.set("b", "bbb");
    expect(cache.get("a")).toBe("aaa");
    cache.set("c", "ccc");
    expect(cache.get("b")).toBeUndefined();
    expect(cache.set("large", "x".repeat(13))).toBe(false);
    expect(cache.bytes).toBeLessThanOrEqual(12);
    cache.clear();
    expect(cache.bytes).toBe(0);
  });
});
