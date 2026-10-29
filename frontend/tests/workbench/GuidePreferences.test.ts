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

it("invalidates failed-write memory when persistent storage changes", () => {
  const key = guidePreferenceKey("recovery", "user");
  localStorage.setItem(key, "{}");
  const write = vi
    .spyOn(Storage.prototype, "setItem")
    .mockImplementation(() => {
      throw new Error("quota");
    });
  setGuideDismissed(key, "agent-configuration", true);
  expect(isGuideDismissed(key, "agent-configuration")).toBe(true);
  setGuideDismissed(key, "agent-configuration", false);
  expect(isGuideDismissed(key, "agent-configuration")).toBe(false);
  setGuideDismissed(key, "agent-configuration", true);
  write.mockRestore();
  localStorage.removeItem(key);
  expect(isGuideDismissed(key, "agent-configuration")).toBe(false);
});
it("removes legacy data only after a successful migration", () => {
  const legacy = agentCreationGuideKey("migration", "user");
  localStorage.setItem(legacy, "1");
  const write = vi
    .spyOn(Storage.prototype, "setItem")
    .mockImplementation(() => {
      throw new Error("quota");
    });
  expect(hasCompletedAgentCreationGuide(legacy)).toBe(true);
  expect(localStorage.getItem(legacy)).toBe("1");
  write.mockRestore();
  const other = agentCreationGuideKey("migration", "other");
  localStorage.setItem(other, "1");
  expect(hasCompletedAgentCreationGuide(other)).toBe(true);
  expect(localStorage.getItem(other)).toBeNull();
});
it("rejects unsupported legacy key versions", () => {
  expect(() =>
    hasCompletedAgentCreationGuide("nexent.agent.creation-guide.v2/t/u")
  ).toThrow("Unsupported legacy");
});
