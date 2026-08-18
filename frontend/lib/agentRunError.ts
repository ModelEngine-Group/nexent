export class AgentRunError extends Error {
  readonly status: number;
  readonly code: string | number;

  constructor(status: number, code: string | number, message: string) {
    super(message);
    this.name = "AgentRunError";
    this.status = status;
    this.code = code;
  }
}

type ErrorRecord = Record<string, unknown>;

function asRecord(value: unknown): ErrorRecord | undefined {
  return value !== null && typeof value === "object"
    ? (value as ErrorRecord)
    : undefined;
}

export function buildAgentRunError(
  status: number,
  statusText: string,
  payload: unknown
): AgentRunError {
  const envelope = asRecord(payload);
  const detail = asRecord(envelope?.detail) ?? envelope;
  const code =
    (detail?.code as string | number | undefined) ??
    (envelope?.code as string | number | undefined) ??
    status;

  const detailMessage = detail?.message ?? envelope?.message;
  const plainDetail =
    typeof envelope?.detail === "string" ? envelope.detail : undefined;
  const message =
    (typeof detailMessage === "string" && detailMessage) ||
    plainDetail ||
    `HTTP ${status}: ${statusText || "Request failed"}`;

  return new AgentRunError(status, code, message);
}
