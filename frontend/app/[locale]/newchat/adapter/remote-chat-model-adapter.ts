"use client";

import type {
  ChatModelAdapter,
  ChatModelRunOptions,
  ChatModelRunResult,
  CompleteAttachment,
  ThreadMessage,
} from "@assistant-ui/react";

import { conversationService } from "@/services/conversationService";
import log from "@/lib/logger";
import { parseAutomationProposal } from "@/features/agentAutomation/parseProposal";

// Backend SSE chunk format
interface SseChunk {
  type: string;
  content: string;
  unit_index?: number;
  // Unique ID shared by a tool call and its side-channel output.
  tool_call_id?: string;
  role?: string;
  tool_name?: string;
  tool_arguments?: string | Record<string, unknown>;
  // Optional sub-agent metadata surfaced alongside ``subagent_start`` /
  // ``subagent_end`` boundaries so the frontend can render the nested card
  // without re-parsing the JSON payload.
  agent_id?: number | string;
  agent_name?: string;
  depth?: number;
}

export interface Nl2aToolRecommendation {
  tool_id: number;
  name: string;
  origin_name?: string | null;
  description: string;
  source: "mcp";
  usage: string;
  labels: string[];
  inputs: Record<string, unknown>;
  score: number;
}

export interface Nl2AgentSelectedTool {
  tool_id: number;
  name: string;
  origin_name?: string | null;
  description: string;
  source: "mcp";
  usage: string;
  labels: string[];
  inputs: string;
}

export interface Nl2AgentToolSelection {
  type: "nl2agent_tool_selection";
  tools: Nl2AgentSelectedTool[];
}

export type Nl2aLocalMcpRecommendationPayload =
  | {
      subtype: "local_mcp_recommendation";
      status: "success";
      recommendation_count: number;
      recommendations: Nl2aToolRecommendation[];
    }
  | {
      subtype: "local_mcp_recommendation";
      status: "error";
      code: "invalid_keywords" | "tool_search_failed";
      retryable: true;
    };

export interface Nl2aAgentDraftPayload {
  subtype: "agent_draft";
  name: string;
  display_name: string;
  description: string;
  duty_prompt: string;
  constraint_prompt: string;
  few_shots_prompt: string | null;
  greeting_message: string;
  example_questions: string[];
}

export type Nl2aPayload =
  Nl2aLocalMcpRecommendationPayload | Nl2aAgentDraftPayload;

export interface Nl2aMessage {
  type: "nl2a";
  tool_name?: string;
  content: Nl2aPayload;
}

interface NexentRunConfig {
  threadId?: string;
  onServerConversationId?: (serverId: string, initialQuestion?: string) => void;
  resume?: boolean;
  agentId?: number | string;
  enablePlan?: boolean;
  runtimeMode?: "nl2agent";
}

// assistant-ui valid part types referenced by this adapter
type AssistantPartType = "text" | "reasoning" | "tool-call" | "source";

// Sub-agent metadata stamped onto reasoning / tool-call / source parts while
// the parent agent has invoked a managed sub-agent. The metadata is the
// bridge between the flat SSE stream and the assistant-ui GroupedParts tree
// in ``thread.tsx``: ``groupBy`` reads ``metadata.subagentId`` +
// ``metadata.runId`` to cluster nested parts inside a
// ``group-subagent-<id>-<runId>`` header (rendered as a collapsible card).
export interface SubAgentPartMetadata {
  subagentId: number | string;
  runId: string;
  agentName: string;
  depth: number;
  task?: string;
  isRunning?: boolean;
}

interface SubAgentStartPayload {
  agent_id?: number | string | null;
  agent_name?: string;
  task?: string;
}

interface SubAgentEndPayload {
  agent_id?: number | string | null;
  agent_name?: string;
}

function parseSubAgentStart(content: string): SubAgentStartPayload {
  if (!content) return {};
  try {
    const parsed = JSON.parse(content);
    if (parsed && typeof parsed === "object") return parsed as SubAgentStartPayload;
  } catch {
    // Backwards-compat: legacy SUBAGENT_START chunks carried plain task text.
  }
  return { task: content };
}

function parseSubAgentEnd(content: string): SubAgentEndPayload {
  if (!content) return {};
  try {
    const parsed = JSON.parse(content);
    if (parsed && typeof parsed === "object") return parsed as SubAgentEndPayload;
  } catch {
    // Fall through to empty payload.
  }
  return {};
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
  contextWindowTokens: number | null;
}

