// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";
import { resolveReasoningAvailability } from "@/lib/modelReasoning";
import type { ReasoningCapability } from "@/types/modelConfig";

const toggle: ReasoningCapability = {
  status: "supported",
  control: "toggle",
  levels: [],
  source: "catalog",
};

it.each(["unknown", "unsupported"] as const)(
  "%s status overrides stale toggle and value controls without mutating metadata",
  (status) => {
    const capability = { ...toggle, status };
    const before = structuredClone(capability);
    expect(resolveReasoningAvailability(capability, true)).toBe(status);
    expect(resolveReasoningAvailability(capability, false)).toBe(status);
    expect(capability).toEqual(before);
  }
);

it("requires a usable control but preserves explicit legacy effort/budget options", () => {
  expect(resolveReasoningAvailability(undefined)).toBe("unknown");
  expect(resolveReasoningAvailability(undefined, true)).toBe("supported");
  expect(resolveReasoningAvailability(toggle)).toBe("supported");
  const noControl = { ...toggle, control: "effort" as const };
  expect(resolveReasoningAvailability(noControl)).toBe("unknown");
  expect(resolveReasoningAvailability(noControl, true)).toBe("supported");
  expect(
    resolveReasoningAvailability({
      ...noControl,
      controls: [{ type: "toggle" }],
    })
  ).toBe("supported");
});
