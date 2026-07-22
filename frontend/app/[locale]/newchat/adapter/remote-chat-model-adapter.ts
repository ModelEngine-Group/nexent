"use client";

import type {
  ChatModelAdapter,
  ChatModelRunOptions,
  ChatModelRunResult,
  CompleteAttachment,
} from "@assistant-ui/react";
import type { ThreadMessage } from "@assistant-ui/react";

import { API_ENDPOINTS } from "@/services/api";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";

// Backend SSE chunk format
interface SseChunk {
  type: string;
  content: any;
  unit_index?: number;
  role?: string;
  tool_name?: string;
  tool_arguments?: string | Record<string, unknown>;
}

// assistant-ui valid part types referenced by this adapter
type AssistantPartType = "text" | "reasoning" | "tool-call" | "source";

export interface VerificationPresentation {
  phase: string;
  event: string;
  severity: string;
  score?: number;
  message: string;
  passed?: boolean;
}

/**
 * Converts the backend verification JSON envelope into display data. The
 * backend intentionally serializes this payload so it can also be persisted;
 * showing that transport JSON directly in chat is never useful to the user.
 */
export function parseVerificationPresentation(
  content: unknown
): VerificationPresentation {
  let payload: Record<string, unknown> = {};
  if (typeof content === "string") {
    try {
      const parsed = JSON.parse(content) as unknown;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        payload = parsed as Record<string, unknown>;
      } else {
        return {
          phase: "start",
          event: "verification",
          severity: "info",
          message: content,
        };
      }
    } catch {
      return {
        phase: "start",
        event: "verification",
        severity: "info",
        message: content,
      };
    }
  } else if (
    content &&
    typeof content === "object" &&
    !Array.isArray(content)
  ) {
    payload = content as Record<string, unknown>;
  }

  const phase = typeof payload.phase === "string" ? payload.phase : "start";
  const messageCandidates = [
    payload.message,
    payload.user_visible_note,
    payload.repair_instruction,
  ];
  const message =
    messageCandidates.find(
      (candidate): candidate is string =>
        typeof candidate === "string" && candidate.trim().length > 0
    ) ?? (phase === "final_pass" ? "最终自检通过" : "正在进行自检");

  return {
    phase,
    event: typeof payload.event === "string" ? payload.event : "verification",
    severity: typeof payload.severity === "string" ? payload.severity : "info",
    score: typeof payload.score === "number" ? payload.score : undefined,
    message,
    passed: typeof payload.passed === "boolean" ? payload.passed : undefined,
  };
}

export function buildVerificationPart(content: unknown) {
  const verification = parseVerificationPresentation(content);
  return {
    type: "text" as const,
    text: verification.message,
    isVerification: true,
    verification,
  };
}

// Per-step token count data (parsed from the backend `token_count` chunk).
// Exported so `conversation-thread-list-adapter` can build the same shape from
// persisted `token_count` units when restoring a historical conversation, and
// `token-usage.tsx` can consume it via message metadata.
export interface StepTokenCount {
  stepNumber: number;
  duration: number;
  stepInputTokens: number;
  stepOutputTokens: number;
  totalOutputTokens: number;
  estimatedContextTokens: number;
  tokenThreshold: number | null;
}

// Accumulated total duration across all steps
let accumulatedDuration = 0;

/**
 * Parses a backend `token_count` payload into a `StepTokenCount` entry.
 * Returns null when the payload is malformed so callers can skip silently.
 */
export function parseStepTokenCount(content: string): StepTokenCount | null {
  try {
    const data = JSON.parse(content) as {
      step_number?: number;
      duration?: number;
      step_input_tokens?: number;
      step_output_tokens?: number;
      total_output_tokens?: number;
      estimated_context_tokens?: number;
      token_threshold?: number | null;
    };
    return {
      stepNumber: data.step_number ?? 0,
      duration: data.duration ?? 0,
      stepInputTokens: data.step_input_tokens ?? 0,
      stepOutputTokens: data.step_output_tokens ?? 0,
      totalOutputTokens: data.total_output_tokens ?? 0,
      estimatedContextTokens: data.estimated_context_tokens ?? 0,
      tokenThreshold: data.token_threshold ?? null,
    };
  } catch {
    return null;
  }
}

// Extended reasoning part with status for grouping support
interface ReasoningPart {
  type: "reasoning";
  text: string;
  status: { type: "running" | "done" };
}

/**
 * Creates a reasoning part with status for proper grouping by assistant-ui.
 */
function makeReasoningPart(text: string, isRunning: boolean): ReasoningPart {
  return {
    type: "reasoning",
    text,
    status: { type: isRunning ? "running" : "done" },
  };
}

/**
 * Metadata carried on attachments by `attachment-adapter.ts` after a successful
 * MinIO upload. Matches the shape needed for `minio_files` in the agent run
 * payload (see `MinioFileItem` in `types/chat.ts`).
 */
interface UploadedAttachmentMeta {
  object_name?: string;
  url?: string;
  presigned_url?: string;
  type?: string;
  size?: number;
}

type MinioFilePayload = UploadedAttachmentMeta & {
  name: string;
  object_name: string;
  type: string;
  size: number;
  url: string;
  presigned_url?: string;
};

