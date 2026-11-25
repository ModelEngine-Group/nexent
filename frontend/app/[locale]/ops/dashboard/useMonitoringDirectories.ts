// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getMcpMonitoringCatalog } from "@/services/mcpMonitoringService";
import type { McpCatalogService } from "@/types/mcpMonitoring";
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

export function mcpServiceKey(service: McpCatalogService): string {
  return service.service_id === null ? "builtin" : String(service.service_id);
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
      tab !== "skill" &&
      (tab !== "mcp" || (tenant === null && Boolean(userTenant))),
    queryFn: ({ signal }) => listOperationsResources(tenant ?? null, signal),
  });
  const skills = useQuery({
    queryKey: [...queryKey, "skills", tenant],
    enabled: tab === "skill" && Boolean(tenant),
    queryFn: () => fetchSkillsList(tenant, "mount"),
  });

  const mcpCatalog = useQuery({
    queryKey: [...queryKey, "mcpCatalog", tenant],
    enabled: tab === "mcp" && tenant !== undefined,
    queryFn: ({ signal }) => getMcpMonitoringCatalog(tenant ?? null, signal),
  });
  // MCP catalog IDs are global; inventory supplies tenant labels for a platform scope.
  const mcpServiceTenant = (service: McpCatalogService) =>
    tenant ??
    inventory.data?.find(
      (item) => item.kind === "mcp" && item.id === service.service_id
    )?.tenant_id;
  const service =
    tab === "mcp"
      ? mcpCatalog.data?.find((item) => mcpServiceKey(item) === selectedService)
      : undefined;
  const serviceId = service?.service_id;
  // The tool directory requires a registered service in the session tenant.
  const canReadTools =
    service !== undefined &&
    service.service_id !== null &&
    Boolean(userTenant) &&
    mcpServiceTenant(service) === userTenant;
  const tools = useQuery({
    queryKey: [...queryKey, "tools", serviceId],
    enabled: canReadTools,
    queryFn: ({ signal }) => listOperationsMcpTools(serviceId!, signal),
  });

  const fetching =
    scope.isFetching ||
    (canChooseTenant && tenants.isFetching) ||
    (tab !== "overview" && groups.isFetching) ||
    (tab === "skill" ? skills.isFetching : inventory.isFetching) ||
    mcpCatalog.isFetching ||
    (canReadTools && tools.isFetching);

  return {
    tenant,
    scope,
    tenants,
    groups,
    inventory,
    skills,
    mcpCatalog,
    mcpService: service,
    mcpServiceTenant,
    tools,
    canReadTools,
    fetching,
    refresh: () => queryClient.refetchQueries({ queryKey, type: "active" }),
  };
}
