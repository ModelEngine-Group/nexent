// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { withBasePath } from "@/lib/basePath";

/** Preserve the /agent-repository alias filters and detail IDs after the route merge. */
export function buildLegacyRepositoryRedirect(locale: string, search: string): string {
  const params = new URLSearchParams(search);
  const legacyTab = params.get("tab");
  // The unified repository rejects the onboarding marker, and the retired
  // personal agent view no longer consumes it.
  params.delete("onboarding");
  params.delete("view");
  params.delete("resource_type");
  if (legacyTab === "review") {
    params.set("tab", "review");
    params.set("resource_type", "agent");
  } else {
    params.set("tab", "agent");
    params.set("view", "repository");
  }
  return withBasePath(`/${locale}/resource-space?${params.toString()}`);
}