interface SkillFileUpload {
  file_name?: string;
  name?: string;
  object_name?: string;
  preview_url?: string;
  url?: string;
  presigned_url?: string;
  download_url?: string;
  mime_type?: string;
  type?: string;
  file_size?: number;
  size?: number;
}

/**
 * Extracts plain text from assistant-ui ThreadMessage content parts.
 */
function extractTextContent(messages: readonly ThreadMessage[]): string {
  return messages
    .map((msg) => {
      const parts = msg.content;
      if (!parts || parts.length === 0) return "";

      return parts
        .map((part) => {
          if (part.type === "text") return part.text ?? "";
          if (part.type === "image") return "[image]";
          return "";
        })
        .join("");
    })
    .join("\n");
}

/**
 * Extracts `minio_files` payload from a user message's attachments. The
 * attachment adapter stashes upload metadata on each attachment after a
 * successful MinIO upload, so we can read it back here without an extra
 * upload round-trip.
 */
function extractMinioFiles(
  message: ThreadMessage | undefined
): MinioFilePayload[] {
  if (!message) return [];
  // Attachments are attached by the AttachmentAdapter via the message content
  // pipeline; the public ThreadMessage type does not declare them but they are
  // present at runtime.
  const attachments = message.attachments as
    | Array<{
        name: string;
        contentType?: string;
        type?: string;
        object_name?: string;
        url?: string;
        presigned_url?: string;
        size?: number;
      }>
    | undefined;
  if (!attachments || attachments.length === 0) return [];

  const files: MinioFilePayload[] = [];
  for (const att of attachments) {
    const objectName = att.object_name;
    const url = att.url;
    if (!objectName || !url) {
      log.warn(
        "[ChatModelAdapter] Attachment missing upload metadata, skipping:",
        att.name
      );
      continue;
    }
    files.push({
      name: att.name,
      object_name: objectName,
      type: att.type ?? att.contentType ?? "file",
      size: att.size ?? 0,
      url,
      presigned_url: att.presigned_url,
    });
  }
  return files;
}

function parseSkillFileAttachments(
  content: string,
  messageId: string
): CompleteAttachment[] {
  try {
    const payload = JSON.parse(content) as {
      skill_file_uploads?: SkillFileUpload[];
    };
    if (!Array.isArray(payload.skill_file_uploads)) return [];

    const attachments: CompleteAttachment[] = payload.skill_file_uploads.map(
      (file, index) => {
        const name = file.file_name || file.name || "Generated file";
        const contentType =
          file.mime_type || file.type || "application/octet-stream";
        const url = file.preview_url || file.presigned_url || file.url;

        return {
          id: `${messageId}-skill-file-${index}`,
          status: { type: "complete" as const },
          type: "file" as const,
          name,
          contentType,
          content: url
            ? [
                {
                  type: "file" as const,
                  filename: name,
                  data: url,
                  mimeType: contentType,
                },
              ]
            : [],
          object_name: file.object_name,
          preview_url: file.preview_url || file.presigned_url,
          download_url: file.download_url,
          url: file.url,
          presigned_url: file.presigned_url,
          size: file.file_size ?? file.size,
        } as unknown as CompleteAttachment;
      }
    );

    return attachments;
  } catch (error) {
    log.warn("[ChatModelAdapter] Failed to parse skill_file_uploads:", error);
    return [];
  }
}

/**
 * Parses one SSE line `data: {...}` into an SseChunk object.
 * Returns null for non-data lines or malformed JSON.
 */
