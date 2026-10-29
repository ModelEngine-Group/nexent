// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { describe, expect, it } from "vitest";
import { automaticModelId } from "@/lib/modelSelection";

describe("AC-FIX-03 automatic selection", () => {
  it("skips failed, unchecked and disabled models", () => {
    expect(
      automaticModelId([
        { id: "failed", connectStatus: "unavailable" },
        { id: "unchecked", connectStatus: "not_detected" },
        { id: "disabled", connectStatus: "available", disabled: true },
        { id: "healthy", connectStatus: "available" },
      ])
    ).toBe("healthy");
  });
  it("requires an explicit choice when every model is unverified", () => {
    expect(
      automaticModelId([{ id: "failed", connectStatus: "unavailable" }])
    ).toBeUndefined();
    expect(automaticModelId([])).toBeUndefined();
  });
  it("preserves legacy selector callers without status metadata", () => {
    expect(automaticModelId([{ id: "legacy" }])).toBe("legacy");
  });
});
