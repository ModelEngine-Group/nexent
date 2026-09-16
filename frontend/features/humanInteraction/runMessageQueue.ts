export interface QueuedRunMessage {
  id: string;
  text: string;
  runId: string | null;
  previousRunId: string | null;
  durable: boolean;
  status: "queued" | "editing" | "delivering" | "error" | "uncertain";
  error?: string;
}

export interface RunMessageState {
  used: boolean;
  entry: QueuedRunMessage | null;
}

export const EMPTY_RUN_MESSAGE: RunMessageState = { used: false, entry: null };

export type RunMessageAction =
  | { type: "enqueue"; entry: QueuedRunMessage }
  | { type: "bind"; runId: string }
  | { type: "edit" }
  | { type: "save"; text: string }
  | { type: "cancel-edit" }
  | { type: "delete" }
  | { type: "deliver" }
  | { type: "guided"; messageId: string }
  | { type: "sent" }
  | { type: "error"; error: string; uncertain?: boolean; messageId?: string }
  | { type: "idle" };

export function reduceRunMessage(
  state: RunMessageState,
  action: RunMessageAction
): RunMessageState {
  const entry = state.entry;
  switch (action.type) {
    case "enqueue":
      return state.used || entry ? state : { used: true, entry: action.entry };
    case "bind":
      return entry && !entry.runId && action.runId !== entry.previousRunId
        ? { ...state, entry: { ...entry, runId: action.runId } }
        : state;
    case "edit":
      return entry && ["queued", "error"].includes(entry.status)
        ? { ...state, entry: { ...entry, status: "editing" } }
        : state;
    case "save":
      return entry?.status === "editing" && action.text.trim()
        ? {
            ...state,
            entry: {
              ...entry,
              text: action.text.trim(),
              status: "queued",
              error: undefined,
            },
          }
        : state;
    case "cancel-edit":
      return entry?.status === "editing"
        ? { ...state, entry: { ...entry, status: "queued" } }
        : state;
    case "delete":
      return entry && !["delivering", "uncertain"].includes(entry.status)
        ? { ...state, entry: null }
        : state;
    case "deliver":
      return entry && ["queued", "error", "uncertain"].includes(entry.status)
        ? {
            ...state,
            entry: { ...entry, status: "delivering", error: undefined },
          }
        : state;
    case "guided":
      return entry?.id === action.messageId && entry.status === "delivering"
        ? EMPTY_RUN_MESSAGE
        : state;
    case "sent":
      return entry?.status === "delivering" ? EMPTY_RUN_MESSAGE : state;
    case "error":
      return entry && (!action.messageId || entry.id === action.messageId)
        ? {
            ...state,
            entry: {
              ...entry,
              status: action.uncertain ? "uncertain" : "error",
              error: action.error,
            },
          }
        : state;
    case "idle":
      return !entry ? EMPTY_RUN_MESSAGE : state;
  }
}

export function canAutoSendQueuedMessage(
  entry: QueuedRunMessage | null,
  run: { run_id: string; status: string } | null,
  streaming: boolean,
  streamCompleted: boolean
): boolean {
  if (!entry || entry.status !== "queued" || streaming) return false;
  if (!entry.durable) return streamCompleted;
  return Boolean(
    entry.runId && run?.run_id === entry.runId && run.status === "COMPLETED"
  );
}