function parseSseChunk(line: string): SseChunk | null {
  if (!line.startsWith("data: ")) return null;
  const jsonStr = line.slice(6).trim();
  if (!jsonStr) return null;
  try {
    const parsed = JSON.parse(jsonStr) as Record<string, unknown>;
    if (typeof parsed.type === "string") return parsed as unknown as SseChunk;
    if (typeof parsed.status === "string") {
      return { type: "status", content: parsed.status };
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Extracts the agent run start time from an agent_new_run content string.
 * The backend prepends `[Current time: YYYY-MM-DD HH:MM:SS]` to the task text.
 * Returns undefined when the prefix is absent or unparseable.
 */
const AGENT_RUN_TIME_PREFIX = "[Current time:";
function extractAgentRunTime(content: string): string | undefined {
  if (!content || !content.startsWith(AGENT_RUN_TIME_PREFIX)) return undefined;
  const closeIdx = content.indexOf("]", AGENT_RUN_TIME_PREFIX.length);
  if (closeIdx < 0) return undefined;
  const raw = content.slice(AGENT_RUN_TIME_PREFIX.length, closeIdx).trim();
  // Basic format check: "YYYY-MM-DD HH:MM:SS"
  if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(raw)) return undefined;
  return raw;
}

/**
 * Maps a backend chunk type to an assistant-ui part type.
 * Returns null for types that should be handled internally (not rendered).
 *
 * Backend chunk types from /agent/run SSE stream:
 *
 * | Backend Type                  | Mapped to    | Description                        |
 * |-------------------------------|--------------|------------------------------------|
 * | model_output_thinking         | reasoning    | Model thinking content (streamed)  |
 * | model_output_deep_thinking    | reasoning    | Model deep thinking content         |
 * | model_output_code             | reasoning    | Model code output (streamed)        |
 * | step_count                   | text         | Current execution step number       |
 * | parse                         | tool-call    | Code parsing result                |
 * | execution_logs                | (attach)     | Attached to preceding tool result  |
 * | agent_new_run                 | text         | Agent basic information            |
 * | agent_finish                 | text         | Sub-agent run completion marker    |
 * | final_answer                 | text         | Final summary answer               |
 * | error                         | text         | Error message                      |
 * | search_content               | text         | Search results content             |
 * | picture_web                  | text         | Web search image references        |
 * | card                         | text         | Card-rendered content              |
 * | tool                         | tool-call    | Tool invocation                    |
 * | memory_search                | text         | Memory search status               |
 * | max_steps_reached            | text         | Max steps limit reached            |
 * | verification                  | text         | ReAct self-verification status     |
 * | skill_file_uploads                  | (attachment) | Skill file upload completion       |
 * | token_count                  | (internal)   | Token usage data for timing        |
 * | conversation_created          | (skipped)    | Internal event, not surfaced       |
 * | status                       | (skipped)    | Internal status, not surfaced       |
 * | search_content_placeholder   | (skipped)    | Internal placeholder, not surfaced  |
 */
export function isReasoningChunkType(type: string): boolean {
  return (
    type === "reasoning" ||
    type === "model_output_thinking" ||
    type === "model_output_deep_thinking" ||
    type === "model_output_code"
  );
}

function mapChunkType(type: string): AssistantPartType | null {
  if (isReasoningChunkType(type)) return "reasoning";

  switch (type) {
    case "tool-call":
    case "tool":
      return "tool-call";
    case "final_answer":
    case "agent_run_info":
    case "user_input":
    case "agent_finish":
    case "max_steps_reached":
    case "verification":
    case "error":
      return "text";
    case "search_content":
    case "picture_web":
      return "source";
    case "conversation_created":
    case "other":
    case "agent_new_run":
    case "token_count":
    case "step_count":
    case "parse":
    case "card":
    case "skill_files":
    case "memory_search":
      return null;
    default:
      return "text";
  }
}

/**
 * Builds an assistant-ui tool-call part from an SSE chunk. The `toolName`
 * comes from `tool_name` (falling back to `role`); arguments come from
 * `tool_arguments` (which may be either a string or a JSON object) and
 * fall back to raw `content`.
 */
export function buildToolCallPart(chunk: SseChunk): any {
  const toolCallId = `tool-${Date.now()}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
  const toolName = chunk.tool_name || chunk.role || "tool";
  // `tool_arguments` may arrive as either a JSON object (the common case
  // for MCP tools such as exa_search) or a pre-stringified string. We
  // normalize both forms so the ToolFallback UI can render the value
  // directly.
  const rawArgs = chunk.tool_arguments ?? chunk.content;
  const argsText = formatToolArguments(rawArgs);
  return {
    type: "tool-call" as const,
    toolCallId,
    toolName,
    args: {},
    argsText,
    unit_index: chunk.unit_index,
  };
}

/**
 * Normalizes a tool-arguments payload for display. Plain strings are
 * passed through; objects are pretty-printed as JSON so the UI shows the
 * readable parameter set (e.g. `query: "..."`) instead of `[object Object]`.
 */
function formatToolArguments(raw: unknown): string {
  if (raw === undefined || raw === null) return "";
  if (typeof raw === "string") return raw;
  try {
    return JSON.stringify(raw, null, 2);
  } catch {
    return String(raw);
  }
}

/**
 * Appends a tool-call to `contentParts`. We always push a standalone
 * tool-call part; assistant-ui's `MessagePrimitive.GroupedParts` will
 * cluster consecutive tool-calls into a `group-tool` block for the
 * shared `ToolGroupRoot` / `ToolGroupTrigger` / `ToolGroupContent`
 * rendering defined in `thread.tsx`.
 */
function appendToolCallPart(contentParts: any[], toolCallPart: any): any {
  contentParts.push(toolCallPart);
  return toolCallPart;
}

/**
 * Attaches an `execution_logs` chunk to the most recently created tool
 * call so the ToolFallback UI can render the logs as the tool's result.
 *
 * Matching prefers `unit_index`; when absent (or unmatched), the most
 * recent tool call is used as a fallback. When no preceding tool call
 * exists, the logs are surfaced as a plain text part so the data is not
 * silently dropped.
 */
function attachExecutionLogsToTool(
  contentParts: any[],
  chunk: SseChunk
): boolean {
  let targetToolCall: any = null;

  // First pass: try to match by unit_index when available.
  if (chunk.unit_index !== undefined) {
    for (let i = contentParts.length - 1; i >= 0; i--) {
      const part = contentParts[i];
      if (part?.type !== "tool-call") continue;
      if (part.unit_index === chunk.unit_index) {
        targetToolCall = part;
        break;
      }
    }
  }

  // Second pass: fall back to the most recent tool call.
  if (!targetToolCall) {
    for (let i = contentParts.length - 1; i >= 0; i--) {
      const part = contentParts[i];
      if (part?.type !== "tool-call") continue;
      targetToolCall = part;
      break;
    }
  }

  if (targetToolCall) {
    targetToolCall.result = (targetToolCall.result ?? "") + chunk.content;
    return true;
  }
  return false;
}

/**
 * Attaches a search source / image entry to the most recently created tool
 * call (matched by unit_index when available). The tool-call's `searchContent`
 * (URL list) and `searchImages` (image URL list) arrays are used by
 * ToolFallbackSearchContent to render per-tool sources.
 */
export function attachSearchContentToTool(
  contentParts: any[],
  unitIndex: number | undefined,
  item: { url: string; title: string }
): boolean {
  const targetToolCall = findMostRecentToolCall(contentParts, unitIndex);
  if (!targetToolCall) return false;
  if (!targetToolCall.searchContent) {
    targetToolCall.searchContent = [];
  }
  if (
    item.url &&
    !targetToolCall.searchContent.some(
      (source: { url: string }) => source.url === item.url
    )
  ) {
    targetToolCall.searchContent.push(item);
  }
  return true;
}

/**
 * Attaches a picture (image URL) entry to the most recently created tool call.
 */
export function attachSearchImageToTool(
  contentParts: any[],
  unitIndex: number | undefined,
  imageUrl: string
): boolean {
  const targetToolCall = findMostRecentToolCall(contentParts, unitIndex);
  if (!targetToolCall) return false;
  if (!targetToolCall.searchImages) {
    targetToolCall.searchImages = [];
  }
  if (!targetToolCall.searchImages.includes(imageUrl)) {
    targetToolCall.searchImages.push(imageUrl);
  }
  return true;
}

/**
 * Finds the most recently created tool-call part, optionally matched by
 * `unit_index`. Shared by source / image attachment helpers.
 */
function findMostRecentToolCall(
  contentParts: any[],
  unitIndex: number | undefined
): any {
  if (unitIndex !== undefined) {
    for (let i = contentParts.length - 1; i >= 0; i--) {
      const part = contentParts[i];
      if (part?.type !== "tool-call") continue;
      if (part.unit_index === unitIndex) return part;
    }
  }
  for (let i = contentParts.length - 1; i >= 0; i--) {
    const part = contentParts[i];
    if (part?.type !== "tool-call") continue;
    return part;
  }
  return null;
}

// Global registry for search sources by message ID (used by MarkdownText for [[b1]] rendering)
// Keyed by messageId (from message.id in the stream), value is SearchSource[]
export interface SearchSource {
  citeIndex: number;
  url: string;
  title: string;
  text?: string;
  sourceType?: string;
  searchType?: string;
  toolSign?: string;
  filename?: string;
  downloadUrl?: string;
  objectName?: string;
}
export const searchSourcesRegistry = new Map<string, SearchSource[]>();

// Conversation-level search sources registry for historical messages.
// Keyed by the assistant-ui messageId so the lookup matches the
// `s.message.id` selector used by `markdown-text.tsx`. Populated by
// `RemoteConversationHistoryAdapter.load()` when restoring a conversation.
export const conversationSourcesRegistry = new Map<string, SearchSource[]>();

// Assistant-generated files are rendered outside message attachments because
// assistant-ui only permits attachments on user messages.
export const skillFileUploadsRegistry = new Map<string, CompleteAttachment[]>();

// Global registry for step token counts (populated during streaming, consumed by UI)
export const stepTokenCounts: StepTokenCount[] = [];

/**
 * Append a parsed `StepTokenCount` to the global streaming registry.
 * Exposed so the `ChatModelAdapter.run` flow and any other writer share a
 * single insertion point. The reader side (`SingleTurnTokenUsage`) keeps
 * importing `stepTokenCounts` directly to avoid an extra re-render.
 */
export function pushStepTokenCount(step: StepTokenCount): void {
  stepTokenCounts.push(step);
}

let agentRunTime: string | undefined;

export function getAgentRunTime(): string | undefined {
  return agentRunTime;
}

/**
 * Clears the global step token counts registry.
 */
export function clearStepTokenCounts(): void {
  stepTokenCounts.length = 0;
  accumulatedDuration = 0;
  agentRunTime = undefined;
}

/**
 * Remote ChatModelAdapter for Nexent backend agent streaming.

/**
 * Parse and build timing metadata from backend token_count chunk.
 * Also stores step data in the global registry for SingleTurnTokenUsage.
 */
function buildTimingFromTokenCount(
  content: string
): ReturnType<typeof buildTimingResult> | null {
  const parsed = parseStepTokenCount(content);
  if (!parsed) {
    log.warn("[ChatModelAdapter] Failed to parse token_count:", content);
    return null;
  }

  // Store step data in global registry so the currently-streaming message's
  // `SingleTurnTokenUsage` can render it without subscribing to per-message
  // metadata updates.
  pushStepTokenCount(parsed);

  // Accumulate duration across all steps
  accumulatedDuration += parsed.duration;

  // Use accumulated duration for total stream time
  const totalDuration = accumulatedDuration;

  return buildTimingResult(
    Date.now(), // streamStartTime - approximate
    undefined, // firstTokenTime - not available
    0, // toolCallCount - tracked separately
    parsed.totalOutputTokens,
    totalDuration
  );
}

/**
 * Remote ChatModelAdapter for Nexent backend agent streaming.
 *
 * Responsibilities:
 * - Build AgentRequest payload from assistant-ui messages
 * - Stream SSE chunks from `/api/agent/run` into ChatModelRunResult
 * - Support resume mode when a thread already has a conversationId
 * - Honor abortSignal for cancellation
 *
 * SSE Protocol:
 *   Backend sends `data: {"type": "...", "content": "..."}` chunks.
 *   Each parsed chunk is yielded as a separate ChatModelRunResult update.
 *   Internal status/resume events are skipped (no UI surface).
 */
export const remoteChatModelAdapter: ChatModelAdapter = {
  async *run({
    messages,
    abortSignal,
    context,
    runConfig,
    unstable_threadId,
  }: ChatModelRunOptions): AsyncGenerator<ChatModelRunResult, void> {
    // Clear step token counts from previous runs
    clearStepTokenCounts();

    // The page layer resolves remote thread metadata to the backend conversation ID.
    // It also injects `onServerConversationId` so we can report back the id
    // the backend auto-creates (via the `conversation_id` response header)
    // when this is the first message in a brand-new thread.
    const customThreadId = runConfig?.custom as
      | {
          threadId?: string;
          draftAgentId?: number | string;
          onServerConversationId?: (
            serverId: string,
            initialQuestion?: string
          ) => void;
          resume?: boolean;
        }
      | undefined;
    const serverThreadId = customThreadId?.threadId;
    const draftAgentId = customThreadId?.draftAgentId;
    const onServerConversationId = customThreadId?.onServerConversationId;
    const isResume = customThreadId?.resume === true;

    // Extract user query: last user message text
    let lastUserIndex = -1;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        lastUserIndex = i;
        break;
      }
    }

    const query =
      lastUserIndex >= 0 ? extractTextContent([messages[lastUserIndex]]) : "";

    if (!isResume && !query) {
      log.warn("[ChatModelAdapter] No user query found in messages");
      return;
    }
    if (isResume && !serverThreadId) {
      log.warn("[ChatModelAdapter] Cannot resume without a conversation ID");
      return;
    }

    // Build history: all messages before the last user message
    const historyMessages =
      !isResume && lastUserIndex > 0 ? messages.slice(0, lastUserIndex) : [];
    const history = historyMessages.map((msg) => {
      const text = extractTextContent([msg]);
      return {
        role: msg.role === "user" ? ("user" as const) : ("assistant" as const),
        content: text,
      };
    });

    // Extract MinIO file metadata from the last user message's attachments.
    // The attachment adapter has already uploaded them by the time `run`
    // is called (assistant-ui calls `send()` before `run()`).
    const minioFiles = isResume
      ? []
      : extractMinioFiles(messages[lastUserIndex]);

    // Build request payload. Resume only needs the conversation identity; the
    // backend owns the original query and execution state.
    const requestBody: Record<string, unknown> = {
      query: isResume ? "" : query,
      history: isResume ? [] : history,
      minio_files: minioFiles.length > 0 ? minioFiles : null,
      is_debug: false,
    };
    const numericServerThreadId = Number(serverThreadId);
    const hasServerConversationId =
      Number.isInteger(numericServerThreadId) && numericServerThreadId > 0;
    if (hasServerConversationId) {
      requestBody.conversation_id = numericServerThreadId;
    }
    const numericDraftAgentId = Number(draftAgentId);
    if (Number.isInteger(numericDraftAgentId) && numericDraftAgentId > 0) {
      requestBody.draft_agent_id = numericDraftAgentId;
    }

    // Pass selected agent if provided via custom (set by the page wrapper)
    const custom = runConfig?.custom as
      { agentId?: number | string; resume?: boolean } | undefined;
    if (custom?.agentId !== undefined && custom.agentId !== null) {
      const numericAgentId =
        typeof custom.agentId === "string"
          ? Number(custom.agentId)
          : custom.agentId;
      if (!Number.isNaN(numericAgentId)) {
        requestBody.agent_id = numericAgentId;
      }
    }

    // Pass selected model if provided via ModelContext (registered by ModelSelector)
    const modelName = context.config?.modelName;
    if (modelName) {
      requestBody.model_id = Number(modelName);
    }

    // Resume is explicit: an existing conversation may also receive a normal
    // new user turn, so conversation_id alone must never select resume mode.
    const url = isResume
      ? `${API_ENDPOINTS.agent.run}?resume=true`
      : API_ENDPOINTS.agent.run;

    log.log(`[ChatModelAdapter] Sending request to ${url}`);

    let response: Response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
        signal: abortSignal,
      });
    } catch (error: unknown) {
      if (error instanceof Error && error.name === "AbortError") {
        log.log("[ChatModelAdapter] Request aborted by user");
        return;
      }
      log.error("[ChatModelAdapter] Fetch error:", error);
      throw error;
    }

    // Capture the server-issued conversation_id from the response header.
    //
    // When the request omits `conversation_id` (i.e. this is the first
    // message in a brand-new thread) the backend auto-creates a conversation
    // row and returns the new id via the `conversation_id` response header
    // (mirrors the northbound `start_streaming_chat` pattern). We forward
    // that id to the page so it can rebind `threadId` for subsequent runs in
    // the same thread, preventing the frontend from triggering an extra
    // `PUT /api/conversation/create` and creating a duplicate empty
    // conversation.
    //
    // The header is also set on the non-streaming resume JSONResponse, so we
    // pick it up there too without any extra work.
    const headerConversationId = response.headers.get("conversation_id");
    if (headerConversationId && onServerConversationId) {
      const numericHeaderId = Number(headerConversationId);
      if (!Number.isNaN(numericHeaderId) && numericHeaderId > 0) {
        try {
          onServerConversationId(
            String(numericHeaderId),
            !isResume && !hasServerConversationId ? query : undefined
          );
          log.log(
            `[ChatModelAdapter] Captured server conversation_id from response header: ${numericHeaderId}`
          );
        } catch (cbError) {
          // Callback failures must never break the stream — log and continue.
          log.error(
            "[ChatModelAdapter] onServerConversationId callback threw:",
            cbError
          );
        }
      }
    }

    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorData.message || errorMessage;
      } catch {
        // Fall back to status text
      }
      log.error(`[ChatModelAdapter] HTTP error: ${errorMessage}`);
      throw new Error(errorMessage);
    }

    if (!response.body) {
      log.warn("[ChatModelAdapter] Empty response body");
      return;
    }

    // Detect JSON response (resume mode where the agent already finished)
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      try {
        const data = await response.json();
        log.log("[ChatModelAdapter] JSON response (resume finished):", data);
      } catch {
        // Ignore parse errors; nothing to stream
      }
      return;
    }

    // Stream SSE chunks
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    let currentReasoningPart: ReturnType<typeof makeReasoningPart> | null =
      null;

    const contentParts: any[] = [];

    // Accumulate search sources and search images across the entire stream.
    // After final_answer these are emitted as source / image parts at the end
    // of the message. The same data is also attached to the most recent
    // tool call so it can be rendered inline within `ToolFallback`.
    //
    // Preserves cite_index for [[b1]] → source registry linkage.
    const searchSourcesAccumulator: SearchSource[] = [];
    const searchImagesAccumulator: string[] = [];
    let skillFileAttachments: CompleteAttachment[] = [];

    // Generate a stable message ID for this stream so MarkdownText can look up sources
    let messageId = `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    let persistedMessageId: number | undefined;
    const buildStreamResult = (
      content: any[],
      timing?: NonNullable<ChatModelRunResult["metadata"]>["timing"]
    ): ChatModelRunResult => ({
      content,
      metadata: {
        ...(timing ? { timing } : {}),
        custom: persistedMessageId === undefined ? {} : { persistedMessageId },
      },
    });

    const streamStartTime = Date.now();
    let firstTokenTime: number | undefined;
    let toolCallCount = 0;
    let storedTiming: ReturnType<typeof buildTimingResult> | null = null;

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Split by SSE line boundaries; keep last incomplete line in buffer
        const lines = buffer.split(/\r?\n/);
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const chunk = parseSseChunk(line);
          if (!chunk) continue;

          // Internal status / resume events: skip
          if (chunk.type === "status") continue;
          if (chunk.type === "assistant_message_created") {
            const persistedId = Number(chunk.content?.message_id);
            if (Number.isInteger(persistedId) && persistedId > 0) {
              persistedMessageId = persistedId;
              messageId = String(persistedId);
            }
            continue;
          }

          // Handle token_count - store timing for final yield
          if (chunk.type === "token_count") {
            storedTiming = buildTimingFromTokenCount(chunk.content);
            continue; // Don't yield for internal data chunks
          }

          // Handle agent_new_run - capture the agent start time before stripping the prefix
          if (chunk.type === "agent_new_run") {
            const captured = extractAgentRunTime(chunk.content);
            if (captured) agentRunTime = captured;
          }

          // Track timing for first content token
          if (firstTokenTime === undefined && chunk.type === "text") {
            firstTokenTime = Date.now() - streamStartTime;
          }

          if (chunk.type === "step_count") {
            // Fold `step_count` into the current reasoning part's text so the
            // rendering layer sees the same `reasoning` part shape regardless
            // of whether the data came from this SSE stream or from a
            // historical load. `ReasoningTrigger` extracts the step label
            // from the leading `**步骤 N**` token at render time.
            currentReasoningPart = makeReasoningPart(
              (currentReasoningPart?.text ?? "") + chunk.content,
              true
            );
            yield buildStreamResult([
              ...contentParts,
              currentReasoningPart,
            ] as any);
            continue;
          }

          if (chunk.type === "skill_files") {
            skillFileAttachments = [
              ...skillFileAttachments,
              ...parseSkillFileAttachments(chunk.content, messageId),
            ];
            skillFileUploadsRegistry.set(messageId, skillFileAttachments);
            contentParts.push({
              type: "text",
              text: "",
              isSkillFiles: true,
              skillFileAttachments,
            });
            yield buildStreamResult(contentParts);
            continue;
          }

          // Handle execution_logs by attaching them as the result of the most
          // recent tool call (matched by unit_index when available).
          if (chunk.type === "execution_logs") {
            const attached = attachExecutionLogsToTool(contentParts, chunk);
            if (!attached) {
              contentParts.push({ type: "text", text: chunk.content });
            }
            yield buildStreamResult(contentParts);
            continue;
          }

          // Handle picture_web: accumulate image URLs and attach them to the
          // most recent tool call (matched by unit_index when available) so the
          // ToolFallback can render them inline.
          if (chunk.type === "picture_web") {
            try {
              const parsed = JSON.parse(chunk.content);
              const imageUrls: string[] = Array.isArray(parsed?.images_url)
                ? parsed.images_url
                : [];
              for (const imageUrl of imageUrls) {
                if (!imageUrl) continue;
                if (!searchImagesAccumulator.includes(imageUrl)) {
                  searchImagesAccumulator.push(imageUrl);
                }
                attachSearchImageToTool(
                  contentParts,
                  chunk.unit_index,
                  imageUrl
                );
              }
            } catch (e) {
              log.warn("[ChatModelAdapter] Failed to parse picture_web:", e);
            }
            // Do NOT yield image parts inline — they are emitted globally after
            // final_answer below.
            continue;
          }

          const partType = mapChunkType(chunk.type);

          if (partType === "reasoning") {
            // Update the streaming reasoning part in-place
            currentReasoningPart = makeReasoningPart(
              (currentReasoningPart?.text ?? "") + chunk.content,
              true
            );
            yield buildStreamResult([
              ...contentParts,
              currentReasoningPart,
            ] as any);
          } else if (partType === "tool-call") {
            // Finalize any ongoing reasoning
            if (currentReasoningPart) {
              currentReasoningPart.status = { type: "done" };
              contentParts.push(currentReasoningPart);
              currentReasoningPart = null;
            }

            if (
              chunk.type === "tool-call" ||
              chunk.type === "tool" ||
              chunk.type === "parse"
            ) {
              toolCallCount++;
              const toolCallPart = buildToolCallPart(chunk);
              appendToolCallPart(contentParts, toolCallPart);
            }
            yield buildStreamResult(contentParts);
          } else if (partType === "text") {
            // Non-reasoning chunk: finalize the reasoning part
            if (currentReasoningPart) {
              currentReasoningPart.status = { type: "done" };
              contentParts.push(currentReasoningPart);
              currentReasoningPart = null;
            }

            contentParts.push(
              chunk.type === "verification"
                ? buildVerificationPart(chunk.content)
                : {
                    type: "text",
                    text: chunk.content,
                    ...(chunk.type === "error" && { isError: true }),
                  }
            );
            yield buildStreamResult(contentParts);
          } else if (partType === "source") {
            // search_content chunk: accumulate for global display and attach to
            // the most recent tool call so the ToolFallback UI can render them.
            try {
              const searchResults = JSON.parse(chunk.content);
              const results = Array.isArray(searchResults)
                ? searchResults
                : [searchResults];
              for (const result of results) {
                const url = result.url || "";
                const filename = result.filename || "";
                const citeIndex = result.cite_index ?? result.citeIndex ?? 0;
                const title = result.title || filename || url;
                const sourceKey = `${result.source_type || "url"}:${result.object_name || url || filename || title}`;
                if (
                  (url || filename || title) &&
                  !searchSourcesAccumulator.some(
                    (source) =>
                      `${source.sourceType || "url"}:${source.objectName || source.url || source.filename || source.title}` ===
                      sourceKey
                  )
                ) {
                  searchSourcesAccumulator.push({
                    citeIndex,
                    url,
                    title,
                    text: result.text,
                    sourceType: result.source_type,
                    searchType: result.search_type,
                    toolSign: result.tool_sign,
                    filename,
                    downloadUrl: result.download_url,
                    objectName: result.object_name,
                  });
                }
                attachSearchContentToTool(contentParts, chunk.unit_index, {
                  url,
                  title,
                });
              }
            } catch (e) {
              log.warn("[ChatModelAdapter] Failed to parse search_content:", e);
            }
            // Do NOT yield source parts inline — they are emitted globally after
            // final_answer below.
          }
        }
      }

      // Process any remaining buffered line
      if (buffer.trim()) {
        const chunk = parseSseChunk(buffer);
        if (chunk && chunk.type !== "status") {
          if (chunk.type === "assistant_message_created") {
            const persistedId = Number(chunk.content?.message_id);
            if (Number.isInteger(persistedId) && persistedId > 0) {
              persistedMessageId = persistedId;
              messageId = String(persistedId);
            }
          } else if (chunk.type === "execution_logs") {
            const attached = attachExecutionLogsToTool(contentParts, chunk);
            if (!attached) {
              contentParts.push({ type: "text", text: chunk.content });
            }
            yield buildStreamResult(contentParts);
          } else if (chunk.type === "skill_files") {
            skillFileAttachments = [
              ...skillFileAttachments,
              ...parseSkillFileAttachments(chunk.content, messageId),
            ];
            skillFileUploadsRegistry.set(messageId, skillFileAttachments);
            contentParts.push({
              type: "text",
              text: "",
              isSkillFiles: true,
              skillFileAttachments,
            });
            yield buildStreamResult(contentParts);
          } else if (chunk.type === "picture_web") {
            try {
              const parsed = JSON.parse(chunk.content);
              const imageUrls: string[] = Array.isArray(parsed?.images_url)
                ? parsed.images_url
                : [];
              for (const imageUrl of imageUrls) {
                if (!imageUrl) continue;
                if (!searchImagesAccumulator.includes(imageUrl)) {
                  searchImagesAccumulator.push(imageUrl);
                }
                attachSearchImageToTool(
                  contentParts,
                  chunk.unit_index,
                  imageUrl
                );
              }
            } catch (e) {
              log.warn("[ChatModelAdapter] Failed to parse picture_web:", e);
            }
          } else {
            const partType = mapChunkType(chunk.type);
            if (partType === "reasoning") {
              currentReasoningPart = makeReasoningPart(
                (currentReasoningPart?.text ?? "") + chunk.content,
                true
              );
              yield buildStreamResult([
                ...contentParts,
                currentReasoningPart,
              ] as any);
            } else if (partType === "tool-call") {
              if (currentReasoningPart) {
                currentReasoningPart.status = { type: "done" };
                contentParts.push(currentReasoningPart);
                currentReasoningPart = null;
              }
              if (
                chunk.type === "tool-call" ||
                chunk.type === "tool" ||
                chunk.type === "parse"
              ) {
                toolCallCount++;
                const toolCallPart = buildToolCallPart(chunk);
                appendToolCallPart(contentParts, toolCallPart);
              }
              yield buildStreamResult(contentParts);
            } else if (partType === "text") {
              if (currentReasoningPart) {
                currentReasoningPart.status = { type: "done" };
                contentParts.push(currentReasoningPart);
                currentReasoningPart = null;
              }
              contentParts.push(
                chunk.type === "verification"
                  ? buildVerificationPart(chunk.content)
                  : {
                      type: "text",
                      text: chunk.content,
                      ...(chunk.type === "error" && { isError: true }),
                    }
              );
              yield buildStreamResult(contentParts);
            } else if (partType === "source") {
              if (currentReasoningPart) {
                currentReasoningPart.status = { type: "done" };
                contentParts.push(currentReasoningPart);
                currentReasoningPart = null;
              }
              try {
                const searchResults = JSON.parse(chunk.content);
                const results = Array.isArray(searchResults)
                  ? searchResults
                  : [searchResults];
                for (const result of results) {
                  const url = result.url || "";
                  const filename = result.filename || "";
                  const citeIndex = result.cite_index ?? result.citeIndex ?? 0;
                  const title = result.title || filename || url;
                  const sourceKey = `${result.source_type || "url"}:${result.object_name || url || filename || title}`;
                  if (
                    (url || filename || title) &&
                    !searchSourcesAccumulator.some(
                      (source) =>
                        `${source.sourceType || "url"}:${source.objectName || source.url || source.filename || source.title}` ===
                        sourceKey
                    )
                  ) {
                    searchSourcesAccumulator.push({
                      citeIndex,
                      url,
                      title,
                      text: result.text,
                      sourceType: result.source_type,
                      searchType: result.search_type,
                      toolSign: result.tool_sign,
                      filename,
                      downloadUrl: result.download_url,
                      objectName: result.object_name,
                    });
                  }
                  attachSearchContentToTool(contentParts, chunk.unit_index, {
                    url,
                    title,
                  });
                }
              } catch (e) {
                log.warn(
                  "[ChatModelAdapter] Failed to parse search_content:",
                  e
                );
              }
            }
          }
        }
      }

      // Finalize any remaining reasoning content at the end
      if (currentReasoningPart) {
        currentReasoningPart.status = { type: "done" };
        contentParts.push(currentReasoningPart);
      }

      // Emit collected search sources as a block after final_answer so the UI
      // shows a unified global sources section at the end of the message.
      // Also register in the shared registry so MarkdownText can resolve [[b1]] refs.
      if (searchSourcesAccumulator.length > 0) {
        searchSourcesRegistry.set(messageId, searchSourcesAccumulator);
        for (const source of searchSourcesAccumulator) {
          contentParts.push({
            type: "source",
            sourceType: source.sourceType === "file" ? "document" : "url",
            url: source.url,
            title: source.title,
            text: source.text,
            filename: source.filename,
            downloadUrl: source.downloadUrl,
            objectName: source.objectName,
            citeIndex: source.citeIndex,
            messageId, // used by thread.tsx / MarkdownText to look up from registry
          });
        }
      }

      // Emit collected search image URLs as a global sources block. Each
      // image is pushed as a `source` part of type `url` with an `isImage`
      // marker so thread.tsx can render it as a thumbnail matching the
      // per-tool ToolFallback.SearchContent rendering.
      if (searchImagesAccumulator.length > 0) {
        for (const imageUrl of searchImagesAccumulator) {
          contentParts.push({
            type: "source",
            sourceType: "url",
            url: imageUrl,
            title: imageUrl,
            isImage: true,
          });
        }
      }

      const finalTiming =
        storedTiming ??
        buildTimingResult(streamStartTime, firstTokenTime, toolCallCount);
      yield buildStreamResult(contentParts, finalTiming.metadata.timing);
    } finally {
      reader.releaseLock();
    }
  },
};

/**
 * Build timing metadata for ChatModelRunResult.
 */
function buildTimingResult(
  streamStartTime: number,
  firstTokenTime: number | undefined,
  toolCallCount: number,
  tokenCount: number = 0,
  duration: number = 0
) {
  const totalStreamTime =
    duration > 0 ? duration * 1000 : Date.now() - streamStartTime;

  return {
    metadata: {
      timing: {
        streamStartTime,
        firstTokenTime,
        totalStreamTime,
        tokenCount,
        tokensPerSecond:
          duration > 0 && tokenCount > 0 ? tokenCount / duration : undefined,
        totalChunks: 1,
        toolCallCount,
      },
    },
  };
}
