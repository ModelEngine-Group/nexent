// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Human-readable name for an AIDP relation target. */
export const aidpRelationName = (
  value: unknown,
  fallback = "—"
): string => {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return String(
      record.display_name ??
        record.displayName ??
        record.api_name ??
        record.name ??
        record.id ??
        fallback
    );
  }
  return fallback;
};

/** AIDP relations and first-class entities are addressed by numeric id. */
export const aidpRelationId = (value: unknown): string => {
  if (typeof value === "string" || typeof value === "number")
    return String(value);
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return String(record.entity_id ?? record.id ?? "");
  }
  return "";
};
