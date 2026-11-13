// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { API_ENDPOINTS, fetchWithErrorHandling } from "@/services/api";
import type {
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
  cleanupSchedule: (tenantId: string, signal?: AbortSignal) =>
    read<CleanupSchedule>(
      queryUrl(API_ENDPOINTS.trajectory.cleanupSchedule, {
        tenant_id: tenantId,
      }),
      signal
    ),
  async saveCleanupSchedule(
    tenantId: string,
    intervalSeconds: number,
    signal?: AbortSignal
  ): Promise<CleanupSchedule> {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.trajectory.cleanupSchedule,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId,
          interval_seconds: intervalSeconds,
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
        limit: 1048576,
      }),
      signal
    ),
  async cleanup(
    beforeDays: number,
    cursor?: string,
    signal?: AbortSignal
  ): Promise<CleanupResult> {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.trajectory.cleanup,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          before_days: beforeDays,
          ...(cursor ? { cursor } : {}),
        }),
        signal,
        cache: "no-store",
      }
    );
    return (await response.json()).data as CleanupResult;
  },
};
