// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, expect, it } from "vitest";

import {
  AGENT_DISPLAY_NAME_MAX_LENGTH,
  AGENT_NAME_MAX_LENGTH,
  isValidAgentName,
} from "@/lib/agentName";

describe("internal Agent identifier contract", () => {
  it.each(["agent_one", "_", "中文助手", "a".repeat(100), "𐐀_agent"])(
    "preserves existing legal identifier %s",
    (name) => expect(isValidAgentName(name)).toBe(true)
  );

  it.each([
    "class",
    "False",
    "None",
    "await",
    "9agent",
    "agent-one",
    "agent name",
    "agent\n",
    " agent",
    "",
    "a".repeat(101),
  ])("rejects invalid identifier %s", (name) =>
    expect(isValidAgentName(name)).toBe(false)
  );

  it("keeps variable and display length limits independent", () => {
    expect(AGENT_NAME_MAX_LENGTH).toBe(100);
    expect(AGENT_DISPLAY_NAME_MAX_LENGTH).toBe(60);
  });
});
