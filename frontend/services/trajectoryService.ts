// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { API_ENDPOINTS, fetchWithErrorHandling } from "@/services/api";
import type {
  ImportedTrajectory,
  SavedTrajectory,
  SavedTrajectoriesPage,
  CleanupResult,
  CleanupSchedule,
  ConversationPage,
  ContentChunk,
  FacetPage,
  RecordsPage,
  RecordsRequest,
  SnapshotPage,
  TrajectoryFacet,
  TrajectoryFilters,
  TrajectoryRecord,
} from "@/types/trajectory";

function queryUrl(endpoint: string, params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "")
      search.set(key, String(value));
  }
  return `${endpoint}?${search}`;
}

async function read<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetchWithErrorHandling(url, {
    signal,
    cache: "no-store",
  });
  return (await response.json()).data as T;
}

export const trajectoryService = {
  savedImports: (page: number, pageSize: number, signal?: AbortSignal) =>
    read<SavedTrajectoriesPage>(
      queryUrl(API_ENDPOINTS.trajectory.imports, { page, page_size: pageSize }),
      signal
    ),
  savedImport: (id: string, signal?: AbortSignal) =>
    read<SavedTrajectory>(API_ENDPOINTS.trajectory.savedImport(id), signal),
  async saveImport(file: File, signal?: AbortSignal): Promise<SavedTrajectory> {
    const body = new FormData();
    body.append("file", file);
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.trajectory.imports,
      {
        method: "POST",
        body,
        signal,
        cache: "no-store",
      }
    );
    return (await response.json()).data as SavedTrajectory;
  },
  async deleteImport(id: string): Promise<{ deleted: boolean }> {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.trajectory.savedImport(id),
      {
        method: "DELETE",
        cache: "no-store",
      }
    );
    return (await response.json()).data as { deleted: boolean };
  },
  async exportArchive(
    row: TrajectoryRecord,
    signal?: AbortSignal
  ): Promise<Blob> {
    const response = await fetchWithErrorHandling(
      queryUrl(API_ENDPOINTS.trajectory.exportArchive(row.conversation_id), {
        tenant_id: row.tenant_id,
        target_user_id: row.user_id,
      }),
      { method: "POST", signal, cache: "no-store" }
    );
    return response.blob();
  },
  async importArchive(
    file: File,
    signal?: AbortSignal
  ): Promise<ImportedTrajectory> {
    const body = new FormData();
    body.append("file", file);
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.trajectory.importArchive,
      {
        method: "POST",
        body,
        signal,
        cache: "no-store",
      }
    );
    return (await response.json()).data as ImportedTrajectory;
  },
  cleanupSchedule: (
    tenantId?: string,
    signal?: AbortSignal,
    allTenants = false
  ) =>
    read<CleanupSchedule>(
      queryUrl(API_ENDPOINTS.trajectory.cleanupSchedule, {
        ...(allTenants ? { all_tenants: true } : { tenant_id: tenantId }),
      }),
      signal
    ),
  async saveCleanupSchedule(
    tenantId: string | undefined,
    policy: Pick<CleanupSchedule, "enabled" | "retention_days">,
    signal?: AbortSignal,
    allTenants = false
  ): Promise<CleanupSchedule> {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.trajectory.cleanupSchedule,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...(allTenants ? { all_tenants: true } : { tenant_id: tenantId }),
          enabled: policy.enabled,
          retention_days: policy.retention_days,
        }),
        signal,
        cache: "no-store",
      }
    );
    return (await response.json()).data as CleanupSchedule;
  },
  records: (params: RecordsRequest, signal?: AbortSignal) =>
    read<RecordsPage>(
      queryUrl(API_ENDPOINTS.trajectory.records, params),
      signal
    ),
  facets: (
    facet: TrajectoryFacet,
    filters: TrajectoryFilters,
    search: string,
    cursor?: string,
    signal?: AbortSignal
  ) =>
    read<FacetPage>(
      queryUrl(API_ENDPOINTS.trajectory.records, {
        ...filters,
        facet,
        search,
        cursor,
        limit: 20,
      }),
      signal
    ),
  conversation: (
    row: TrajectoryRecord,
    params: {
      cursor?: string;
      snapshot_id?: string;
      query_id?: string;
      limit?: number;
    },
    signal?: AbortSignal
  ) =>
    read<ConversationPage>(
      queryUrl(API_ENDPOINTS.trajectory.conversation(row.conversation_id), {
        tenant_id: row.tenant_id,
        target_user_id: row.user_id,
        ...params,
      }),
      signal
    ),
  snapshot: (
    row: TrajectoryRecord,
    params: { snapshot_id?: string; cursor?: string; node_id?: string },
    signal?: AbortSignal
  ) =>
    read<SnapshotPage>(
      queryUrl(API_ENDPOINTS.trajectory.snapshot(row.conversation_id), {
        tenant_id: row.tenant_id,
        target_user_id: row.user_id,
        trajectory_id: row.trajectory_id,
        limit: 500,
        ...params,
      }),
      signal
    ),
  content: (
    conversationId: string,
    contentId: string,
    offset: number,
    signal?: AbortSignal
  ) =>
    read<ContentChunk>(
      queryUrl(API_ENDPOINTS.trajectory.content(conversationId, contentId), {
        offset,
        limit: 65536,
      }),
      signal
    ),
  async cleanup(
    beforeDays: number,
    cursor?: string,
    signal?: AbortSignal,
    tenantId?: string
  ): Promise<CleanupResult> {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.trajectory.cleanup,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          before_days: beforeDays,
          ...(tenantId ? { tenant_id: tenantId } : {}),
          ...(cursor ? { cursor } : {}),
        }),
        signal,
        cache: "no-store",
      }
    );
    return (await response.json()).data as CleanupResult;
  },
};
