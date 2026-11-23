// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, expect, it } from "vitest";
import en from "../../public/locales/en/common.json";
import zh from "../../public/locales/zh/common.json";

// The Agent Space page is reachable from the sidebar entry and from the Home
// quick action, while its heading is rendered from its own key. All three
// surfaces must share a single English name so the entry label never drifts
// away from the page title in that locale.
const englishAgentSpaceName = "Agent Space";

describe("Agent Space English naming", () => {
  it("keeps the sidebar entry, the Home quick action and the page title on one name", () => {
    expect(en["sidebar.agentSpace"]).toBe(englishAgentSpaceName);
    expect(en["agentRepository.page.title"]).toBe(englishAgentSpaceName);
    expect(en["sidebar.agentRepository"]).toBe(englishAgentSpaceName);
  });

  it("keeps the Chinese page title and sidebar entry unchanged", () => {
    expect(zh["agentRepository.page.title"]).toBe("Agent 仓库");
    expect(zh["sidebar.agentSpace"]).toBe("Agent 仓库");
  });
});
