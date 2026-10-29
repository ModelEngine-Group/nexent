// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import {
  guidePreferenceKey,
  isGuideDismissed,
  setGuideDismissed,
} from "@/lib/guidePreferences";
import {
  agentCreationGuideKey,
  hasCompletedAgentCreationGuide,
  completeAgentCreationGuide,
} from "@/lib/agentCreationGuide";

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});
it("persists both guides independently and supports reopening", () => {
  const key = guidePreferenceKey("tenant", "user");
  expect(isGuideDismissed(key, "agent-configuration")).toBe(false);
  setGuideDismissed(key, "agent-configuration", true);
  completeAgentCreationGuide(agentCreationGuideKey("tenant", "user"));
  expect(JSON.parse(localStorage.getItem(key)!)).toEqual({
    "agent-configuration": { dismissed: true },
    "agent-creation": { dismissed: true },
  });
  setGuideDismissed(key, "agent-configuration", false);
  expect(isGuideDismissed(key, "agent-configuration")).toBe(false);
  expect(
    hasCompletedAgentCreationGuide(agentCreationGuideKey("tenant", "user"))
  ).toBe(true);
});
it("migrates legacy completion and isolates users and tenants", () => {
  const legacy = agentCreationGuideKey("t/1", "u");
  localStorage.setItem(legacy, "1");
  expect(hasCompletedAgentCreationGuide(legacy)).toBe(true);
  expect(
    isGuideDismissed(guidePreferenceKey("other", "u"), "agent-creation")
  ).toBe(false);
  expect(
    isGuideDismissed(guidePreferenceKey("t/1", "other"), "agent-creation")
  ).toBe(false);
});
it("recovers from malformed storage and falls back when writes fail", () => {
  const key = guidePreferenceKey("broken", "user");
  localStorage.setItem(key, "invalid");
  expect(isGuideDismissed(key, "agent-configuration")).toBe(false);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("denied");
  });
  setGuideDismissed(key, "agent-configuration", true);
  expect(isGuideDismissed(key, "agent-configuration")).toBe(true);
});
