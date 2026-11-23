// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listGroups } from "@/services/groupService";
import {
  checkOperationsScope,
  listOperationsMcpTools,
  listOperationsResources,
} from "@/services/operationsService";
import { fetchSkillsList } from "@/services/skillService";
import { listTenants, type Tenant } from "@/services/tenantService";
import type { MonitoringTab } from "./monitoringFilters";

export function resourceKey(tenantId: string, id: number | string): string {
  return JSON.stringify([tenantId, id]);
}

export function useMonitoringDirectories({
  userId,
  userTenant,
  selectedTenant,
  canChooseTenant,
  canReadInventory,
  tab,
  selectedService,
}: {
  userId: string;
  userTenant: string;
  selectedTenant: string;
  canChooseTenant: boolean;
  canReadInventory: boolean;
  tab: MonitoringTab;
  selectedService?: string;
}) {
  const queryClient = useQueryClient();
  const queryKey = ["opsMonitoringDirectories", userId, userTenant] as const;
  const requestedTenant = canChooseTenant ? selectedTenant : userTenant;
  const scope = useQuery({
    queryKey: [...queryKey, "scope", requestedTenant],
    queryFn: () =>
      checkOperationsScope("dashboard", requestedTenant || undefined),
  });
  const tenant = scope.isSuccess ? scope.data.tenant_id : undefined;
  const tenants = useQuery({
    queryKey: [...queryKey, "tenants"],
    enabled: canChooseTenant,
    queryFn: async () => {
      const pageSize = 100;
      const choices: Tenant[] = [];
      let end = 1;
      for (let page = 1; page <= end; page += 1) {
        const result = await listTenants({ page, page_size: pageSize });
        choices.push(...result.data);
        if (page === 1) end = result.total_pages;
      }
      return choices;
    },
  });
  const groups = useQuery({
    queryKey: [...queryKey, "groups", tenant],
    enabled: tab !== "overview" && Boolean(tenant),
    queryFn: () => listGroups(tenant!),
  });
  const inventory = useQuery({
    queryKey: [...queryKey, "inventory", tenant],
    enabled:
      tenant !== undefined &&
      canReadInventory &&
      tab !== "overview" &&
      tab !== "skill",
    queryFn: ({ signal }) => listOperationsResources(tenant ?? null, signal),
  });
  const skills = useQuery({
    queryKey: [...queryKey, "skills", tenant],
    enabled: tab === "skill" && Boolean(tenant),
    queryFn: () => fetchSkillsList(tenant, "mount"),
  });

  const service =
    tab === "mcp" && canReadInventory
      ? inventory.data?.find(
          (item) =>
            item.kind === "mcp" &&
            resourceKey(item.tenant_id, item.id) === selectedService
        )
      : undefined;
  // The tool directory resolves tenant from the session, regardless of SU scope.
  const canReadTools = Boolean(service && service.tenant_id === userTenant);
  const tools = useQuery({
    queryKey: [...queryKey, "tools", service?.tenant_id, service?.id],
    enabled: canReadTools,
    queryFn: ({ signal }) => listOperationsMcpTools(service!.id, signal),
  });

  const fetching =
    scope.isFetching ||
    (canChooseTenant && tenants.isFetching) ||
    (tab !== "overview" && groups.isFetching) ||
    (tab === "skill"
      ? skills.isFetching
      : tab !== "overview" && inventory.isFetching) ||
    (canReadTools && tools.isFetching);

  return {
    tenant,
    scope,
    tenants,
    groups,
    inventory,
    skills,
    tools,
    canReadTools,
    fetching,
    refresh: () => queryClient.refetchQueries({ queryKey, type: "active" }),
  };
}