/**
 * Parsed ReAct self-verification payload from a backend `verification` SSE chunk.
 * All fields mirror the backend VerificationResult.to_payload() shape.
 */
export interface VerificationContent {
  phase: string;
  event: string;
  round: number;
  severity: string;
  score: number;
  failed_criteria: string[];
  repair_instruction: string;
  user_visible_note: string;
  message: string;
  passed: boolean;
}

export interface VerificationPanelPart {
  type: "verification-panel";
  results: VerificationContent[];
  completed: boolean;
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
      context_window_tokens?: number | null;
    };
    return {
      stepNumber: data.step_number ?? 0,
      duration: data.duration ?? 0,
      stepInputTokens: data.step_input_tokens ?? 0,
      stepOutputTokens: data.step_output_tokens ?? 0,
      totalOutputTokens: data.total_output_tokens ?? 0,
      estimatedContextTokens: data.estimated_context_tokens ?? 0,
      tokenThreshold: data.token_threshold ?? null,
      contextWindowTokens: data.context_window_tokens ?? null,
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
 * ``metadata`` is an optional escape hatch: assistant-ui's ``ReasoningPart``
 * type does not declare a metadata field, but we attach one so the
 * ``MessagePrimitive.GroupedParts`` ``groupBy`` callback can route the part
 * into the right sub-agent cluster.
 */
function makeReasoningPart(
  text: string,
  isRunning: boolean,
  metadata?: SubAgentPartMetadata,
): ReasoningPart {
  const part: ReasoningPart = {
    type: "reasoning",
    text,
    status: { type: isRunning ? "running" : "done" },
  };
  if (metadata) {
    // ``ReasoningPart`` does not expose ``metadata``; the runtime tolerates
    // the extra field, and the renderer reads it via a typed cast.
    (part as ReasoningPart & { metadata?: SubAgentPartMetadata }).metadata =
      metadata;
  }
  return part;
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
 * | nl2a                          | (metadata)   | NL2Agent structured output         |
 * | agent_new_run                 | text         | Agent basic information            |
 * | agent_finish                 | text         | Sub-agent run completion marker    |
 * | subagent_start               | subagent     | Opens a nested sub-agent card      |
 * | subagent_end                 | subagent     | Closes the most recent nested card |
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
    case "subagent_start":
    case "subagent_end":
      // Sub-agent boundaries are handled explicitly above before mapChunkType
      // runs. Falling through here would push them as plain text parts.
      return null;
    case "conversation_created":
    case "other":
    case "agent_new_run":
    case "token_count":
    case "step_count":
    case "parse":
    case "card":
    case "nl2a":
    case "skill_files":
    case "memory_search":
    case "plan":
    case "plan_step_update":
    case "execution_logs":
      return null;
    default:
      return null;
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
    tool_call_id: chunk.tool_call_id,
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
 * Parses an NL2Agent SSE chunk into frontend message metadata.
 */
function parseNl2aMessage(chunk: SseChunk): Nl2aMessage | null {
  try {
    return {
      type: "nl2a",
      tool_name: chunk.tool_name,
      content: JSON.parse(chunk.content) as Nl2aPayload,
    };
  } catch (error) {
    log.warn("[ChatModelAdapter] Failed to parse nl2a content:", error);
    return null;
  }
}

/**
 * Attaches an `execution_logs` chunk to its originating tool call.
 *
 * Matching uses the stable `tool_call_id` emitted at the actual invocation
 * boundary. Legacy payloads without an ID attach to the most recent tool call.
 */
export function attachExecutionLogsToTool(
  contentParts: any[],
  chunk: SseChunk
): boolean {
  const targetToolCall = findMostRecentToolCall(
    contentParts,
    chunk.tool_call_id
  );
  if (!targetToolCall) return false;

  // Do not fall back when an ID is present but cannot be matched. That could
  // attach a parallel tool call's logs to the wrong result.
  if (
    chunk.tool_call_id !== undefined &&
    targetToolCall.tool_call_id !== chunk.tool_call_id
  ) {
    return false;
  }

  targetToolCall.result = (targetToolCall.result ?? "") + chunk.content;
  return true;
}

/**
 * Attaches a search source to its originating tool call.
 */
export function attachSearchContentToTool(
  contentParts: any[],
  item: { url: string; title: string },
  toolCallId: string | undefined = undefined
): boolean {
  const targetToolCall = findMostRecentToolCall(contentParts, toolCallId);
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
 * Attaches an image URL to its originating tool call.
 */
export function attachSearchImageToTool(
  contentParts: any[],
  imageUrl: string,
  toolCallId: string | undefined = undefined
): boolean {
  const targetToolCall = findMostRecentToolCall(contentParts, toolCallId);
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
 * Finds the tool call identified by `toolCallId`, or the most recent call
 * when an incomplete payload has no correlation ID.
 */
function findMostRecentToolCall(
  contentParts: any[],
  toolCallId: string | undefined = undefined
): any {
  if (toolCallId !== undefined) {
    for (let i = contentParts.length - 1; i >= 0; i--) {
      const part = contentParts[i];
      if (part?.type !== "tool-call") continue;
      if (part.tool_call_id === toolCallId) return part;
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

// Plan data types
export interface PlanStep {
  id: string;
  title: string;
  description?: string;
  status: string;
}

export interface PlanData {
  planId?: string;
  title: string;
  steps: PlanStep[];
}

// Global plan store shared by the stream adapter and the composer UI.
const planListeners = new Set<() => void>();
export const planRegistry = {
  data: null as PlanData | null,
  set(newData: PlanData | null) {
    this.data = newData
      ? { ...newData, steps: newData.steps.map((step) => ({ ...step })) }
      : null;
    planListeners.forEach((listener) => listener());
  },
  updateStep(stepId: string, status: string) {
    if (!this.data) return;
    const stepIndex = this.data.steps.findIndex((item) => item.id === stepId);
    if (stepIndex < 0) return;
    const steps = this.data.steps.map((step, index) =>
      index === stepIndex ? { ...step, status } : step,
    );
    this.data = { ...this.data, steps };
    planListeners.forEach((listener) => listener());
  },
  subscribe(listener: () => void) {
    planListeners.add(listener);
    return () => {
      planListeners.delete(listener);
    };
  },
};

export function parsePlan(content: string): PlanData | null {
  try {
    const payload = JSON.parse(content) as {
      plan_id?: string;
      title?: string;
      steps?: Array<{
        id?: string | number;
        title?: string;
        description?: string;
        status?: string;
      }>;
    };
    if (!Array.isArray(payload.steps)) return null;
    return {
      planId: payload.plan_id,
      title: payload.title || "Plan",
      steps: payload.steps.map((step) => ({
        id: String(step.id ?? ""),
        title: step.title || String(step.id ?? ""),
        description: step.description,
        status: step.status || "pending",
      })),
    };
  } catch {
    return null;
  }
}

export function parsePlanStepUpdate(content: string): { stepId: string; status: string } | null {
  try {
    const payload = JSON.parse(content) as { step_id?: string | number; status?: string };
    if (payload.step_id === undefined || !payload.status) return null;
    return { stepId: String(payload.step_id), status: payload.status };
  } catch {
    return null;
  }
}

/**
 * Parses the inner JSON payload of a backend `verification` SSE chunk.
 * Returns null for unparseable content so callers skip silently.
 */
export function parseVerification(chunk: { content: string }): VerificationContent | null {
  try {
    const data = JSON.parse(chunk.content);
    return {
      phase: String(data.phase || "start"),
      event: String(data.event || "unknown"),
      round: Number(data.round || 0),
      severity: String(data.severity || "info"),
      score: Number(data.score ?? 1.0),
      failed_criteria: Array.isArray(data.failed_criteria) ? data.failed_criteria.map(String) : [],
      repair_instruction: String(data.repair_instruction ?? ""),
      user_visible_note: String(data.user_visible_note ?? ""),
      message: String(data.message ?? ""),
      passed: Boolean(data.passed ?? false),
    };
  } catch {
    log.warn("[ChatModelAdapter] Failed to parse verification content:", chunk.content);
    return null;
  }
}

/**
 * Mutates ``metadata.isRunning = false`` on every message part carrying the
 * given ``runId``. Called from the ``subagent_end`` handler so the rendered
 * collapsible card flips from its running indicator to a finished state
 * without needing a separate per-message registry.
 */
export function markSubAgentRunFinished(parts: any[], runId: string): void {
  for (const part of parts) {
    if (part && part.metadata && part.metadata.runId === runId) {
      part.metadata.isRunning = false;
    }
  }
}

/**
 * Lookup helper exported for the conversation thread list adapter so the
 * historical message loader can use the same shape when reconstructing
 * sub-agent runs from persisted units.
 */
export function makeSubAgentMetadata(input: {
  subagentId: number | string;
  runId: string;
  agentName: string;
  depth: number;
  task?: string;
  isRunning?: boolean;
}): SubAgentPartMetadata {
  return {
    subagentId: input.subagentId,
    runId: input.runId,
    agentName: input.agentName,
    depth: input.depth,
    task: input.task,
    isRunning: input.isRunning ?? true,
  };
}

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
 * Clears the global step token counts registry and resets the shared plan
 * state. Called from `remoteChatModelAdapter.run()` so a fresh assistant
 * turn never inherits the previous run's plan panel.
 */
export function clearStepTokenCounts(): void {
  stepTokenCounts.length = 0;
  accumulatedDuration = 0;
  agentRunTime = undefined;
  planRegistry.set(null);
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
    const custom = runConfig?.custom as NexentRunConfig | undefined;
    const isNl2Agent = custom?.runtimeMode === "nl2agent";
    const serverThreadId = custom?.threadId;
    const onServerConversationId = custom?.onServerConversationId;
    const isResume = !isNl2Agent && custom?.resume === true;

    // Extract user query: last user message text
    let lastUserIndex = -1;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        lastUserIndex = i;
        break;
      }
    }

    const visibleQuery =
      lastUserIndex >= 0 ? extractTextContent([messages[lastUserIndex]]) : "";
    const selectionMetadata =
      isNl2Agent && lastUserIndex >= 0
        ? (
            messages[lastUserIndex].metadata?.custom as
              { nl2agentToolSelection?: Nl2AgentToolSelection } | undefined
          )?.nl2agentToolSelection
        : undefined;
    const query = selectionMetadata
      ? JSON.stringify(selectionMetadata)
      : visibleQuery;

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
    if (!isNl2Agent && hasServerConversationId) {
      requestBody.conversation_id = numericServerThreadId;
    }

    // Pass selected agent if provided via custom (set by the page wrapper)
    if (
      !isNl2Agent &&
      custom?.agentId !== undefined &&
      custom.agentId !== null
    ) {
      const numericAgentId =
        typeof custom.agentId === "string"
          ? Number(custom.agentId)
          : custom.agentId;
      if (!Number.isNaN(numericAgentId)) {
        requestBody.agent_id = numericAgentId;
      }
    }
    requestBody.enable_plan = custom?.enablePlan === true;

    // Pass selected model if provided via ModelContext (registered by ModelSelector)
    const modelName = context.config?.modelName;
    if (!isNl2Agent && modelName) {
      requestBody.model_id = Number(modelName);
    }

    log.log("[ChatModelAdapter] Sending agent request through conversation service");

    let agentResponse: ReadableStreamDefaultReader<Uint8Array> | { type: "json"; data: unknown };
    try {
      agentResponse = await conversationService.runAgent(
        {
          ...requestBody,
          query: String(requestBody.query || ""),
          history: (requestBody.history || []) as Array<{ role: string; content: string }>,
          conversation_id: requestBody.conversation_id as number | undefined,
          minio_files: requestBody.minio_files as any,
          agent_id: requestBody.agent_id as number | undefined,
          model_id: requestBody.model_id as number | undefined,
          is_debug: false,
          is_resume: isResume,
          enable_plan: custom?.enablePlan === true,
          runtime_mode: isNl2Agent ? "nl2agent" : undefined,
        },
        abortSignal,
        (conversationId) => {
          const numericId = Number(conversationId);
          if (!Number.isNaN(numericId) && numericId > 0 && onServerConversationId) {
            onServerConversationId(
              String(numericId),
              !isResume && !hasServerConversationId ? query : undefined,
            );
          }
        },
      );
    } catch (error: unknown) {
      if (
        error instanceof Error &&
        (error.name === "AbortError" || error.message === "请求已被取消")
      ) {
        log.log("[ChatModelAdapter] Request aborted by user");
        return;
      }
      log.error("[ChatModelAdapter] Agent request failed:", error);
      throw error;
    }

    if ("type" in agentResponse) {
      log.log("[ChatModelAdapter] JSON response (resume finished):", agentResponse.data);
      return;
    }

    const reader = agentResponse;
    const decoder = new TextDecoder();
    let buffer = "";

    let currentReasoningPart: ReturnType<typeof makeReasoningPart> | null =
      null;

    const contentParts: any[] = [];

    // Sub-agent tracking. The streaming adapter no longer maintains a
    // ``subagent-group`` part type: instead it stamps a ``metadata`` object
    // onto every reasoning / tool-call / source part emitted while a
    // sub-agent is running. ``MessagePrimitive.GroupedParts`` in
    // ``thread.tsx`` reads that metadata via its ``groupBy`` callback and
    // clusters the nested parts inside a ``group-subagent-<id>-<runId>``
    // header (rendered as a collapsible card).
    //
    // ``runId`` distinguishes parallel invocations of the same sub-agent:
    // every ``subagent_start`` allocates a fresh run id so two simultaneous
    // calls to e.g. the same weather helper produce two independent groups
    // rather than being merged.
    interface ActiveSubAgent {
      runId: string;
      agentId: number | string;
      agentName: string;
      task?: string;
      depth: number;
      isRunning: boolean;
    }
    const subAgentStack: ActiveSubAgent[] = [];
    let subAgentRunCounter = 0;
    const currentSubAgent = (): ActiveSubAgent | null =>
      subAgentStack.length > 0
        ? subAgentStack[subAgentStack.length - 1]
        : null;
    const buildMetadata = (): SubAgentPartMetadata | null => {
      const top = currentSubAgent();
      if (!top) return null;
      return {
        subagentId: top.agentId,
        runId: top.runId,
        agentName: top.agentName,
        depth: top.depth,
        task: top.task,
        isRunning: top.isRunning,
      };
    };
    const flushOpenReasoning = () => {
      if (currentReasoningPart) {
        currentReasoningPart.status = { type: "done" };
        contentParts.push(currentReasoningPart);
        currentReasoningPart = null;
      }
    };

    // Accumulate search sources and search images across the entire stream.
    // After final_answer these are emitted as source / image parts at the end
    // of the message. The same data is also attached to the most recent
    // tool call so it can be rendered inline within `ToolFallback`.
    //
    // Preserves cite_index for [[b1]] → source registry linkage.
    const searchSourcesAccumulator: SearchSource[] = [];
    const searchImagesAccumulator: string[] = [];
    let skillFileAttachments: CompleteAttachment[] = [];
    let nl2a: Nl2aMessage | undefined;
    let verificationPanel: VerificationPanelPart | null = null;

    const updateVerificationPanel = (result: VerificationContent): boolean => {
      if (!verificationPanel) {
        // The final-answer verifier emits `start` before evaluating the answer.
        // Earlier step-level checks must not create a final verification panel.
        if (result.phase !== "start") return false;
        verificationPanel = {
          type: "verification-panel",
          results: [],
          completed: false,
        };
        contentParts.push(verificationPanel);
      }
      verificationPanel.results.push(result);
      return true;
    };

    const completeVerificationPanel = () => {
      if (verificationPanel) verificationPanel.completed = true;
    };

    // Generate a stable message ID for this stream so MarkdownText can look up sources
    const messageId = `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const buildStreamResult = (content: any[]): ChatModelRunResult => ({
      content,
      metadata: nl2a ? { custom: { nl2a } } : undefined,
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

          // Handle token_count - store timing for final yield
          if (chunk.type === "token_count") {
            storedTiming = buildTimingFromTokenCount(chunk.content);
            continue; // Don't yield for internal data chunks
          }

          if (chunk.type === "plan") {
            const plan = parsePlan(chunk.content);
            if (plan) planRegistry.set(plan);
            continue;
          }

          if (chunk.type === "plan_step_update") {
            const update = parsePlanStepUpdate(chunk.content);
            if (update) planRegistry.updateStep(update.stepId, update.status);
            continue;
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
            // from the leading `**步骤 N**` token at render time. Inherit
            // the current sub-agent's metadata (if any) so the part lands
            // inside the right ``group-subagent-*`` cluster.
            currentReasoningPart = makeReasoningPart(
              (currentReasoningPart?.text ?? "") + chunk.content,
              true,
              buildMetadata() ?? undefined,
            );
            yield buildStreamResult(
              currentReasoningPart
                ? [...contentParts, currentReasoningPart]
                : [...contentParts],
            );
            continue;
          }

          if (chunk.type === "skill_files") {
            skillFileAttachments = [
              ...skillFileAttachments,
              ...parseSkillFileAttachments(chunk.content, messageId),
            ];
            skillFileUploadsRegistry.set(messageId, skillFileAttachments);
            flushOpenReasoning();
            const skillPart: any = {
              type: "text",
              text: "",
              isSkillFiles: true,
              skillFileAttachments,
            };
            const skillMeta = buildMetadata();
            if (skillMeta) skillPart.metadata = skillMeta;
            contentParts.push(skillPart);
            yield buildStreamResult(contentParts);
            continue;
          }

          // Attach execution logs to their originating tool call. Ignore
          // uncorrelated logs so internal data is never rendered as chat text.
          if (chunk.type === "execution_logs") {
            attachExecutionLogsToTool(contentParts, chunk);
            yield buildStreamResult(contentParts);
            continue;
          }

          if (chunk.type === "nl2a") {
            const parsedNl2a = parseNl2aMessage(chunk);
            if (parsedNl2a) {
              nl2a = parsedNl2a;
              yield buildStreamResult(contentParts);
            }
            continue;
          }

          if (chunk.type === "automation_proposal") {
            const proposal = parseAutomationProposal(chunk.content);
            if (proposal) {
              flushOpenReasoning();
              contentParts.push({
                type: "data",
                name: "automation-proposal",
                data: proposal,
              });
              yield buildStreamResult(contentParts);
            } else {
              log.warn(
                "[ChatModelAdapter] Failed to parse automation proposal"
              );
            }
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
                  imageUrl,
                  chunk.tool_call_id
                );
              }
            } catch (e) {
              log.warn("[ChatModelAdapter] Failed to parse picture_web:", e);
            }
            // Do NOT yield image parts inline — they are emitted globally after
            // final_answer below.
            continue;
          }

          // Aggregate all verification events into one live panel. The first
          // `start` event creates the panel; subsequent events update its results.
          if (chunk.type === "verification") {
            const parsed = parseVerification(chunk);
            if (parsed) {
              flushOpenReasoning();
              if (updateVerificationPanel(parsed)) {
                yield buildStreamResult(contentParts);
              }
            }
            continue;
          }

          // The final answer (or other terminal events) terminates the self-check lifecycle.
          // Mark the existing panel complete before exposing terminal output.
          if (
            chunk.type === "final_answer" ||
            chunk.type === "error" ||
            chunk.type === "agent_finish" ||
            chunk.type === "max_steps_reached"
          ) {
            completeVerificationPanel();
          }

          // Sub-agent boundary handling. ``subagent_start`` pushes a new
          // entry on the stack and emits a stamp ``data`` part so the
          // ``group-subagent-<id>-<runId>`` cluster appears in
          // ``MessagePrimitive.GroupedParts`` immediately (the header card
          // reads agentName / task / running from this stamp even before the
          // first reasoning chunk arrives). Subsequent reasoning/tool/source
          // parts pick up the same metadata via ``buildMetadata()``.
          // ``subagent_end`` flips ``isRunning`` on every member part and
          // clears the stack.
          if (chunk.type === "subagent_start") {
            flushOpenReasoning();
            const payload = parseSubAgentStart(chunk.content);
            const agentId =
              payload.agent_id ?? chunk.agent_id ?? `unknown-${subAgentRunCounter}`;
            subAgentRunCounter += 1;
            const runId = `run-${subAgentRunCounter}`;
            const descriptor = {
              runId,
              agentId,
              agentName: payload.agent_name || chunk.agent_name || "subagent",
              task: payload.task,
              depth:
                typeof chunk.depth === "number"
                  ? chunk.depth
                  : subAgentStack.length,
              isRunning: true,
            };
            subAgentStack.push(descriptor);
            contentParts.push({
              type: "data",
              name: "subagent-boundary",
              data: { kind: "start", ...descriptor },
              metadata: buildMetadata() ?? undefined,
            });
            yield buildStreamResult(contentParts);
            continue;
          }

          if (chunk.type === "subagent_end") {
            flushOpenReasoning();
            const payload = parseSubAgentEnd(chunk.content);
            const closing = subAgentStack.pop();
            if (closing) {
              closing.isRunning = false;
              if (payload.agent_name) closing.agentName = payload.agent_name;
              markSubAgentRunFinished(contentParts, closing.runId);
            }
            yield buildStreamResult(contentParts);
            continue;
          }

          const partType = mapChunkType(chunk.type);

          if (partType === "reasoning") {
            // Update the streaming reasoning part in-place. Carry the
            // current sub-agent's metadata through to ``groupBy`` so the
            // part clusters inside the matching ``group-subagent-*`` card.
            currentReasoningPart = makeReasoningPart(
              (currentReasoningPart?.text ?? "") + chunk.content,
              true,
              buildMetadata() ?? undefined,
            );
            yield buildStreamResult(
              currentReasoningPart
                ? [...contentParts, currentReasoningPart]
                : [...contentParts],
            );
          } else if (partType === "tool-call") {
            // Finalize any ongoing reasoning
            flushOpenReasoning();

            if (
              chunk.type === "tool-call" ||
              chunk.type === "tool" ||
              chunk.type === "parse"
            ) {
              toolCallCount++;
              const toolCallPart = buildToolCallPart(chunk);
              const toolMeta = buildMetadata();
              if (toolMeta) toolCallPart.metadata = toolMeta;
              appendToolCallPart(contentParts, toolCallPart);
            }
            yield buildStreamResult(contentParts);
          } else if (partType === "text") {
            // Non-reasoning chunk: finalize the reasoning part
            flushOpenReasoning();

            const textPart: any = {
              type: "text",
              text: chunk.content,
              ...(chunk.type === "error" && { isError: true }),
            };
            const textMeta = buildMetadata();
            if (textMeta) textPart.metadata = textMeta;
            contentParts.push(textPart);
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
                attachSearchContentToTool(
                  contentParts,
                  { url, title },
                  chunk.tool_call_id
                );
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
          if (chunk.type === "plan") {
            const plan = parsePlan(chunk.content);
            if (plan) planRegistry.set(plan);
          } else if (chunk.type === "plan_step_update") {
            const update = parsePlanStepUpdate(chunk.content);
            if (update) planRegistry.updateStep(update.stepId, update.status);
          } else if (chunk.type === "execution_logs") {
            attachExecutionLogsToTool(contentParts, chunk);
            yield buildStreamResult(contentParts);
          } else if (chunk.type === "nl2a") {
            const parsedNl2a = parseNl2aMessage(chunk);
            if (parsedNl2a) {
              nl2a = parsedNl2a;
              yield buildStreamResult(contentParts);
            }
          } else if (chunk.type === "automation_proposal") {
            const proposal = parseAutomationProposal(chunk.content);
            if (proposal) {
              if (currentReasoningPart) {
                currentReasoningPart.status = { type: "done" };
                contentParts.push(currentReasoningPart);
                currentReasoningPart = null;
              }
              contentParts.push({
                type: "data",
                name: "automation-proposal",
                data: proposal,
              });
              yield buildStreamResult(contentParts);
            }
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
                  imageUrl,
                  chunk.tool_call_id
                );
              }
            } catch (e) {
              log.warn("[ChatModelAdapter] Failed to parse picture_web:", e);
            }
          } else if (chunk.type === "verification") {
            const parsed = parseVerification(chunk);
            if (parsed) {
              if (currentReasoningPart) {
                currentReasoningPart.status = { type: "done" };
                contentParts.push(currentReasoningPart);
                currentReasoningPart = null;
              }
              if (updateVerificationPanel(parsed)) {
                yield buildStreamResult(contentParts);
              }
            }
          } else {
            if (chunk.type === "final_answer") {
              completeVerificationPanel();
            }
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
              contentParts.push({
                type: "text",
                text: chunk.content,
                ...(chunk.type === "error" && { isError: true }),
              });
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
                  attachSearchContentToTool(
                  contentParts,
                  { url, title },
                  chunk.tool_call_id
                );
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
      flushOpenReasoning();
      // Defensive: mark any still-open sub-agent instances as no longer
      // running. The streaming adapter expects balanced starts/ends; if
      // upstream failed mid-flight we surface the partial output instead of
      // leaving dangling groups.
      for (const open of subAgentStack) {
        open.isRunning = false;
        markSubAgentRunFinished(contentParts, open.runId);
      }
      subAgentStack.length = 0;

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

      const finalResult = buildStreamResult(contentParts);
      const timingResult =
        storedTiming ??
        buildTimingResult(streamStartTime, firstTokenTime, toolCallCount);
      yield {
        ...finalResult,
        messageId,
        metadata: {
          ...finalResult.metadata,
          ...timingResult.metadata,
        },
      } as any;
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
