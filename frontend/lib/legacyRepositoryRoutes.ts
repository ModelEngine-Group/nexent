// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { withBasePath } from "@/lib/basePath";
import type { ResourceType } from "@/types/resourceRepository";

/** Preserve feature-owned filters and detail IDs while retiring old tab names. */
export function buildLegacyRepositoryRedirect(
  locale: string,
  resourceType: ResourceType,
  search: string
): string | null {
  const params = new URLSearchParams(search);
  const legacyTab = params.get("tab");
  // Published-agent usage guides still need the personal management component.
  if (resourceType === "agent" && legacyTab === "mine") return null;
  params.delete("view");
  params.delete("resource_type");
  if (legacyTab === "review") {
    params.set("tab", "review");
    params.set("resource_type", resourceType);
  } else {
    params.set("tab", resourceType);
    params.set("view", legacyTab === "mine" ? "mine" : "repository");
  }
  return withBasePath(`/${locale}/resource-space?${params.toString()}`);
}
