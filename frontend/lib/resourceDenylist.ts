// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { DenylistItem, DenylistScope } from "@/types/resourceDenylist";

/** Keep the overview and drawer counts aligned with displayed exclusion rules. */
export function denylistSelectedGroups(
  scope: DenylistScope,
  items: DenylistItem[],
  selected: ReadonlySet<string>
) {
  const unique = [...new Map(items.map((item) => [item.key, item])).values()];
  const byKey = new Map(unique.map((item) => [item.key, item]));
  const isGlobal = (item: DenylistItem) =>
    Boolean(
      item.global_blocked ||
      (item.parent_key && byKey.get(item.parent_key)?.global_blocked)
    );
  return {
    global:
      scope === "tenant"
        ? unique.filter(
            (item) =>
              isGlobal(item) &&
              !(item.parent_key && byKey.get(item.parent_key)?.global_blocked)
          )
        : [],
    current: unique.filter(
      (item) =>
        selected.has(item.key) && (scope === "global" || !isGlobal(item))
    ),
  };
}

export function denylistResourceKind(
  item: DenylistItem
): "local" | "mcpService" | "mcpTool" | "skill" {
  if (item.resource_type === "skill") return "skill";
  if (item.resource_type === "mcp") return "mcpService";
  const remote = item.source
    ? item.source === "mcp"
    : Boolean(item.parent_key || item.service);
  return remote ? "mcpTool" : "local";
}
