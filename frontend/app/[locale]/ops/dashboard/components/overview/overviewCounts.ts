// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import type { OperationsResource } from "@/types/operations";
import { resourceKey } from "../../useMonitoringDirectories";

export function countOverviewResources(resources: OperationsResource[]) {
  const identities = { agent: new Set<string>(), model: new Set<string>() };
  for (const { kind, tenant_id, id } of resources) {
    if (kind === "agent" || kind === "model") {
      identities[kind].add(resourceKey(tenant_id, id));
    }
  }
  return { agent: identities.agent.size, model: identities.model.size };
}
