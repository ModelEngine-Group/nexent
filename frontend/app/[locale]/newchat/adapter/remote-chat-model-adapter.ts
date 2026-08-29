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
import type { SkillParam, ToolParam } from "@/types/agentConfig";

// Backend SSE chunk format
interface ImageMetadata {
  source_file?: string;
  image_url?: string;
}

function parseImageMetadata(value: unknown): ImageMetadata | null {
  if (typeof value !== "string") return null;

  try {
    const metadata = JSON.parse(value) as ImageMetadata;
    return typeof metadata.image_url === "string" ? metadata : null;
  } catch {
    return null;
  }
}

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
  // Stable identifier produced at the SDK layer for each sub-agent invocation.
  // It travels on every chunk emitted while that sub-agent is running so the
  // frontend can route streaming content to the matching card even when
  // sibling sub-agents execute in parallel.
  invocation_id?: string;
  path?: string;
  block_id?: string;
  origin_type?: string;
  sequence?: number;
  is_new_file?: boolean;
  paths?: string[];
}

export type Nl2SkillStreamEvent = SseChunk;

export interface Nl2SkillFileCardData {
  path: string;
  content: string;
  kind: "markdown" | "code" | "generic";
  language?: "python" | "bash";
  isStreaming: boolean;
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

export type Nl2AgentCardActionSubtype =
  | "requirement_clarification"
  | "suggested_resource_installation"
  | "installed_resource_binding";

export interface Nl2AgentCardAction {
  type: "nl2agent_card_action";
  subtype: Nl2AgentCardActionSubtype;
  agent_id: number;
  action: string;
  result: Record<string, unknown>;
}

export type Nl2AgentDraftField = "description" | Nl2aPromptField;

export type Nl2AgentStateEvent =
  | {
      event: "agent_draft_fields_saved";
      agent_id: number;
      updated_fields: Nl2AgentDraftField[];
    }
  | {
      event: "prompt_generation_failed";
      agent_id: number;
      failed_fields: Nl2aPromptField[];
    }
  | {
      event: "agent_generation_completed";
      agent_id: number;
    };

export interface Nl2aRequirementClarificationOption {
  option_id: string;
  label: string;
}

export interface Nl2aRequirementClarificationQuestion {
  question_id: string;
  question_type: "single_choice" | "multiple_choice" | "text";
  title: string;
  required: boolean;
  options: Nl2aRequirementClarificationOption[];
  allow_other: boolean;
  other_input_expanded: boolean;
}

export interface Nl2aRequirementClarificationPayload {
  subtype: "requirement_clarification";
  agent_id: number;
  questions: Nl2aRequirementClarificationQuestion[];
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

export interface Nl2aSuggestedResourceInstallationPayload {
  subtype: "suggested_resource_installation";
  agent_id: number;
  resources: Nl2aInstallableResource[];
}

export interface Nl2aInstalledResourceBindingPayload {
  subtype: "installed_resource_binding";
  agent_id: number;
  resources: Nl2aRecommendedResource[];
}

export interface Nl2aResourceCandidate {
  candidate_ref: string;
  resource_type: "tool" | "skill" | "mcp_server";
  source:
    | "LOCAL_TOOL"
    | "MCP_TOOL"
    | "INSTALLED_SKILL"
    | "NEXENT_OFFICIAL_SKILL"
    | "TENANT_SKILL_REPOSITORY"
    | "TENANT_MCP_REPOSITORY";
  name: string;
  description: string;
  requirement_ids: string[];
  score: number;
}

export type Nl2aInstallationFormKind =
  "SKILL_CONFIG" | "MCP_REMOTE" | "MCP_CONTAINER";

export interface Nl2aResourceInstallationOption {
  option_id: string;
  label: string;
  form_kind: Nl2aInstallationFormKind;
  config: Record<string, unknown> | SkillParam[];
}

export interface Nl2aInstallableResource {
  candidate: Nl2aResourceCandidate & {
    resource_type: "skill" | "mcp_server";
  };
  recommendation: "recommended" | "optional";
  form_kind: Nl2aInstallationFormKind;
  config: Record<string, unknown> | SkillParam[];
  installation_options: Nl2aResourceInstallationOption[];
  default_option_id: string;
}

export type Nl2aRecommendedResource =
  | {
      candidate: Nl2aResourceCandidate & { resource_type: "tool" };
      recommendation: "recommended" | "optional";
      is_bound: boolean;
      form_kind: "TOOL_CONFIG";
      config: ToolParam[];
    }
  | {
      candidate: Nl2aResourceCandidate & { resource_type: "skill" };
      recommendation: "recommended" | "optional";
      is_bound: boolean;
      form_kind: "SKILL_CONFIG";
      config: SkillParam[];
    };

export type Nl2aPromptField =
  | "duty_prompt"
  | "constraint_prompt"
  | "few_shots_prompt"
  | "greeting_message"
  | "example_questions";

export type Nl2aPayload =
  | Nl2aRequirementClarificationPayload
  | Nl2aLocalMcpRecommendationPayload
  | Nl2aAgentDraftPayload
  | Nl2aSuggestedResourceInstallationPayload
  | Nl2aInstalledResourceBindingPayload;

export interface Nl2aMessage {
  type: "nl2a";
  tool_name?: string;
  content: Nl2aPayload;
}

interface NexentRunConfig {
  threadId?: string;
  onServerConversationId?: (serverId: string, initialQuestion?: string) => void;
  onGenerationStopped?: (conversationId: number) => void;
  onRunId?: (runId: string) => void;
  resume?: boolean;
  agentId?: number | string;
  agentVersionNo?: number;
  enablePlan?: boolean;
  runtimeMode?: "nl2agent" | "nl2skill" | "agent-debug";
  knowledgeScope?: import("@/types/knowledgeScope").ConversationKnowledgeScope;
  onKnowledgeScopeResolved?: (
    resolution: import("@/types/knowledgeScope").KnowledgeScopeResolution
  ) => void;
  draftSnapshot?: Record<string, unknown>;
  complexity?: "simple" | "complicated";
  language?: "zh" | "en";
  onNl2SkillEvent?: (event: Nl2SkillStreamEvent) => void;
  onNl2AgentState?: (event: Nl2AgentStateEvent) => void;
  onNl2AgentStopped?: (agentId: number) => void;
  modelId?: number;
  runtimeMetadata?: Record<string, unknown>;
  runtimeMetadataVersion?: number;
  onRuntimeMetadataSent?: (version?: number) => void;
}

function notifyKnowledgeScopeResolved(
  content: unknown,
  callback: NexentRunConfig["onKnowledgeScopeResolved"]
): void {
  if (!callback) return;
  try {
    const resolution =
      typeof content === "string" ? JSON.parse(content) : content;
    if (
      resolution &&
      typeof resolution === "object" &&
      Array.isArray((resolution as { warnings?: unknown }).warnings)
    ) {
      callback(
        resolution as import("@/types/knowledgeScope").KnowledgeScopeResolution
      );
    }
  } catch (error) {
    log.warn(
      "[ChatModelAdapter] Failed to parse knowledge_scope_resolved:",
      error
    );
  }
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
  invocation_id?: string;
}

interface SubAgentEndPayload {
  agent_id?: number | string | null;
  agent_name?: string;
  invocation_id?: string;
}

function parseSubAgentStart(content: string): SubAgentStartPayload {
  if (!content) return {};
  try {
    const parsed = JSON.parse(content);
    if (parsed && typeof parsed === "object")
      return parsed as SubAgentStartPayload;
  } catch {
    // Backwards-compat: legacy SUBAGENT_START chunks carried plain task text.
  }
  return { task: content };
}

function parseSubAgentEnd(content: string): SubAgentEndPayload {
  if (!content) return {};
  try {
    const parsed = JSON.parse(content);
    if (parsed && typeof parsed === "object")
      return parsed as SubAgentEndPayload;
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
  metadata?: SubAgentPartMetadata
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

interface FileUpload {
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
  file_size_bytes?: number;
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

function parseFileAttachments(
  content: string,
  messageId: string
): CompleteAttachment[] {
  try {
    const payload = JSON.parse(content) as {
      file_uploads?: FileUpload[];
      skill_file_uploads?: FileUpload[];
    };
    const fileUploads = Array.isArray(payload.file_uploads)
      ? payload.file_uploads
      : payload.skill_file_uploads;
    if (!Array.isArray(fileUploads)) return [];

    const attachments: CompleteAttachment[] = fileUploads.map((file, index) => {
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
        size: file.file_size ?? file.file_size_bytes ?? file.size,
      } as unknown as CompleteAttachment;
    });

    return attachments;
  } catch (error) {
    log.warn("[ChatModelAdapter] Failed to parse file_uploads:", error);
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
 * | files                        | (attachment) | File upload completion             |
 * | token_count                  | (internal)   | Token usage data for timing        |
 * | conversation_created          | (skipped)    | Internal event, not surfaced       |
 * | status                       | (skipped)    | Internal status, not surfaced       |
 * | search_content_placeholder   | (skipped)    | Internal placeholder, not surfaced  |
 */
export function isReasoningChunkType(type: string): boolean {
  return (
    type === "reasoning" ||
    type === "model_output_thinking" ||
    type === "model_thinking_output" ||
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
    case "model_output":
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
    case "knowledge_scope_resolved":
    case "other":
    case "agent_new_run":
    case "token_count":
    case "step_count":
    case "parse":
    case "card":
    case "nl2a":
    case "nl2a_state":
    case "files":
    case "skill_files": // Backward compatibility during rolling upgrades
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
    const content = JSON.parse(chunk.content) as Nl2aPayload;
    if (content.subtype === "requirement_clarification") {
      if (
        !Number.isInteger(content.agent_id) ||
        content.agent_id <= 0 ||
        !Array.isArray(content.questions) ||
        content.questions.length === 0 ||
        content.questions.length > 5
      ) {
        log.warn("[ChatModelAdapter] Ignored invalid clarification payload");
        return null;
      }
    }
    if (content.subtype === "installed_resource_binding") {
      if (
        !Number.isInteger(content.agent_id) ||
        content.agent_id <= 0 ||
        !Array.isArray(content.resources) ||
        content.resources.length > 12 ||
        content.resources.some(
          (resource) =>
            !resource?.candidate?.candidate_ref ||
            !["tool", "skill"].includes(resource.candidate.resource_type) ||
            !["recommended", "optional"].includes(resource.recommendation) ||
            typeof resource.is_bound !== "boolean" ||
            !Array.isArray(resource.config)
        )
      ) {
        log.warn("[ChatModelAdapter] Ignored invalid binding-card payload");
        return null;
      }
    }
    if (content.subtype === "suggested_resource_installation") {
      if (
        !Number.isInteger(content.agent_id) ||
        content.agent_id <= 0 ||
        !Array.isArray(content.resources) ||
        content.resources.length === 0 ||
        content.resources.length > 12 ||
        content.resources.some(
          (resource) =>
            !resource?.candidate?.candidate_ref ||
            !["skill", "mcp_server"].includes(
              resource.candidate.resource_type
            ) ||
            !Array.isArray(resource.installation_options) ||
            resource.installation_options.length === 0 ||
            !resource.default_option_id ||
            !resource.installation_options.some(
              (option) => option.option_id === resource.default_option_id
            )
        )
      ) {
        log.warn(
          "[ChatModelAdapter] Ignored invalid installation-card payload"
        );
        return null;
      }
    }
    return {
      type: "nl2a",
      tool_name: chunk.tool_name,
      content,
    };
  } catch (error) {
    log.warn("[ChatModelAdapter] Failed to parse nl2a content:", error);
    return null;
  }
}

export function parseNl2AgentState(content: string): Nl2AgentStateEvent | null {
  try {
    const parsed = JSON.parse(content) as Record<string, unknown>;
    if (!Number.isInteger(parsed.agent_id) || Number(parsed.agent_id) <= 0) {
      return null;
    }
    const promptFields = new Set<Nl2aPromptField>([
      "duty_prompt",
      "constraint_prompt",
      "few_shots_prompt",
      "greeting_message",
      "example_questions",
    ]);
    if (parsed.event === "agent_generation_completed") {
      return Object.keys(parsed).length === 2
        ? (parsed as unknown as Nl2AgentStateEvent)
        : null;
    }
    if (parsed.event === "prompt_generation_failed") {
      if (
        Object.keys(parsed).length !== 3 ||
        !Array.isArray(parsed.failed_fields) ||
        parsed.failed_fields.length === 0 ||
        parsed.failed_fields.some(
          (field) =>
            typeof field !== "string" ||
            !promptFields.has(field as Nl2aPromptField)
        ) ||
        new Set(parsed.failed_fields).size !== parsed.failed_fields.length
      ) {
        return null;
      }
      return parsed as unknown as Nl2AgentStateEvent;
    }

    const draftFields = new Set<Nl2AgentDraftField>([
      "description",
      ...promptFields,
    ]);
    if (
      parsed.event !== "agent_draft_fields_saved" ||
      Object.keys(parsed).length !== 3 ||
      !Array.isArray(parsed.updated_fields) ||
      parsed.updated_fields.length === 0 ||
      parsed.updated_fields.some(
        (field) =>
          typeof field !== "string" ||
          !draftFields.has(field as Nl2AgentDraftField)
      ) ||
      new Set(parsed.updated_fields).size !== parsed.updated_fields.length
    ) {
      return null;
    }
    return parsed as unknown as Nl2AgentStateEvent;
  } catch {
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
  item: {
    url: string;
    title: string;
    text?: string;
    sourceType?: string;
    filename?: string;
    sourceFile?: string;
    downloadUrl?: string;
    objectName?: string;
    citeIndex?: number;
    toolSign?: string;
    isImage?: boolean;
    imageKey?: string;
  },
  toolCallId: string | undefined = undefined
): boolean {
  // Images are rendered from the authenticated PICTURE_WEB source in the
  // answer and sources panel. Attaching SEARCH_CONTENT image metadata here
  // would render the same image again inside the tool call, and relative AIDP
  // ViewImage paths would be resolved against the current locale route.
  if (item.isImage) return false;

  const targetToolCall = findMostRecentToolCall(contentParts, toolCallId);
  if (!targetToolCall) return false;
  if (!targetToolCall.searchContent) {
    targetToolCall.searchContent = [];
  }
  if (item.url || item.sourceFile) {
    targetToolCall.searchContent.push(item);
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
  sourceFile?: string;
  downloadUrl?: string;
  objectName?: string;
  isImage?: boolean;
  imageKey?: string;
}
export const searchSourcesRegistry = new Map<string, SearchSource[]>();

// Maps the safe marker embedded in persisted answer markdown (for example
// /__aidp_image__/j2) to the authenticated image URL received separately via
// PICTURE_WEB. Real AIDP URLs are never exposed to the model.
export const searchImagesRegistry = new Map<
  string,
  Map<string, SearchSource>
>();

const AIDP_IMAGE_MARKER_PATTERN = /\/__aidp_image__\/([a-z]+\d+)/gi;
const MARKDOWN_IMAGE_URL_PATTERN =
  /!\[[^\]]*\]\(\s*<?([^>\s)]+)>?(?:\s+["'][^)]*["'])?\s*\)/g;

export function extractAidpImageKeys(texts: readonly string[]): string[] {
  const keys: string[] = [];
  const seen = new Set<string>();
  for (const text of texts) {
    AIDP_IMAGE_MARKER_PATTERN.lastIndex = 0;
    for (const match of text.matchAll(AIDP_IMAGE_MARKER_PATTERN)) {
      const key = match[1];
      if (!seen.has(key)) {
        seen.add(key);
        keys.push(key);
      }
    }
  }
  return keys;
}

export function extractMarkdownImageUrls(texts: readonly string[]): string[] {
  const urls: string[] = [];
  const seen = new Set<string>();
  for (const text of texts) {
    MARKDOWN_IMAGE_URL_PATTERN.lastIndex = 0;
    for (const match of text.matchAll(MARKDOWN_IMAGE_URL_PATTERN)) {
      const url = match[1];
      if (!seen.has(url)) {
        seen.add(url);
        urls.push(url);
      }
    }
  }
  return urls;
}

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
      index === stepIndex ? { ...step, status } : step
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

export function parsePlanStepUpdate(
  content: string
): { stepId: string; status: string } | null {
  try {
    const payload = JSON.parse(content) as {
      step_id?: string | number;
      status?: string;
    };
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
export function parseVerification(chunk: {
  content: string;
}): VerificationContent | null {
  try {
    const data = JSON.parse(chunk.content);
    return {
      phase: String(data.phase || "start"),
      event: String(data.event || "unknown"),
      round: Number(data.round || 0),
      severity: String(data.severity || "info"),
      score: Number(data.score ?? 1.0),
      failed_criteria: Array.isArray(data.failed_criteria)
        ? data.failed_criteria.map(String)
        : [],
      repair_instruction: String(data.repair_instruction ?? ""),
      user_visible_note: String(data.user_visible_note ?? ""),
      message: String(data.message ?? ""),
      passed: Boolean(data.passed ?? false),
    };
  } catch {
    log.warn(
      "[ChatModelAdapter] Failed to parse verification content:",
      chunk.content
    );
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
 * Collects interleaved parts for each sub-agent invocation into one stable
 * contiguous segment. The first occurrence of an invocation determines the
 * segment position; the original order inside that invocation is preserved.
 */
export function collapseSubAgentParts(parts: any[]): any[] {
  const groupedParts = new Map<string, any[]>();
  const emittedRuns = new Set<string>();
  const collapsed: any[] = [];

  for (const part of parts) {
    const runId = part?.metadata?.runId;
    if (!runId) {
      collapsed.push(part);
      continue;
    }

    let group = groupedParts.get(runId);
    if (!group) {
      group = [];
      groupedParts.set(runId, group);
    }
    group.push(part);

    if (emittedRuns.has(runId)) continue;
    emittedRuns.add(runId);
    collapsed.push(group);
  }

  return collapsed.flat();
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

/**
 * Clears the global step token counts registry and resets the shared plan
 * state. Called from `remoteChatModelAdapter.run()` so a fresh assistant
 * turn never inherits the previous run's plan panel.
 */
export function clearStepTokenCounts(): void {
  stepTokenCounts.length = 0;
  accumulatedDuration = 0;
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
    const isNl2Skill = custom?.runtimeMode === "nl2skill";
    const isAgentDebug = custom?.runtimeMode === "agent-debug";
    const isEphemeralRuntime = isNl2Agent || isNl2Skill || isAgentDebug;
    const serverThreadId = custom?.threadId;
    const onServerConversationId = custom?.onServerConversationId;
    const onRunId = custom?.onRunId;
    const isResume = !isEphemeralRuntime && custom?.resume === true;
    const nl2AgentId =
      typeof custom?.agentId === "string"
        ? Number(custom.agentId)
        : custom?.agentId;
    if (
      isNl2Agent &&
      (!Number.isInteger(nl2AgentId) || Number(nl2AgentId) <= 0)
    ) {
      log.warn("[ChatModelAdapter] NL2Agent requires an editable Agent ID");
      return;
    }

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
    const lastUserCustom =
      isNl2Agent && lastUserIndex >= 0
        ? (messages[lastUserIndex].metadata?.custom as
            | {
                nl2agentCardAction?: Nl2AgentCardAction;
              }
            | undefined)
        : undefined;
    const structuredNl2AgentInput = lastUserCustom?.nl2agentCardAction;
    if (
      structuredNl2AgentInput &&
      structuredNl2AgentInput.agent_id !== nl2AgentId
    ) {
      log.warn("[ChatModelAdapter] Ignored mismatched NL2Agent action ID");
      return;
    }
    const query = structuredNl2AgentInput
      ? JSON.stringify(structuredNl2AgentInput)
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
      const customMetadata = isNl2Agent
        ? (msg.metadata?.custom as
            { nl2agentCardAction?: Nl2AgentCardAction } | undefined)
        : undefined;
      const text = customMetadata?.nl2agentCardAction
        ? JSON.stringify(customMetadata.nl2agentCardAction)
        : extractTextContent([msg]);
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
      is_debug: isAgentDebug,
    };
    const numericServerThreadId = Number(serverThreadId);
    const hasServerConversationId =
      Number.isInteger(numericServerThreadId) && numericServerThreadId > 0;
    if (!isEphemeralRuntime && hasServerConversationId) {
      requestBody.conversation_id = numericServerThreadId;
    }

    // Pass selected agent if provided via custom (set by the page wrapper)
    if (
      (isAgentDebug || isNl2Agent || !isEphemeralRuntime) &&
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
    if (!isResume && !isEphemeralRuntime && custom?.knowledgeScope) {
      requestBody.knowledge_scope = custom.knowledgeScope;
    }

    // Pass selected model if provided via ModelContext (registered by ModelSelector)
    // For agent-debug mode, prefer the model passed via custom (from the compare panel selector)
    const modelName = context.config?.modelName;
    const modelIdFromCustom = custom?.modelId;

    if (isAgentDebug && modelIdFromCustom) {
      // Agent-debug mode: use the model from the compare panel selector
      requestBody.model_id = Number(modelIdFromCustom);
    } else if (modelName) {
      // Normal mode: use the model from ModelContext
      requestBody.model_id = Number(modelName);
    }

    log.log(
      "[ChatModelAdapter] Sending agent request through conversation service"
    );
    log.log(
      `[ChatModelAdapter] model_id=${requestBody.model_id}, isAgentDebug=${isAgentDebug}, customModelId=${modelIdFromCustom}`
    );

    let backendConversationId = hasServerConversationId
      ? numericServerThreadId
      : null;
    let backendRunId: string | null = null;
    let backendStopPromise: Promise<void> | null = null;
    let abortHandled = false;
    let userAborted = false;
    const stopBackendRun = async (runId: string | number) => {
      if (backendStopPromise) return;
      backendStopPromise = conversationService
        .stop(runId)
        .then(() => undefined)
        .catch((error) => {
          log.error(
            `[ChatModelAdapter] Failed to stop backend run ${runId}:`,
            error
          );
        });
      await backendStopPromise;
    };
    const handleAbort = () => {
      if (abortHandled) return;
      abortHandled = true;
      const abortReason = abortSignal?.reason as
        { detach?: boolean } | undefined;
      if (abortReason?.detach) {
        log.log(
          `[ChatModelAdapter] Local stream detached from conversation ${backendConversationId ?? "unknown"}`
        );
        return;
      }
      userAborted = true;
      if (backendConversationId !== null) {
        custom?.onGenerationStopped?.(backendConversationId);
      }
      const nl2AgentId = Number(custom?.agentId);
      if (isNl2Agent && Number.isInteger(nl2AgentId) && nl2AgentId > 0) {
        custom?.onNl2AgentStopped?.(nl2AgentId);
      }
      if (backendConversationId !== null) {
        void stopBackendRun(backendConversationId);
      } else if (backendRunId !== null) {
        void stopBackendRun(backendRunId);
      }
    };
    abortSignal?.addEventListener("abort", handleAbort, { once: true });
    if (abortSignal?.aborted) handleAbort();
    const cleanupAbortHandler = () => {
      abortSignal?.removeEventListener("abort", handleAbort);
    };

    let agentResponse:
      ReadableStreamDefaultReader<Uint8Array> | { type: "json"; data: unknown };
    let returnedRuntimeMetadataVersion: number | undefined;
    try {
      agentResponse = await conversationService.runAgent(
        {
          ...requestBody,
          query: String(requestBody.query || ""),
          history: (requestBody.history || []) as Array<{
            role: string;
            content: string;
          }>,
          conversation_id: requestBody.conversation_id as number | undefined,
          minio_files: requestBody.minio_files as any,
          agent_id: requestBody.agent_id as number | undefined,
          version_no: custom?.agentVersionNo,
          is_debug: isAgentDebug,
          is_resume: isResume,
          enable_plan: custom?.enablePlan === true,
          knowledge_scope: requestBody.knowledge_scope as
            | import("@/types/knowledgeScope").ConversationKnowledgeScope
            | undefined,
          runtime_mode: isNl2Agent
            ? "nl2agent"
            : isNl2Skill
              ? "nl2skill"
              : undefined,
          draft_snapshot: isNl2Skill ? custom?.draftSnapshot : undefined,
          complexity: isNl2Skill ? custom?.complexity : undefined,
          language: isNl2Skill ? custom?.language : undefined,
          model_id: isNl2Skill
            ? (custom?.modelId ?? (requestBody.model_id as number | undefined))
            : (requestBody.model_id as number | undefined),
          metadata: custom?.runtimeMetadata,
          expected_metadata_version: custom?.runtimeMetadataVersion,
        },
        abortSignal,
        (conversationId) => {
          const numericId = Number(conversationId);
          if (!Number.isNaN(numericId) && numericId > 0) {
            backendConversationId = numericId;
            if (abortSignal?.aborted) {
              custom?.onGenerationStopped?.(numericId);
              void stopBackendRun(numericId);
            }
          }
          if (numericId > 0 && onServerConversationId) {
            onServerConversationId(
              String(numericId),
              !isResume && !hasServerConversationId ? query : undefined
            );
          }
        },
        (version) => {
          returnedRuntimeMetadataVersion = version;
        },
        (runId) => {
          backendRunId = runId;
          onRunId?.(runId);
          if (abortSignal?.aborted) {
            void stopBackendRun(runId);
          }
        }
      );
      if (custom?.runtimeMetadata !== undefined) {
        custom.onRuntimeMetadataSent?.(returnedRuntimeMetadataVersion);
      }
    } catch (error: unknown) {
      cleanupAbortHandler();
      if (
        error instanceof Error &&
        (error.name === "AbortError" || error.message === "请求已被取消")
      ) {
        if (abortSignal?.aborted) handleAbort();
        await backendStopPromise;
        log.log("[ChatModelAdapter] Request aborted by user");
        return;
      }
      log.error("[ChatModelAdapter] Agent request failed:", error);
      throw error;
    }

    if ("type" in agentResponse) {
      cleanupAbortHandler();
      log.log(
        "[ChatModelAdapter] JSON response (resume finished):",
        agentResponse.data
      );
      return;
    }

    const reader = agentResponse;
    const decoder = new TextDecoder();
    let buffer = "";

    let currentReasoningPart: ReturnType<typeof makeReasoningPart> | null =
      null;

    // Keep one flat parts array in the exact order events are received. The
    // invocation map only tracks reasoning parts and attribution metadata;
    // it must not reorder parent and sub-agent output when parallel calls
    // interleave.
    type InvocationSlot = {
      invocationId: string;
      reasoningIdx: number | null;
    };
    const invocationSlots = new Map<string, InvocationSlot>();
    const contentParts: any[] = [];
    const nl2SkillFilePartIndices = new Map<string, number>();
    let nl2SkillSummaryPartIndex: number | null = null;
    const classifyNl2SkillFile = (
      path: string
    ): Pick<Nl2SkillFileCardData, "kind" | "language"> => {
      const extension = path.split(".").pop()?.toLowerCase();
      if (extension === "md" || extension === "markdown") {
        return { kind: "markdown" };
      }
      if (extension === "py") {
        return { kind: "code", language: "python" };
      }
      if (extension === "sh" || extension === "bash") {
        return { kind: "code", language: "bash" };
      }
      return { kind: "generic" };
    };
    const upsertNl2SkillFile = (chunk: SseChunk) => {
      const path =
        chunk.type === "skill_body" ? "SKILL.md" : chunk.path || "file.txt";
      let partIndex = nl2SkillFilePartIndices.get(path);
      if (partIndex === undefined) {
        partIndex = contentParts.length;
        contentParts.push({
          type: "data",
          name: "nl2skill-file",
          data: {
            path,
            content: "",
            ...classifyNl2SkillFile(path),
            isStreaming: true,
          },
        });
        nl2SkillFilePartIndices.set(path, partIndex);
      }
      const currentPart = contentParts[partIndex] as {
        type: "data";
        name: "nl2skill-file";
        data: Nl2SkillFileCardData;
      };
      contentParts[partIndex] = {
        ...currentPart,
        data: {
          ...currentPart.data,
          content: currentPart.data.content + (chunk.content || ""),
        },
      };
    };
    const finishNl2SkillFiles = () => {
      for (const partIndex of nl2SkillFilePartIndices.values()) {
        const currentPart = contentParts[partIndex] as {
          type: "data";
          name: "nl2skill-file";
          data: Nl2SkillFileCardData;
        };
        contentParts[partIndex] = {
          ...currentPart,
          data: { ...currentPart.data, isStreaming: false },
        };
      }
    };
    const appendNl2SkillSummary = (content: string) => {
      if (nl2SkillSummaryPartIndex === null) {
        nl2SkillSummaryPartIndex = contentParts.length;
        contentParts.push({ type: "text", text: content });
        return;
      }
      const currentPart = contentParts[nl2SkillSummaryPartIndex] as {
        type: "text";
        text: string;
      };
      contentParts[nl2SkillSummaryPartIndex] = {
        ...currentPart,
        text: currentPart.text + content,
      };
    };
    const slotForInvocation = (invocationId: string): InvocationSlot | null =>
      invocationSlots.get(invocationId) ?? null;
    const ensureSlot = (invocationId: string): InvocationSlot => {
      let slot = invocationSlots.get(invocationId);
      if (!slot) {
        slot = { invocationId, reasoningIdx: null };
        invocationSlots.set(invocationId, slot);
      }
      return slot;
    };

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
    //
    // Parallel siblings are tracked in a Map keyed by the backend's stable
    // ``invocation_id``. A LIFO stack would mis-attribute a sibling's chunks
    // when both are open simultaneously. The Map also lets us close exactly
    // the run named by a ``subagent_end.invocation_id`` regardless of which
    // sibling finished first.
    interface ActiveSubAgent {
      runId: string;
      agentId: number | string;
      agentName: string;
      task?: string;
      depth: number;
      isRunning: boolean;
      invocationId: string;
      // Reference to the per-invocation slot in ``invocationSlots`` that
      // owns this descriptor's parts list. Kept alongside the
      // descriptor so a finished invocation still routes any trailing
      // cleanup to the same slot.
      slot: InvocationSlot;
    }
    const activeSubAgents = new Map<string, ActiveSubAgent>();
    // Most-recently-touched invocation id. Used as the "active" scope for
    // streaming chunks that don't carry their own invocation_id (e.g. legacy
    // backends). Updated by every subagent_start/end and by direct chunk
    // attribution when invocation_id is present.
    let activeInvocationId: string | null = null;
    let subAgentRunCounter = 0;
    const currentSubAgent = (): ActiveSubAgent | null =>
      activeInvocationId
        ? (activeSubAgents.get(activeInvocationId) ?? null)
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
    // Helpers to activate a sub-agent scope for metadata attribution.
    const activateSubAgent = (invocationId: string) => {
      activeInvocationId = invocationId;
    };
    // Resolve the sub-agent slot for a chunk's ``invocation_id`` and
    // activate it as the current scope. Returns null when the chunk belongs
    // to the parent agent (no invocation_id, or unknown invocation_id).
    //
    // Key invariant: never fall back to a sub-agent when the chunk doesn't
    // carry a matching invocation_id. Otherwise parent-agent reasoning /
    // tool chunks that arrive interleaved with sub-agent chunks would be
    // mis-attributed to whatever sub-agent happens to be on the stack,
    // creating spurious "phantom" sub-agent cards.
    const resolveSubAgent = (
      invocationId: string | undefined
    ): ActiveSubAgent | null => {
      if (!invocationId) {
        // Parent chunks do not carry an invocation ID. Never reuse the last
        // sibling scope because parallel calls may still be active.
        activeInvocationId = null;
        return null;
      }
      const resolved = activeSubAgents.get(invocationId);
      if (!resolved) {
        // An explicit but unknown ID must never reuse the previously active
        // sibling. Treat it as parent output to prevent cross-card mixing.
        activeInvocationId = null;
        return null;
      }
      activateSubAgent(invocationId);
      return resolved;
    };

    const flushOpenReasoning = (specificInvocationId?: string | null) => {
      if (specificInvocationId) {
        const entry = activeSubAgents.get(specificInvocationId);
        if (!entry || entry.slot.reasoningIdx === null) return;
        contentParts[entry.slot.reasoningIdx].status = { type: "done" };
        entry.slot.reasoningIdx = null;
        return;
      }
      if (currentReasoningPart) {
        currentReasoningPart.status = { type: "done" };
        contentParts.push(currentReasoningPart);
        currentReasoningPart = null;
      }
    };
    const flushAllOpenReasoning = () => {
      // Final defensive close at stream end. Closes any per-invocation
      // reasoning part that was still streaming so the rendering layer
      // sees a ``done`` status on the last byte.
      for (const entry of activeSubAgents.values()) {
        if (entry.slot.reasoningIdx !== null) {
          contentParts[entry.slot.reasoningIdx].status = { type: "done" };
          entry.slot.reasoningIdx = null;
        }
      }
      if (currentReasoningPart) {
        currentReasoningPart.status = { type: "done" };
        contentParts.push(currentReasoningPart);
        currentReasoningPart = null;
      }
    };

    // Helper: build a fresh sub-agent metadata object for a given invocation.
    function subAgentMetadataFor(entry: ActiveSubAgent): SubAgentPartMetadata {
      return {
        subagentId: entry.agentId,
        runId: entry.runId,
        agentName: entry.agentName,
        depth: entry.depth,
        task: entry.task,
        isRunning: entry.isRunning,
      };
    }

    // Accumulate search sources and verified images across the stream. Images
    // are rendered at safe markers inside the answer markdown; source parts
    // remain grouped at the end for the sources panel.
    //
    // Preserves cite_index for [[b1]] → source registry linkage.
    const searchSourcesAccumulator: SearchSource[] = [];
    const searchImagesAccumulator: SearchSource[] = [];
    let skillFileAttachments: CompleteAttachment[] = [];
    let nl2a: Nl2aMessage | undefined;
    const acceptNl2aBoundary = (chunk: SseChunk): boolean => {
      const parsedNl2a = parseNl2aMessage(chunk);
      if (!parsedNl2a) return false;
      if (nl2a) {
        log.error(
          "[ChatModelAdapter] Ignored additional NL2Agent card in one run",
          {
            acceptedSubtype: nl2a.content.subtype,
            ignoredSubtype: parsedNl2a.content.subtype,
          }
        );
        return false;
      }
      nl2a = parsedNl2a;
      return true;
    };
    const deliveredNl2AgentStates = new Set<string>();
    const deliverNl2AgentState = (chunk: SseChunk) => {
      if (!isNl2Agent || userAborted) return;
      const event = parseNl2AgentState(chunk.content);
      if (!event) {
        log.warn("[ChatModelAdapter] Ignored invalid nl2a_state payload");
        return;
      }
      const eventKey = JSON.stringify(event);
      if (event.event !== "agent_draft_fields_saved") {
        if (deliveredNl2AgentStates.has(eventKey)) return;
        deliveredNl2AgentStates.add(eventKey);
      }
      custom?.onNl2AgentState?.(event);
    };
    let verificationPanel: VerificationPanelPart | null = null;

    const appendSearchImages = (imageUrls: string[]) => {
      const imageMetadata = searchSourcesAccumulator.filter(
        (source) => source.isImage
      );

      for (const imageUrl of imageUrls) {
        if (!imageUrl) continue;

        const metadata = imageMetadata[searchImagesAccumulator.length];
        const imageSource: SearchSource = {
          ...metadata,
          url: imageUrl,
          title: metadata?.title || imageUrl,
          text: metadata?.text,
          sourceType: "url",
          isImage: true,
          imageKey:
            metadata?.imageKey ||
            (metadata?.toolSign && metadata?.citeIndex !== undefined
              ? `${metadata.toolSign}${metadata.citeIndex}`
              : undefined),
        };
        searchImagesAccumulator.push(imageSource);
      }
    };

    const updateVerificationPanel = (result: VerificationContent): boolean => {
      // Each verification lifecycle begins with `start`. Create its card as
      // soon as that SSE event arrives so all following phases stream into it.
      if (result.phase === "start") {
        completeVerificationPanel();
        verificationPanel = {
          type: "verification-panel",
          results: [],
          completed: false,
        };
        contentParts.push(verificationPanel);
      }
      if (!verificationPanel) return false;
      verificationPanel.results.push(result);
      return true;
    };

    const completeVerificationPanel = () => {
      if (verificationPanel) verificationPanel.completed = true;
    };

    // Generate a stable message ID for this stream so MarkdownText can look up sources
    const messageId = `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const buildStreamResult = (content: any[]): ChatModelRunResult => ({
      content: collapseSubAgentParts(content),
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

          if (chunk.type === "knowledge_scope_resolved") {
            notifyKnowledgeScopeResolved(
              chunk.content as unknown,
              custom?.onKnowledgeScopeResolved
            );
            continue;
          }

          if (isNl2Skill) {
            custom?.onNl2SkillEvent?.(chunk);
            if (chunk.type === "skill_body" || chunk.type === "file_content") {
              flushOpenReasoning();
              upsertNl2SkillFile(chunk);
              yield buildStreamResult(contentParts);
              continue;
            }
            if (chunk.type === "summary") {
              flushOpenReasoning();
              appendNl2SkillSummary(chunk.content);
              yield buildStreamResult(contentParts);
              continue;
            }
            if (chunk.type === "done") {
              flushOpenReasoning();
              finishNl2SkillFiles();
              yield buildStreamResult(contentParts);
              continue;
            }
          }

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

          // Track timing for first content token
          if (firstTokenTime === undefined && chunk.type === "text") {
            firstTokenTime = Date.now() - streamStartTime;
          }

          if (chunk.type === "step_count") {
            // Fold `step_count` into the invocation's reasoning part text
            // so the rendering layer sees the same reasoning part shape
            // regardless of whether the data came from streaming or a
            // historical load. ReasoningTrigger extracts the step label
            // (``**步骤 N**``) at render time.
            //
            // Each parallel invocation owns a stable slot index inside
            // ``contentParts``: the first step_count (or reasoning) chunk
            // pushes a fresh reasoning part; later chunks mutate the part
            // in place. This keeps every per-invocation reasoning part
            // contiguous in the parts array, so assistant-ui's GroupedParts
            // yields a single card per invocation even when chunks
            // interleave across multiple parallel sub-agents.
            const top = resolveSubAgent(chunk.invocation_id);
            if (top) {
              if (top.slot.reasoningIdx === null) {
                const part = makeReasoningPart(
                  chunk.content,
                  true,
                  subAgentMetadataFor(top)
                );
                contentParts.push(part);
                top.slot.reasoningIdx = contentParts.length - 1;
              } else {
                contentParts[top.slot.reasoningIdx].text += chunk.content;
              }
              currentReasoningPart = null;
              yield buildStreamResult(contentParts);
            } else {
              currentReasoningPart = makeReasoningPart(
                (currentReasoningPart?.text ?? "") + chunk.content,
                true,
                undefined
              );
              yield buildStreamResult(
                currentReasoningPart
                  ? [...contentParts, currentReasoningPart]
                  : [...contentParts]
              );
            }
            continue;
          }

          if (chunk.type === "files" || chunk.type === "skill_files") {
            skillFileAttachments = [
              ...skillFileAttachments,
              ...parseFileAttachments(chunk.content, messageId),
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
            if (acceptNl2aBoundary(chunk)) {
              yield buildStreamResult(contentParts);
            }
            continue;
          }

          if (chunk.type === "nl2a_state") {
            deliverNl2AgentState(chunk);
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
              appendSearchImages(imageUrls);
            } catch (e) {
              log.warn("[ChatModelAdapter] Failed to parse picture_web:", e);
            }
            continue;
          }

          // Each verification `start` event creates a card immediately;
          // following events for that lifecycle update the same card.
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
            // Commit any pending parent reasoning BEFORE writing the final
            // answer text so the answer does not appear before its preceding
            // step thought in the merged view.
            flushOpenReasoning();
            completeVerificationPanel();
          }

          // Sub-agent boundary handling. ``subagent_start`` registers a new
          // invocation in the per-id map (so parallel siblings stay
          // independent) and emits a stamp ``data`` part so the
          // ``group-subagent-<id>-<runId>`` cluster appears in
          // ``MessagePrimitive.GroupedParts`` immediately (the header card
          // reads agentName / task / running from this stamp even before the
          // first reasoning chunk arrives). Subsequent reasoning/tool/source
          // parts pick up the same metadata via ``buildMetadata()``.
          // ``subagent_end`` flips ``isRunning`` on every member part and
          // closes exactly the invocation named by ``invocation_id`` rather
          // than blindly popping the most recent stack entry.
          if (chunk.type === "subagent_start") {
            // Commit parent reasoning before opening the first nested card so
            // the transient parent part cannot be reordered behind it.
            flushOpenReasoning();
            const payload = parseSubAgentStart(chunk.content);
            const agentId =
              payload.agent_id ??
              chunk.agent_id ??
              `unknown-${subAgentRunCounter}`;
            subAgentRunCounter += 1;
            const runId = `run-${subAgentRunCounter}`;
            const invocationId =
              payload.invocation_id ?? chunk.invocation_id ?? runId;
            const descriptor: ActiveSubAgent = {
              runId,
              agentId,
              agentName: payload.agent_name || chunk.agent_name || "subagent",
              task: payload.task,
              depth:
                typeof chunk.depth === "number"
                  ? chunk.depth
                  : activeSubAgents.size,
              isRunning: true,
              invocationId,
              slot: ensureSlot(invocationId),
            };
            activeSubAgents.set(invocationId, descriptor);
            activeInvocationId = invocationId;
            contentParts.push({
              type: "data",
              name: "subagent-boundary",
              data: { kind: "start", ...descriptor },
              metadata: subAgentMetadataFor(descriptor),
            });
            yield buildStreamResult(contentParts);
            continue;
          }

          if (chunk.type === "subagent_end") {
            const payload = parseSubAgentEnd(chunk.content);
            const invocationId = payload.invocation_id ?? chunk.invocation_id;
            const closing = invocationId
              ? activeSubAgents.get(invocationId)
              : undefined;
            if (closing) {
              closing.isRunning = false;
              if (payload.agent_name) closing.agentName = payload.agent_name;
              // Close this invocation's reasoning slot in-place so subsequent
              // sibling chunks can keep adding parts without leaving dangling
              // streaming reasoning on the finishing run.
              if (closing.slot.reasoningIdx !== null) {
                contentParts[closing.slot.reasoningIdx].status = {
                  type: "done",
                };
                closing.slot.reasoningIdx = null;
              }
              activeSubAgents.delete(invocationId!);
              markSubAgentRunFinished(contentParts, closing.runId);
            }
            // Pick the next active invocation id so subsequent reasoning /
            // tool parts default to a still-open sibling when present.
            activeInvocationId = activeSubAgents.size
              ? (activeSubAgents.keys().next().value ?? null)
              : null;
            yield buildStreamResult(contentParts);
            continue;
          }

          const partType = mapChunkType(chunk.type);

          if (partType === "reasoning") {
            // Update the streaming reasoning part in-place. Carry the
            // current sub-agent's metadata through to ``groupBy`` so the
            // part clusters inside the matching ``group-subagent-*`` card.
            //
            // Each parallel invocation owns a stable slot index in
            // ``contentParts``: the first reasoning chunk pushes a fresh
            // reasoning part at a new index; later chunks append to that
            // same part. This keeps per-invocation reasoning parts
            // contiguous in the parts array, so assistant-ui's
            // GroupedParts yields a single card per invocation even when
            // chunks interleave across multiple parallel sub-agents.
            // Use ``resolveSubAgent`` so that even when an SSE chunk
            // carries its own ``invocation_id`` (interleaved parallel
            // stream) it is routed to the correct run immediately.
            const top = resolveSubAgent(chunk.invocation_id);
            if (top) {
              if (top.slot.reasoningIdx === null) {
                const part = makeReasoningPart(
                  chunk.content,
                  true,
                  subAgentMetadataFor(top)
                );
                contentParts.push(part);
                top.slot.reasoningIdx = contentParts.length - 1;
              } else {
                contentParts[top.slot.reasoningIdx].text += chunk.content;
              }
              currentReasoningPart = null;
              yield buildStreamResult(contentParts);
            } else {
              currentReasoningPart = makeReasoningPart(
                (currentReasoningPart?.text ?? "") + chunk.content,
                true,
                undefined
              );
              yield buildStreamResult(
                currentReasoningPart
                  ? [...contentParts, currentReasoningPart]
                  : [...contentParts]
              );
            }
          } else if (partType === "tool-call") {
            // Commit parent reasoning before exposing the tool call so the
            // current streaming snapshot keeps both parts visible.
            flushOpenReasoning(chunk.invocation_id);
            // Resolve the chunk's invocation so the tool-call part is
            // attributed to the right parallel sub-agent. Sub-agent
            // reasoning parts are kept open across tool-calls (see
            // ``flushOpenReasoning``), so the merged view stays
            // contiguous and the GroupedParts coalescer keeps each
            // invocation in a single card.
            const toolMeta = resolveSubAgent(chunk.invocation_id);

            if (
              chunk.type === "tool-call" ||
              chunk.type === "tool" ||
              chunk.type === "parse"
            ) {
              toolCallCount++;
              const toolCallPart = buildToolCallPart(chunk);
              if (toolMeta) {
                toolCallPart.metadata = subAgentMetadataFor(toolMeta);
              }
              appendToolCallPart(contentParts, toolCallPart);
            }
            yield buildStreamResult(contentParts);
          } else if (partType === "text") {
            // Non-reasoning chunk. As with tool-call, attribute the part
            // to the chunk's invocation (when present) and keep any open
            // sub-agent reasoning part running so the merged view stays
            // contiguous.
            const textMeta = resolveSubAgent(chunk.invocation_id);

            const textPart: any = {
              type: "text",
              text: chunk.content,
              ...(chunk.type === "error" && { isError: true }),
            };
            if (textMeta) {
              textPart.metadata = subAgentMetadataFor(textMeta);
            }
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
                const imageMetadata = parseImageMetadata(result.text);
                const resolvedUrl = imageMetadata?.image_url || url;
                const text = imageMetadata ? "" : result.text;
                const isImage =
                  result.score_details?.chunk_type === "image" ||
                  Boolean(imageMetadata);
                const title =
                  result.title ||
                  filename ||
                  imageMetadata?.source_file ||
                  resolvedUrl;
                if (url || filename || title) {
                  searchSourcesAccumulator.push({
                    citeIndex,
                    url: resolvedUrl,
                    title,
                    text,
                    sourceType: result.source_type,
                    searchType: result.search_type,
                    toolSign: result.tool_sign,
                    filename,
                    sourceFile:
                      result.source_file || imageMetadata?.source_file,
                    downloadUrl: result.download_url,
                    objectName: result.object_name,
                    isImage,
                    imageKey: result.image_key,
                  });
                }
                attachSearchContentToTool(
                  contentParts,
                  {
                    url: resolvedUrl,
                    title,
                    text,
                    sourceType: result.source_type,
                    filename,
                    sourceFile:
                      result.source_file || imageMetadata?.source_file,
                    downloadUrl: result.download_url,
                    objectName: result.object_name,
                    citeIndex,
                    toolSign: result.tool_sign,
                    isImage,
                    imageKey: result.image_key,
                  },
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
          if (isNl2Skill) custom?.onNl2SkillEvent?.(chunk);
          if (chunk.type === "knowledge_scope_resolved") {
            notifyKnowledgeScopeResolved(
              chunk.content as unknown,
              custom?.onKnowledgeScopeResolved
            );
          } else if (
            isNl2Skill &&
            (chunk.type === "skill_body" || chunk.type === "file_content")
          ) {
            flushOpenReasoning();
            upsertNl2SkillFile(chunk);
            yield buildStreamResult(contentParts);
          } else if (isNl2Skill && chunk.type === "summary") {
            flushOpenReasoning();
            appendNl2SkillSummary(chunk.content);
            yield buildStreamResult(contentParts);
          } else if (isNl2Skill && chunk.type === "done") {
            flushOpenReasoning();
            finishNl2SkillFiles();
            yield buildStreamResult(contentParts);
          } else if (chunk.type === "plan") {
            const plan = parsePlan(chunk.content);
            if (plan) planRegistry.set(plan);
          } else if (chunk.type === "plan_step_update") {
            const update = parsePlanStepUpdate(chunk.content);
            if (update) planRegistry.updateStep(update.stepId, update.status);
          } else if (chunk.type === "execution_logs") {
            attachExecutionLogsToTool(contentParts, chunk);
            yield buildStreamResult(contentParts);
          } else if (chunk.type === "nl2a") {
            if (acceptNl2aBoundary(chunk)) {
              yield buildStreamResult(contentParts);
            }
          } else if (chunk.type === "nl2a_state") {
            deliverNl2AgentState(chunk);
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
          } else if (chunk.type === "files" || chunk.type === "skill_files") {
            skillFileAttachments = [
              ...skillFileAttachments,
              ...parseFileAttachments(chunk.content, messageId),
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
              appendSearchImages(imageUrls);
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
              // Commit any pending parent reasoning so the answer is emitted
              // after the most recent step thought instead of being reordered
              // in front of it.
              flushOpenReasoning();
              completeVerificationPanel();
            }
            const partType = mapChunkType(chunk.type);
            if (partType === "reasoning") {
              const top = resolveSubAgent(chunk.invocation_id);
              if (top) {
                if (top.slot.reasoningIdx === null) {
                  const part = makeReasoningPart(
                    chunk.content,
                    true,
                    subAgentMetadataFor(top)
                  );
                  contentParts.push(part);
                  top.slot.reasoningIdx = contentParts.length - 1;
                } else {
                  contentParts[top.slot.reasoningIdx].text += chunk.content;
                }
                currentReasoningPart = null;
                yield buildStreamResult(contentParts);
              } else {
                currentReasoningPart = makeReasoningPart(
                  (currentReasoningPart?.text ?? "") + chunk.content,
                  true
                );
                yield buildStreamResult([
                  ...contentParts,
                  currentReasoningPart,
                ] as any);
              }
            } else if (partType === "tool-call") {
              // Commit parent reasoning before exposing the tool call so the
              // final buffered SSE chunk follows the same streaming behavior.
              flushOpenReasoning(chunk.invocation_id);
              if (
                chunk.type === "tool-call" ||
                chunk.type === "tool" ||
                chunk.type === "parse"
              ) {
                toolCallCount++;
                const toolCallPart = buildToolCallPart(chunk);
                const toolMeta = resolveSubAgent(chunk.invocation_id);
                if (toolMeta)
                  toolCallPart.metadata = {
                    subagentId: toolMeta.agentId,
                    runId: toolMeta.runId,
                    agentName: toolMeta.agentName,
                    depth: toolMeta.depth,
                    task: toolMeta.task,
                    isRunning: toolMeta.isRunning,
                  };
                appendToolCallPart(contentParts, toolCallPart);
              }
              yield buildStreamResult(contentParts);
            } else if (partType === "text") {
              const textPart: any = {
                type: "text",
                text: chunk.content,
                ...(chunk.type === "error" && { isError: true }),
              };
              const textMeta = resolveSubAgent(chunk.invocation_id);
              if (textMeta)
                textPart.metadata = {
                  subagentId: textMeta.agentId,
                  runId: textMeta.runId,
                  agentName: textMeta.agentName,
                  depth: textMeta.depth,
                  task: textMeta.task,
                  isRunning: textMeta.isRunning,
                };
              contentParts.push(textPart);
              yield buildStreamResult(contentParts);
            } else if (partType === "source") {
              try {
                const searchResults = JSON.parse(chunk.content);
                const results = Array.isArray(searchResults)
                  ? searchResults
                  : [searchResults];
                for (const result of results) {
                  const url = result.url || "";
                  const filename = result.filename || "";
                  const citeIndex = result.cite_index ?? result.citeIndex ?? 0;
                  const imageMetadata = parseImageMetadata(result.text);
                  const resolvedUrl = imageMetadata?.image_url || url;
                  const text = imageMetadata ? "" : result.text;
                  const isImage =
                    result.score_details?.chunk_type === "image" ||
                    Boolean(imageMetadata);
                  const title =
                    result.title ||
                    filename ||
                    imageMetadata?.source_file ||
                    resolvedUrl;
                  if (url || filename || title) {
                    searchSourcesAccumulator.push({
                      citeIndex,
                      url: resolvedUrl,
                      title,
                      text,
                      sourceType: result.source_type,
                      searchType: result.search_type,
                      toolSign: result.tool_sign,
                      filename,
                      sourceFile:
                        result.source_file || imageMetadata?.source_file,
                      downloadUrl: result.download_url,
                      objectName: result.object_name,
                      isImage,
                      imageKey: result.image_key,
                    });
                  }
                  attachSearchContentToTool(
                    contentParts,
                    {
                      url: resolvedUrl,
                      title,
                      text,
                      sourceType: result.source_type,
                      filename,
                      sourceFile:
                        result.source_file || imageMetadata?.source_file,
                      downloadUrl: result.download_url,
                      objectName: result.object_name,
                      citeIndex,
                      toolSign: result.tool_sign,
                      isImage,
                      imageKey: result.image_key,
                    },
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
      flushAllOpenReasoning();
      finishNl2SkillFiles();
      // Defensive: mark any still-open sub-agent instances as no longer
      // running. The streaming adapter expects balanced starts/ends; if
      // upstream failed mid-flight we surface the partial output instead of
      // leaving dangling groups.
      for (const open of activeSubAgents.values()) {
        open.isRunning = false;
        markSubAgentRunFinished(contentParts, open.runId);
      }
      activeSubAgents.clear();
      activeInvocationId = null;

      // SEARCH_CONTENT and PICTURE_WEB can reach the browser in either order.
      // Resolve them only after the stream is complete, using the markers that
      // actually survived into the final answer as the authoritative keys.
      const answerImageKeys = extractAidpImageKeys(
        contentParts.flatMap((part) =>
          part?.type === "text" && typeof part.text === "string"
            ? [part.text]
            : []
        )
      );
      const answerImageUrls = new Set(
        extractMarkdownImageUrls(
          contentParts.flatMap((part) =>
            part?.type === "text" && typeof part.text === "string"
              ? [part.text]
              : []
          )
        )
      );
      const imageMetadata = searchSourcesAccumulator.filter(
        (source) => source.isImage
      );
      for (const [index, image] of searchImagesAccumulator.entries()) {
        const metadata =
          imageMetadata.find((source) => {
            if (!source.url) return false;
            const relativeUrl = source.url.replace(/^\/+/, "");
            return image.url.endsWith(relativeUrl);
          }) ?? imageMetadata[index];
        const imageKey =
          metadata?.imageKey ||
          (metadata?.toolSign && metadata.citeIndex !== undefined
            ? `${metadata.toolSign}${metadata.citeIndex}`
            : undefined) ||
          answerImageKeys[index] ||
          image.imageKey;
        searchImagesAccumulator[index] = {
          ...image,
          ...metadata,
          url: image.url,
          title: metadata?.title || image.title,
          text: metadata?.text || image.text,
          sourceType: "url",
          isImage: true,
          imageKey,
        };
      }

      const imageMap = new Map<string, SearchSource>();
      for (const image of searchImagesAccumulator) {
        if (image.imageKey) imageMap.set(image.imageKey, image);
      }
      if (imageMap.size > 0) searchImagesRegistry.set(messageId, imageMap);

      searchSourcesRegistry.set(messageId, [
        ...searchSourcesAccumulator.filter((source) => !source.isImage),
        ...searchImagesAccumulator,
      ]);

      // Web search tools return verified images through PICTURE_WEB, but the
      // model does not always include image markdown in its answer. Render
      // those otherwise-unreferenced images after the answer, outside the
      // grouped source block. AIDP markers and explicit markdown images keep
      // their original inline position and are not duplicated here.
      for (const image of searchImagesAccumulator) {
        if (
          answerImageUrls.has(image.url) ||
          ((image.url.includes("/KnowledgeBase/Tenants/") ||
            image.url.includes("/ind-aidp/images/")) &&
            image.imageKey &&
            answerImageKeys.includes(image.imageKey))
        ) {
          continue;
        }
        // Use assistant-ui's native image part. Custom fields attached to an
        // empty text part are not preserved when history is reconstructed.
        contentParts.push({ type: "image", image: image.url });
      }

      // Emit one contiguous source block after the answer and image cards.
      // Also register it so MarkdownText can resolve citation markers.
      if (searchSourcesAccumulator.length > 0) {
        for (const source of searchSourcesAccumulator) {
          if (source.isImage) continue;
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

      for (const image of searchImagesAccumulator) {
        contentParts.push({
          type: "source",
          sourceType: "url",
          url: image.url,
          title: image.title,
          text: image.text,
          citeIndex: image.citeIndex,
          isImage: true,
          imageKey: image.imageKey,
          messageId,
        });
      }

      const finalResult = buildStreamResult(
        collapseSubAgentParts(contentParts)
      );
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
      cleanupAbortHandler();
      if (isNl2Skill) {
        custom?.onNl2SkillEvent?.({
          type: "stream_closed",
          content: "",
        });
      }
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
