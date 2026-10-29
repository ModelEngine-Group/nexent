// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export type GuideId = "agent-configuration" | "agent-creation";
type Preferences = Partial<Record<GuideId, { dismissed: boolean }>>;
const memory = new Map<string, Preferences>();

export function guidePreferenceKey(tenantId: string, userId: string) {
  return `nexent.guide-preferences.v1/${encodeURIComponent(tenantId)}/${encodeURIComponent(userId)}`;
}

function read(key: string): Preferences {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(key) ?? "{}");
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return { ...value, ...memory.get(key) };
    }
  } catch {
    // Unavailable or invalid browser storage must not block the UI.
  }
  return memory.get(key) ?? {};
}

export function isGuideDismissed(key: string, id: GuideId, legacyKey?: string) {
  const preference = read(key)[id];
  if (typeof preference?.dismissed === "boolean") return preference.dismissed;
  try {
    if (legacyKey && window.localStorage.getItem(legacyKey) === "1") {
      setGuideDismissed(key, id, true);
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
  try {
    window.localStorage.setItem(key, JSON.stringify(preferences));
    memory.delete(key);
  } catch {
    memory.set(key, preferences);
  }
  window.dispatchEvent(new Event("nexent-guide-preferences"));
}
