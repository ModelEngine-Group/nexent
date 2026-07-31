import { getAuthHeaders } from "@/lib/auth";
import { API_ENDPOINTS, fetchWithErrorHandling } from "@/services/api";

export type MemoryScope = "tenant" | "user" | "agent";
export type MemoryType = "long_term" | "short_term";
export type MemoryStatus = "active" | "archived" | "disabled";

export interface MemoryRecord {
  memory_id: number;
  agent_id: string | null;
  agent_name: string | null;
  conversation_id: string | null;
  conversation_title: string | null;
  layer: MemoryScope;
  memory_type: MemoryType;
  status: MemoryStatus;
  content: string;
  create_time: string | null;
  embedding_compatible?: boolean;
}

export interface MemoryRecordInput {
  layer: MemoryScope;
  memory_type: MemoryType;
  content: string;
}

export interface MemoryRecordUpdate {
  content?: string;
  status?: MemoryStatus;
}

async function requestJson<T>(url: string, options: RequestInit): Promise<T> {
  const response = await fetchWithErrorHandling(url, options);
  return response.json() as Promise<T>;
}

export async function listMemoryRecords(
  layer: MemoryScope
): Promise<MemoryRecord[]> {
  const params = new URLSearchParams({
    layer,
    status: "",
    limit: "1000",
  });
  const result = await requestJson<{ items: MemoryRecord[] }>(
    `${API_ENDPOINTS.memory.records.list}?${params.toString()}`,
    { method: "GET", headers: getAuthHeaders() }
  );
  return result.items ?? [];
}

export async function createMemoryRecord(
  input: MemoryRecordInput
): Promise<void> {
  await requestJson(API_ENDPOINTS.memory.records.create, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(input),
  });
}

export async function updateMemoryRecord(
  memoryId: number,
  input: MemoryRecordUpdate
): Promise<void> {
  await requestJson(API_ENDPOINTS.memory.records.update(memoryId), {
    method: "PATCH",
    headers: getAuthHeaders(),
    body: JSON.stringify(input),
  });
}

export async function deleteMemoryRecord(memoryId: number): Promise<void> {
  await requestJson(API_ENDPOINTS.memory.records.delete(memoryId), {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
}
