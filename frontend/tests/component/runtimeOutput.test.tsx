// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";
import { outputStatus } from "@/lib/nexentOutputStatus";

it.each(["running", "streaming"])(
  "restores %s from backend status",
  (status) => {
    expect(outputStatus(status)).toEqual({ type: "running" });
  }
);
it("restores backend terminal states without interpreting Core envelopes", () => {
  expect(outputStatus("completed")).toEqual({
    type: "complete",
    reason: "stop",
  });
  expect(outputStatus("failed", "failed")).toEqual({
    type: "incomplete",
    reason: "error",
    error: "failed",
  });
  expect(outputStatus("stopped")).toEqual({
    type: "incomplete",
    reason: "cancelled",
  });
  expect(outputStatus()).toBeUndefined();
});
