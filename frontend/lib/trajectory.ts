// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type {
  DirectoryField,
  TrajectoryFilters,
  TrajectoryNode,
} from "@/types/trajectory";

export function invalidatesTrajectory(error: unknown): boolean {
  if (!error || typeof error !== "object" || !("code" in error)) return false;
  return [
    "snapshot_reset",
    "invalid_reference",
    "content_expired",
    "trajectory_expired",
    "trajectory_not_found",
    "trajectory_corrupt",
    "unauthenticated",
    "administrator_required",
    "401",
    "403",
    "404",
    "410",
  ].includes(String(error.code));
}

export function formatMetric(
  value: number | null | undefined,
  digits = 2
): string {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value.toLocaleString(undefined, { maximumFractionDigits: digits })
    : "—";
}

export function formatTraceTime(value: string | null | undefined): string {
  if (!value || !Number.isFinite(Date.parse(value))) return "—";
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function resetFilters(
  filters: TrajectoryFilters,
  field: DirectoryField,
  value?: string
): TrajectoryFilters {
  const order: DirectoryField[] = [
    "tenant_id",
    "target_user_id",
    "agent_id",
    "conversation_id",
  ];
  const next = { ...filters, [field]: value, id_query: "" };
  for (const child of order.slice(order.indexOf(field) + 1)) delete next[child];
  return next;
}

export function filterTree(
  nodes: TrajectoryNode[],
  text: string,
  kind: string,
  bodies?: ReadonlyMap<string, string>,
  bodyMatch?: (id: string, query: string) => boolean
): Set<string> {
  const query = text.trim().toLocaleLowerCase();
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const keep = new Set<string>();
  for (const node of nodes) {
    if (kind && kind !== node.kind) continue;
    const haystack = [
      node.name,
      node.input?.text,
      node.output?.text,
      bodies?.get(node.id),
    ]
      .join(" ")
      .toLocaleLowerCase();
    if (query && !haystack.includes(query) && !bodyMatch?.(node.id, query))
      continue;
    let current: TrajectoryNode | undefined = node;
    while (current && !keep.has(current.id)) {
      keep.add(current.id);
      current = current.parent_id ? byId.get(current.parent_id) : undefined;
    }
  }
  return keep;
}

/** An execution-scoped LRU. Account for both UTF-8 payload and JS string storage. */
export class BodyCache {
  private entries = new Map<string, { text: string; size: number }>();
  bytes = 0;
  constructor(readonly limit = 32 * 1024 * 1024) {}
  get(key: string): string | undefined {
    const value = this.entries.get(key);
    if (!value) return undefined;
    this.entries.delete(key);
    this.entries.set(key, value);
    return value.text;
  }
  set(key: string, text: string): boolean {
    const size = Math.max(
      text.length * 2,
      new TextEncoder().encode(text).length
    );
    if (size > this.limit) return false;
    const old = this.entries.get(key);
    if (old) {
      this.bytes -= old.size;
      this.entries.delete(key);
    }
    while (this.bytes + size > this.limit) {
      const key = this.entries.keys().next().value;
      if (key === undefined) break;
      this.bytes -= this.entries.get(key)!.size;
      this.entries.delete(key);
    }
    this.entries.set(key, { text, size });
    this.bytes += size;
    return true;
  }
  clear(): void {
    this.entries.clear();
    this.bytes = 0;
  }
  matches(prefix: string, query: string): boolean {
    for (const [key, value] of this.entries)
      if (
        key.startsWith(prefix) &&
        value.text.toLocaleLowerCase().includes(query)
      )
        return true;
    return false;
  }
}

export function recordKey(row: {
  tenant_id: string;
  user_id: string;
  conversation_id: string;
  trajectory_id: string | null;
}): string {
  return JSON.stringify([
    row.tenant_id,
    row.user_id,
    row.conversation_id,
    row.trajectory_id,
  ]);
}
