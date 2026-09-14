import { fetchWithAuth, getAuthHeaders } from "@/lib/auth";
import { API_BASE_URL } from "@/services/api";
import type {
  HumanClarificationAnswer,
  HumanClarificationQuestion,
} from "./clarification";

export interface HumanRequest {
  request_id: string;
  run_id: string;
  kind: "CLARIFICATION" | "ACTION_APPROVAL" | "USER_STEERING";
  status: string;
  version: number;
  digest: string;
  expires_at: string;
  payload: {
    schema_version?: number;
    questions?: HumanClarificationQuestion[];
    question?: string;
    options?: string[];
    allow_other?: boolean;
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

export type HumanDecision = "answer" | "approve" | "reject" | "steer";

const base = `${API_BASE_URL}/agent/human-interactions`;

export class HumanInteractionHttpError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
  }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetchWithAuth(`${base}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new HumanInteractionHttpError(
      typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`,
      response.status
    );
  }
  return response.json();
}

export const humanInteractionClient = {
  capabilities: () =>
    request<{
      enabled: boolean;
      accept_new_runs: boolean;
      live_resume: boolean;
      tool_approval_enabled: boolean;
    }>("/capabilities"),
  conversation: (id: number) => request<HumanRun | null>(`/conversation/${id}`),
  control: (id: string, action: "pause" | "terminate") =>
    request<HumanRun>(`/${id}/${action}`, {}),
  steer: (runId: string, messageId: string, text: string) =>
    request<{ accepted: boolean }>(`/${runId}/steer`, {
      message_id: messageId,
      text,
    }),
  decide: (
    item: HumanRequest,
    decision: HumanDecision,
    response: string | HumanClarificationAnswer[],
    key: string
  ) =>
    request(`/${item.run_id}/requests/${item.request_id}/decisions`, {
      version: item.version,
      digest: item.digest,
      idempotency_key: key,
      decision,
      ...(typeof response === "string"
        ? { text: response || null }
        : { answers: response }),
    }),
};
