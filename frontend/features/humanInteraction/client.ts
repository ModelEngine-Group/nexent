import { fetchWithAuth, getAuthHeaders } from "@/lib/auth";
import { API_BASE_URL } from "@/services/api";

export interface HumanRequest {
  request_id: string;
  run_id: string;
  kind: "CLARIFICATION" | "ACTION_APPROVAL" | "USER_STEERING";
  status: string;
  version: number;
  digest: string;
  expires_at: string;
  payload: {
    question?: string;
    options?: string[];
    tool?: string;
    arguments?: Record<string, unknown>;
  };
}

export interface HumanRun {
  run_id: string;
  conversation_id: number;
  status: string;
  event_seq: number;
  pause_requested: boolean;
  requests: HumanRequest[];
}

const base = `${API_BASE_URL}/agent/human-interactions`;

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetchWithAuth(`${base}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(
      typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`
    );
  }
  return response.json();
}

export const humanInteractionClient = {
  capabilities: () =>
    request<{ enabled: boolean; accept_new_runs: boolean }>("/capabilities"),
  conversation: (id: number) => request<HumanRun | null>(`/conversation/${id}`),
  control: (id: string, action: "pause" | "terminate") =>
    request<HumanRun>(`/${id}/${action}`, {}),
  decide: (
    item: HumanRequest,
    decision: "answer" | "approve" | "reject" | "steer",
    text: string,
    key: string
  ) =>
    request(`/${item.run_id}/requests/${item.request_id}/decisions`, {
      version: item.version,
      digest: item.digest,
      idempotency_key: key,
      decision,
      text: text || null,
    }),
};
