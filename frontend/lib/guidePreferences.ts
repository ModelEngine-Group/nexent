// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

export type GuideId = "agent-configuration" | "agent-creation";
type Preferences = Partial<Record<GuideId, { dismissed: boolean }>>;
const memory = new Map<
  string,
  { preferences: Preferences; baseline: string | null }
>();
export const LEGACY_GUIDE_PREFIX = "nexent.agent.creation-guide.v1/";

export function sharedGuideKey(legacyKey: string) {
  if (!legacyKey.startsWith(LEGACY_GUIDE_PREFIX)) {
    throw new Error("Unsupported legacy guide preference key");
  }
  return `nexent.guide-preferences.v1/${legacyKey.slice(LEGACY_GUIDE_PREFIX.length)}`;
}

export function guidePreferenceKey(tenantId: string, userId: string) {
  return `nexent.guide-preferences.v1/${encodeURIComponent(tenantId)}/${encodeURIComponent(userId)}`;
}

function read(key: string): Preferences {
  try {
    const raw = window.localStorage.getItem(key);
    const fallback = memory.get(key);
    if (fallback && raw === fallback.baseline) return fallback.preferences;
    memory.delete(key);
    const value: unknown = JSON.parse(raw ?? "{}");
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return value as Preferences;
    }
  } catch {
    // Unavailable or invalid browser storage must not block the UI.
  }
  return memory.get(key)?.preferences ?? {};
}

export function isGuideDismissed(key: string, id: GuideId, legacyKey?: string) {
  const preference = read(key)[id];
  if (typeof preference?.dismissed === "boolean") return preference.dismissed;
  try {
    if (legacyKey && window.localStorage.getItem(legacyKey) === "1") {
      if (setGuideDismissed(key, id, true)) {
        window.localStorage.removeItem(legacyKey);
      }
      return true;
    }
  } catch {
    // Legacy preferences are optional when storage is denied.
  }
  return false;
}

export function setGuideDismissed(
  key: string,
  id: GuideId,
  dismissed: boolean
) {
  const preferences = { ...read(key), [id]: { dismissed } };
  let baseline: string | null = null;
  try {
    baseline = window.localStorage.getItem(key);
  } catch {
    // Reads may be denied along with writes.
  }
  let persisted = false;
  try {
    window.localStorage.setItem(key, JSON.stringify(preferences));
    persisted = true;
    memory.delete(key);
  } catch {
    memory.set(key, { preferences, baseline });
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("nexent-guide-preferences"));
  }
  return persisted;
}
