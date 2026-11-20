// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  RESOURCE_REPOSITORY_PERMISSION_ROUTE,
  RESOURCE_REPOSITORY_TABS,
  RESOURCE_TYPES,
} from "@/const/resourceRepository";
import { withBasePath } from "@/lib/basePath";
import type {
  ResourceRepositoryParseResult,
  ResourceRepositoryTarget,
  ResourceRepositoryTab,
  ResourceRepositoryView,
  ResourceType,
} from "@/types/resourceRepository";

/** Normalize legacy safe integers without losing BIGINT precision. */
export function normalizeRepositoryId(value: unknown): string | null {
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value) || value <= 0) return null;
    value = String(value);
  }
  if (typeof value !== "string" || !/^[1-9][0-9]{0,18}$/.test(value)) {
    return null;
  }
  return BigInt(value) <= BigInt("9223372036854775807") ? value : null;
}

const idParameters = {
  repository_id: "repositoryId",
  review_id: "reviewId",
  agent_id: "agentId",
  skill_id: "skillId",
  source_mcp_id: "sourceMcpId",
} as const;

/** Parse only supported navigation fields; list filters remain feature-owned. */
export function parseResourceRepositoryTarget(
  params: Pick<URLSearchParams, "get" | "getAll">
): ResourceRepositoryParseResult {
  const keys = [
    "tab",
    "view",
    "resource_type",
    "onboarding",
    ...Object.keys(idParameters),
  ];
  if (keys.some((key) => params.getAll(key).length > 1)) {
    return { valid: false, error: "invalid_parameter" };
  }
  const tab = params.get("tab") ?? "agent";
  const view = params.get("view");
  const resourceType = params.get("resource_type");
  if (
    !RESOURCE_REPOSITORY_TABS.includes(tab as ResourceRepositoryTab) ||
    (view !== null && view !== "repository" && view !== "mine") ||
    (tab === "agent" && view === "mine") ||
    (resourceType !== null &&
      !RESOURCE_TYPES.includes(resourceType as ResourceType))
  ) {
    return { valid: false, error: "invalid_parameter" };
  }
  const target: ResourceRepositoryTarget = {
    tab: tab as ResourceRepositoryTab,
  };
  if (view) target.view = view as ResourceRepositoryView;
  if (resourceType) target.resourceType = resourceType as ResourceType;
  for (const [parameter, field] of Object.entries(idParameters)) {
    const value = params.get(parameter);
    if (value === null) continue;
    const id = normalizeRepositoryId(value);
    if (!id) return { valid: false, error: "invalid_parameter" };
    target[field as (typeof idParameters)[keyof typeof idParameters]] = id;
  }
  const effectiveType = tab === "review" ? resourceType : tab;
  if (
    (target.reviewId && target.repositoryId) ||
    (target.reviewId && tab !== "review") ||
    (tab !== "review" && resourceType !== null && resourceType !== tab) ||
    (tab === "review" && target.repositoryId && !resourceType) ||
    (target.agentId && effectiveType !== "agent") ||
    (target.skillId && effectiveType !== "skill") ||
    (target.sourceMcpId && effectiveType !== "mcp")
  ) {
    return { valid: false, error: "conflicting_target" };
  }
  if (params.get("onboarding") !== null) {
    return { valid: false, error: "conflicting_target" };
  }
  return { valid: true, target };
}

/** Build the destination href separately from the canonical permission route. */
export function buildResourceRepositoryHref(
  locale: string,
  target: ResourceRepositoryTarget
): string {
  if (!/^[a-z]{2}(?:-[A-Za-z]{2,4})?$/.test(locale)) {
    throw new Error("Invalid locale");
  }
  const params = new URLSearchParams({ tab: target.tab });
  if (target.view) params.set("view", target.view);
  if (target.resourceType) params.set("resource_type", target.resourceType);
  for (const [parameter, field] of Object.entries(idParameters)) {
    const value =
      target[field as (typeof idParameters)[keyof typeof idParameters]];
    if (value !== undefined) params.set(parameter, value);
  }
  if (target.onboarding !== undefined)
    params.set("onboarding", target.onboarding);
  if (!parseResourceRepositoryTarget(params).valid) {
    throw new Error("Invalid resource repository target");
  }
  return withBasePath(
    `/${locale}${RESOURCE_REPOSITORY_PERMISSION_ROUTE}?${params.toString()}`
  );
}
