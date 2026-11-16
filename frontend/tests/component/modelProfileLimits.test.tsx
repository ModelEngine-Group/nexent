// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, expect, it } from "vitest";
import { profileOutputLimit } from "../../lib/modelProfileLimits";

describe("profile output cap display", () => {
  it("uses a known cap within the effective context window", () => {
    expect(
      profileOutputLimit({ output_limit: 384000, combined_window: 1000000 })
    ).toBe(384000);
    expect(
      profileOutputLimit(
        { output_limit: 384000, combined_window: 1000000 },
        200000
      )
    ).toBe(200000);
  });
  it("leaves unknown or invalid caps empty", () => {
    for (const context of [
      undefined,
      null,
      {},
      { output_limit: 0 },
      { output_limit: -1 },
      { output_limit: "8192" },
      { output_limit: NaN },
    ]) {
      expect(profileOutputLimit(context)).toBeUndefined();
    }
  });
});
