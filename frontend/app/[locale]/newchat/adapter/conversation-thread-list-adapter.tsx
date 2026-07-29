"use client";

import type { FC, MutableRefObject, PropsWithChildren } from "react";
import { useMemo } from "react";
import {
  ExportedMessageRepository,
  RuntimeAdapterProvider,
  useAui,
} from "@assistant-ui/react";
import type {
  ChatModelRunOptions,
  ChatModelRunResult,
  CompleteAttachment,
  ExportedMessageRepositoryItem,
  GenericThreadHistoryAdapter,
  MessageFormatAdapter,
  RemoteThreadListAdapter,
  ThreadHistoryAdapter,
} from "@assistant-ui/react";
import { conversationService } from "@/services/conversationService";
import { storageService } from "@/services/storageService";
import type { ConversationListItem } from "@/types/conversation";
import type { ApiMessage } from "@/types/conversation";
import log from "@/lib/logger";
import { createAssistantStream } from "assistant-stream";
import type { AttachmentType } from "../utils/attachment-type";
import {
  attachExecutionLogsToTool,
  attachSearchContentToTool,
  attachSearchImageToTool,
  buildToolCallPart,
  conversationSourcesRegistry,
  isReasoningChunkType,
  skillFileUploadsRegistry,
  parseStepTokenCount,
  parsePlan,
  parsePlanStepUpdate,
  planRegistry,
  type PlanData,
  type SearchSource,
  type StepTokenCount,
} from "./remote-chat-model-adapter";
import { agUIChatModelAdapter } from "./ag-ui-chat-model-adapter";
import {
  createA2UIDataPart,
  markA2UIFormSubmitted,
  normalizeLegacyA2UIActionText,
  processA2UIEnvelope,
} from "../a2ui/runtime";
import { parseA2UIFormSubmissionState } from "../a2ui/form-submission-store";

type RemoteThreadInitializeResponse = Awaited<
  ReturnType<RemoteThreadListAdapter["initialize"]>
>;
type RemoteThreadListResponse = Awaited<
  ReturnType<RemoteThreadListAdapter["list"]>
>;
type RemoteThreadMetadata = Awaited<
  ReturnType<RemoteThreadListAdapter["fetch"]>
>;

const historicalPlanCache = new Map<string, PlanData | null>();
type HistoricalChatMode = "planning" | "execution";

let activeHistoricalConversationId: string | undefined;
let activeHistoricalChatModeConversationId: string | undefined;
let historicalChatModeListener:
  | ((mode: HistoricalChatMode) => void)
  | undefined;
const historicalChatModeCache = new Map<string, HistoricalChatMode>();

export const restoreHistoricalPlan = (conversationId?: string): void => {
  activeHistoricalConversationId = conversationId;
  if (!conversationId) {
    planRegistry.set(null);
    return;
  }
  planRegistry.set(historicalPlanCache.get(conversationId) ?? null);
};

export const setHistoricalChatModeListener = (
  listener: ((mode: HistoricalChatMode) => void) | undefined
): void => {
  historicalChatModeListener = listener;
};

export const restoreHistoricalChatMode = (conversationId?: string): void => {
  activeHistoricalChatModeConversationId = conversationId;
  historicalChatModeListener?.(
    conversationId
      ? (historicalChatModeCache.get(conversationId) ?? "execution")
      : "execution"
  );
};

const cacheHistoricalChatMode = (
  conversationId: string,
  chatMode: HistoricalChatMode | undefined
): void => {
  const mode = chatMode ?? "execution";
  historicalChatModeCache.set(conversationId, mode);
  if (activeHistoricalChatModeConversationId === conversationId) {
    historicalChatModeListener?.(mode);
  }
};

const toAttachmentType = (rawType: string): AttachmentType => {
  const normalizedType = rawType.toLowerCase();
  if (normalizedType === "image" || normalizedType.startsWith("image/")) {
    return "image";
  }
  if (
    normalizedType === "document" ||
    normalizedType.startsWith("text/") ||
    normalizedType.includes("pdf") ||
    normalizedType.includes("word") ||
    normalizedType.includes("spreadsheet") ||
    normalizedType.includes("presentation") ||
    normalizedType.includes("json")
  ) {
    return "document";
  }
  return "file";
};

const toToolSearchItem = (
  value: unknown
): { url: string; title: string } | null => {
  if (typeof value !== "object" || value === null) return null;

  const item = value as Record<string, unknown>;
  const url = typeof item.url === "string" ? item.url : "";
  const title =
    (typeof item.title === "string" && item.title) ||
    (typeof item.filename === "string" && item.filename) ||
    url;
  return url ? { url, title } : null;
};

const parseSearchPlaceholderUnitId = (content: string): string | null => {
  try {
    const value = JSON.parse(content) as { unit_id?: unknown };
    return value.unit_id === undefined || value.unit_id === null
      ? null
      : String(value.unit_id);
  } catch {
    return null;
  }
};

const parseSearchImageUrls = (content: string): string[] => {
  try {
    const value = JSON.parse(content) as { images_url?: unknown };
    return Array.isArray(value.images_url)
      ? value.images_url.filter(
          (imageUrl): imageUrl is string =>
            typeof imageUrl === "string" && imageUrl.length > 0
        )
      : [];
  } catch {
    return [];
  }
};

type HistoryMessage = Parameters<
  typeof ExportedMessageRepository.fromArray
>[0][number];

type BranchableHistoryMessage = Parameters<
  typeof ExportedMessageRepository.fromBranchableArray
>[0][number];

const buildBranchableHistory = (
  messages: HistoryMessage[]
): BranchableHistoryMessage[] => {
  const branchableMessages: BranchableHistoryMessage[] = [];
  let visibleHeadId: string | null = null;

  for (let groupStart = 0; groupStart < messages.length; ) {
    const role = messages[groupStart].role;
    let groupEnd = groupStart + 1;
    while (groupEnd < messages.length && messages[groupEnd].role === role) {
      groupEnd++;
    }

    const group = messages.slice(groupStart, groupEnd);
    const parentId = visibleHeadId;

    for (const message of group) {
      branchableMessages.push({ message, parentId });
    }

    visibleHeadId = group.at(-1)?.id ?? visibleHeadId;
    groupStart = groupEnd;
  }

  return branchableMessages;
};

const areSameUserMessages = (left: ApiMessage, right: ApiMessage): boolean =>
  left.role === "user" &&
  right.role === "user" &&
  JSON.stringify(left.message) === JSON.stringify(right.message) &&
  JSON.stringify(left.minio_files ?? []) ===
    JSON.stringify(right.minio_files ?? []) &&
  JSON.stringify(left.a2ui_submission ?? null) ===
    JSON.stringify(right.a2ui_submission ?? null);

/**
 * Collapse refresh-generated duplicate user messages while preserving every
 * assistant response as a branch under the first user message.
 *
 * Assistant messages do not reset the comparison. A different user message
 * does reset it, so identical questions from separate turns remain distinct.
 */
const collapseRefreshUserMessages = (messages: ApiMessage[]): ApiMessage[] => {
  const collapsed: ApiMessage[] = [];
  let activeUserMessage: ApiMessage | undefined;

  for (const message of messages) {
    if (message.role !== "user") {
      collapsed.push(message);
      continue;
    }

    if (activeUserMessage && areSameUserMessages(activeUserMessage, message)) {
      continue;
    }

    collapsed.push(message);
    activeUserMessage = message;
  }

  return collapsed;
};

const restoreAttachments = (
  message: ApiMessage,
  messageId: string
): CompleteAttachment[] => {
  if (!message.minio_files) return [];

  return message.minio_files.map((file, index) => {
    const item = typeof file === "string" ? { object_name: file } : file;
    const objectName = item.object_name;
    const name =
      "name" in item && item.name
        ? item.name
        : objectName.split("/").pop() || "Attachment";
    const rawType = "type" in item && item.type ? item.type : "file";
    const attachmentType = toAttachmentType(rawType);
    const url =
      "url" in item && typeof item.url === "string" ? item.url : undefined;
    const previewUrl = objectName
      ? storageService.getPreviewUrl(objectName, name)
      : undefined;
    const content = previewUrl
      ? attachmentType === "image"
        ? [{ type: "image" as const, image: previewUrl }]
        : [
            {
              type: "file" as const,
              filename: name,
              data: previewUrl,
              mimeType: rawType,
            },
          ]
      : [];

    return {
      id: `${messageId}-attachment-${index}`,
      status: { type: "complete" as const },
      type: attachmentType,
      name,
      contentType: rawType,
      content,
      object_name: objectName,
      url,
      presigned_url:
        "presigned_url" in item && typeof item.presigned_url === "string"
          ? item.presigned_url
          : undefined,
      preview_url: previewUrl,
      size: "size" in item ? item.size : undefined,
    } as unknown as CompleteAttachment;
  });
};

class RemoteConversationHistoryAdapter implements ThreadHistoryAdapter {
  private loadGeneration = 0;

  constructor(
    private readonly getRemoteId: () => string | undefined,
    private readonly initializeThread: () => Promise<RemoteThreadInitializeResponse>
  ) {}

  async load(): Promise<
    ExportedMessageRepository & { unstable_resume?: boolean }
  > {
    const loadGeneration = ++this.loadGeneration;
    // Historical threads may be cached by assistant-ui, so plan state is
    // cached independently by backend conversation ID. Parsing below updates
    // only this load's local snapshot; the active conversation applies it.
    const remoteId = this.getRemoteId();
    let restoredPlan: PlanData | null = null;
    log.log(
      `[history-adapter] load() invoked, remoteId="${remoteId}", prior plan=${
        planRegistry.data ? "set" : "null"
      }`
    );
    if (!remoteId) {
      if (loadGeneration === this.loadGeneration) {
        historicalPlanCache.delete("");
      }
      log.log(`[history-adapter] no remoteId, returning empty`);
      return { messages: [] };
    }

    // Translate backend `ApiMessage` items into assistant-ui content parts.
    // Historical thinking output is restored as completed reasoning content,
    // while the final answer remains a separate text part.
    const response = await conversationService.getDetail(Number(remoteId));
    const detail = response.data?.[0];
    if (!detail) {
      return { messages: [] };
    }
    cacheHistoricalChatMode(remoteId, detail.chat_mode);
    if (!detail.message) {
      return { messages: [] };
    }

    const messages: HistoryMessage[] = [];
    const historyMessages = collapseRefreshUserMessages(detail.message);

    for (const [messageIndex, msg] of historyMessages.entries()) {
      // Resolve a stable messageId first — every per-message side store
      // (sources registry, metadata bucket) is keyed off this value so it
      // matches the id that assistant-ui later sets on the rendered message.
      const messageId = String(msg.message_id ?? `${remoteId}-${messageIndex}`);

      // Backend returns message as a string for user messages, but as an array of
      // ApiMessageItem for assistant messages. Normalize to array for consistent handling.
      const messageParts = Array.isArray(msg.message)
        ? msg.message
        : typeof msg.message === "string"
          ? [{ type: "text", content: msg.message }]
          : [];

      // Collect token_count units so the per-message `SingleTurnTokenUsage`
      // can render the historical step breakdown. The streaming adapter writes
      // the same data into the global registry, but historical restores have
      // no streaming run to read from.
      const stepTokenCounts: StepTokenCount[] = [];

      // Populate conversationSourcesRegistry for historical assistant messages
      // and build the matching `source` parts that drive the
      // `SourceGroupButton`/`SourcesPanel` UI. Keying the registry by the
      // messageId (rather than `${remoteId}_${assistantIdx}`) keeps the lookup
      // aligned with what `markdown-text.tsx` queries via `s.message.id`.
      if (msg.role === "assistant" && Array.isArray(msg.search)) {
        const sources: SearchSource[] = [];
        for (const searchItem of msg.search) {
          if (typeof searchItem === "object" && searchItem !== null) {
            const item = searchItem as Record<string, unknown>;
            const url = (item.url as string | undefined) ?? "";
            const filename = (item.filename as string | undefined) ?? "";
            const title = (item.title as string | undefined) || filename || url;
            if (url || filename || title) {
              sources.push({
                citeIndex: (item.cite_index as number | undefined) ?? 0,
                url,
                title,
                text: item.text as string | undefined,
                sourceType: item.source_type as string | undefined,
                searchType: item.search_type as string | undefined,
                toolSign: item.tool_sign as string | undefined,
                filename,
                downloadUrl: item.download_url as string | undefined,
                objectName: item.object_name as string | undefined,
              });
            }
          }
        }
        if (sources.length > 0) {
          conversationSourcesRegistry.set(messageId, sources);
        }
      }

      const content: Array<Record<string, unknown>> = [];

      if (msg.role === "user") {
        const submissionState = parseA2UIFormSubmissionState(
          msg.a2ui_submission
        );
        if (submissionState) {
          markA2UIFormSubmitted(remoteId, submissionState);
        }
        const text = messageParts
          .filter((part) => part.type === "text")
          .map((part) => part.content)
          .join("\n");
        if (text) {
          content.push({
            type: "text",
            text: normalizeLegacyA2UIActionText(text),
          });
        }
      } else {
        let reasoningText = "";
        // Stack of currently-open sub-agent invocations reconstructed from
        // persisted ``subagent_start`` / ``subagent_end`` units. We do not
        // route inner parts into a separate ``subagent-group`` array;
        // instead we stamp a ``metadata`` block on every reasoning / tool /
        // source part so ``MessagePrimitive.GroupedParts`` in ``thread.tsx``
        // can cluster them under the matching ``group-subagent-<id>-<runId>``
        // header.
        type ActiveSubAgent = {
          runId: string;
          agentId: number | string;
          agentName: string;
          task?: string;
          depth: number;
        };
        const subAgentStack: ActiveSubAgent[] = [];
        const renderedA2UISurfaces = new Set<string>();
        let historicalRunCounter = 0;
        const currentSubAgent = (): ActiveSubAgent | null =>
          subAgentStack.length > 0
            ? subAgentStack[subAgentStack.length - 1]
            : null;
        const buildMetadata = ():
          | {
              subagentId: number | string;
              runId: string;
              agentName: string;
              depth: number;
              task?: string;
              isRunning: boolean;
            }
          | undefined => {
          const top = currentSubAgent();
          if (!top) return undefined;
          return {
            subagentId: top.agentId,
            runId: top.runId,
            agentName: top.agentName,
            depth: top.depth,
            task: top.task,
            isRunning: false,
          };
        };

        const flushReasoning = () => {
          if (!reasoningText) return;
          const reasoningPart: Record<string, unknown> = {
            type: "reasoning",
            text: reasoningText,
            status: { type: "done" },
          };
          const meta = buildMetadata();
          if (meta) reasoningPart.metadata = meta;
          content.push(reasoningPart);
          reasoningText = "";
        };

        for (const [partIndex, part] of messageParts.entries()) {
          // Note: do NOT early-return on `!part.content` at the top level —
          // `tool` items stored in the database have an empty `content` field
          // and only carry `tool_name` + `tool_arguments` (see the
          // `get_station_code_of_citys` example in the history payload). An
          // early return here would drop those tool calls and leave the
          // matching `execution_logs` chunk unattached, so it would be
          // surfaced as plain text instead of a tool result. Each branch
          // below handles its own empty-content case (e.g. `parse` is now
          // intentionally skipped, mirroring the streaming adapter).

          // Token count units are not part of the rendered content — they are
          // parsed into the per-message step bucket below and consumed by
          // `SingleTurnTokenUsage` via message metadata.
          if (part.type === "token_count") {
            const parsed = parseStepTokenCount(part.content);
            if (parsed) stepTokenCounts.push(parsed);
            continue;
          }

          // Restore per-tool search sources from the persisted placeholder.
          // The backend keeps the full results in `searchByUnitId`, keyed by
          // the placeholder's database unit ID.
          if (part.type === "search_content_placeholder") {
            const unitId = parseSearchPlaceholderUnitId(part.content);
            const searchResults = unitId
              ? msg.searchByUnitId?.[unitId]
              : undefined;
            if (Array.isArray(searchResults)) {
              for (const searchResult of searchResults) {
                const item = toToolSearchItem(searchResult);
                if (item) {
                  attachSearchContentToTool(content, item, part.tool_call_id);
                }
              }
            }
            continue;
          }

          // Older history payloads may retain the original search_content
          // unit instead of a placeholder. Support that shape as well.
          if (part.type === "search_content") {
            try {
              const parsed = JSON.parse(part.content) as unknown;
              const searchResults = Array.isArray(parsed) ? parsed : [parsed];
              for (const searchResult of searchResults) {
                const item = toToolSearchItem(searchResult);
                if (item) {
                  attachSearchContentToTool(content, item, part.tool_call_id);
                }
              }
            } catch (error) {
              log.warn(
                "[history-adapter] Failed to parse search_content:",
                error
              );
            }
            continue;
          }

          if (part.type === "picture_web") {
            for (const imageUrl of parseSearchImageUrls(part.content)) {
              attachSearchImageToTool(content, imageUrl, part.tool_call_id);
            }
            continue;
          }

          if (part.type === "skill_file_uploads") {
            continue;
          }

          if (part.type === "a2ui") {
            flushReasoning();
            let envelope: unknown = part.content;
            try {
              envelope = JSON.parse(part.content);
            } catch {
              // The runtime emits a safe fallback for malformed history.
            }
            const result = processA2UIEnvelope(remoteId, envelope);
            const createsSurface = Boolean(
              envelope &&
              typeof envelope === "object" &&
              "message" in envelope &&
              (envelope as { message?: unknown }).message &&
              typeof (envelope as { message: unknown }).message === "object" &&
              "createSurface" in (envelope as { message: object }).message
            );
            const surfaceId =
              result.surfaceId ??
              (envelope &&
              typeof envelope === "object" &&
              "surfaceId" in envelope
                ? String((envelope as { surfaceId: unknown }).surfaceId)
                : `invalid-${messageId}-${partIndex}`);
            if (
              (createsSurface || result.error) &&
              !renderedA2UISurfaces.has(surfaceId)
            ) {
              content.push(
                createA2UIDataPart(remoteId, surfaceId, result.error)
              );
              renderedA2UISurfaces.add(surfaceId);
            }
            continue;
          }

          if (part.type === "plan") {
            const plan = parsePlan(part.content);
            log.log(
              `[history-adapter] plan unit: parsed=${
                plan ? "ok" : "null"
              }, steps=${plan?.steps.length ?? 0}`
            );
            if (plan) restoredPlan = plan;
            const previous = content.at(-1);
            if (
              previous?.type === "tool-call" &&
              previous.toolName === "tool"
            ) {
              previous.toolName = "create_plan";
              previous.argsText = part.content;
            }
            continue;
          }

          if (part.type === "plan_step_update") {
            const update = parsePlanStepUpdate(part.content);
            log.log(
              `[history-adapter] plan_step_update unit: parsed=${
                update ? "ok" : "null"
              }`
            );
            if (update && restoredPlan) {
              restoredPlan = {
                ...restoredPlan,
                steps: restoredPlan.steps.map((step) =>
                  step.id === update.stepId
                    ? { ...step, status: update.status }
                    : step
                ),
              };
            }
            const previous = content.at(-1);
            if (
              previous?.type === "tool-call" &&
              previous.toolName === "tool"
            ) {
              previous.toolName = "update_plan_step";
              previous.argsText = part.content;
            }
            continue;
          }

          // ``subagent_start`` allocates a fresh ``runId`` and pushes the
          // descriptor so subsequent reasoning / tool / source parts inherit
          // its ``metadata``. We also push a ``data`` boundary stamp (same
          // shape as the streaming adapter emits) so the
          // ``group-subagent-*`` cluster appears immediately when the
          // conversation is reloaded.
          if (part.type === "subagent_start") {
            flushReasoning();
            let payload: {
              agent_id?: number | string;
              agent_name?: string;
              task?: string;
            } = {};
            try {
              const parsed = JSON.parse(part.content || "{}");
              if (parsed && typeof parsed === "object") {
                payload = parsed as typeof payload;
              }
            } catch {
              payload = { task: part.content };
            }
            historicalRunCounter += 1;
            const runId = `run-${historicalRunCounter}`;
            const descriptor: ActiveSubAgent = {
              runId,
              agentId: payload.agent_id ?? "unknown",
              agentName: payload.agent_name || "subagent",
              task: payload.task,
              depth: subAgentStack.length + 1,
            };
            subAgentStack.push(descriptor);
            const stampMeta = buildMetadata();
            content.push({
              type: "data",
              name: "subagent-boundary",
              data: {
                kind: "start",
                runId,
                agentId: descriptor.agentId,
                agentName: descriptor.agentName,
                task: descriptor.task,
                depth: descriptor.depth,
                isRunning: false,
              },
              metadata: stampMeta,
            });
            continue;
          }

          if (part.type === "subagent_end") {
            flushReasoning();
            subAgentStack.pop();
            continue;
          }

          if (part.type === "step_count") {
            if (part.content) reasoningText += part.content;
            continue;
          }

          if (isReasoningChunkType(part.type)) {
            if (part.content) reasoningText += part.content;
            continue;
          }

          if (part.type === "tool" || part.type === "tool-call") {
            flushReasoning();
            const toolCallPart = buildToolCallPart({
              type: part.type,
              content: part.content,
              unit_index: part.unit_index ?? partIndex,
              tool_call_id: part.tool_call_id,
              role: part.role,
              tool_name: part.tool_name,
              tool_arguments: part.tool_arguments,
            });
            toolCallPart.status = { type: "complete" };
            const meta = buildMetadata();
            if (meta) toolCallPart.metadata = meta;
            content.push(toolCallPart);
            continue;
          }

          if (part.type === "execution_logs") {
            flushReasoning();
            attachExecutionLogsToTool(content, part);
            continue;
          }

          if (part.type === "error") {
            flushReasoning();
            if (part.content) {
              const errorPart: Record<string, unknown> = {
                type: "text",
                text: part.content,
                isError: true,
              };
              const meta = buildMetadata();
              if (meta) errorPart.metadata = meta;
              content.push(errorPart);
            }
            continue;
          }

          if (part.type === "final_answer") {
            flushReasoning();
            if (part.content) {
              const textPart: Record<string, unknown> = {
                type: "text",
                text: part.content,
              };
              const meta = buildMetadata();
              if (meta) textPart.metadata = meta;
              content.push(textPart);
            }
          }
        }

        flushReasoning();

        // Defensive: pop any unclosed sub-agent stack entries so the
        // reconstruction state stays balanced even when the historical
        // stream was truncated (e.g. resumed mid-run, agent run stopped
        // early, etc.).
        subAgentStack.length = 0;

        // Some older records only persist the message-level image list. When
        // no picture_web unit restored images inline, associate that list with
        // the most recent tool call so ToolFallback still shows its Sources.
        if (Array.isArray(msg.picture) && msg.picture.length > 0) {
          const toolHasImages = content.some(
            (item) =>
              item?.type === "tool-call" &&
              Array.isArray(item.searchImages) &&
              item.searchImages.length > 0
          );
          if (!toolHasImages) {
            for (const imageUrl of msg.picture) {
              if (typeof imageUrl === "string" && imageUrl) {
                attachSearchImageToTool(content, imageUrl);
              }
            }
          }
        }

        if (content.length === 0) {
          const fallbackText = messageParts
            .filter((part) => part.type !== "skill_file_uploads")
            .map((part) => part.content)
            .join("\n");
          if (fallbackText) content.push({ type: "text", text: fallbackText });
        }

        // Emit a `source` part for each persisted search result so the
        // `group-source` block renders the inline "检索结果" trigger button.
        // Mirrors the streaming adapter's end-of-stream emission, but uses the
        // already-aggregated `msg.search` data instead of rebuilding it from
        // the raw SSE chunks.
        if (Array.isArray(msg.search) && msg.search.length > 0) {
          for (const searchItem of msg.search) {
            if (typeof searchItem === "object" && searchItem !== null) {
              const item = searchItem as Record<string, unknown>;
              const url = (item.url as string | undefined) ?? "";
              const filename = (item.filename as string | undefined) ?? "";
              const title =
                (item.title as string | undefined) || filename || url;
              if (!url && !filename && !title) continue;
              const citeIndex = (item.cite_index as number | undefined) ?? 0;
              content.push({
                type: "source",
                sourceType: item.source_type === "file" ? "document" : "url",
                url,
                title,
                text: item.text as string | undefined,
                filename,
                downloadUrl: item.download_url as string | undefined,
                objectName: item.object_name as string | undefined,
                citeIndex,
                messageId,
              });
            }
          }
        }

        // Emit one `source` part per persisted image so the side panel's
        // image tab has data to render. The streaming adapter emits these
        // from `picture_web` chunks; historical loads read them from
        // `msg.picture` which already de-duplicates by URL.
        if (Array.isArray(msg.picture) && msg.picture.length > 0) {
          for (const imageUrl of msg.picture) {
            if (typeof imageUrl !== "string" || !imageUrl) continue;
            content.push({
              type: "source",
              sourceType: "url",
              url: imageUrl,
              title: imageUrl,
              isImage: true,
            });
          }
        }
      }

      const attachments = restoreAttachments(msg, messageId);
      if (msg.role === "assistant" && attachments.length > 0) {
        skillFileUploadsRegistry.set(messageId, attachments);
        content.push({
          type: "text",
          text: "",
          isSkillFiles: true,
        });
      }

      if (content.length === 0 && attachments.length === 0) {
        // Still track assistant index even if no content (for registry alignment)
        continue;
      }

      // Persist the historical step breakdown on message metadata so
      // `SingleTurnTokenUsage` can find it via the same selector it uses for
      // the streaming flow (which writes to a global registry). assistant-ui
      // requires `metadata.custom` to be present on every message, so we
      // always include the field and only set the token bucket when we have
      // historical step data.
      const metadata = {
        custom: stepTokenCounts.length > 0 ? { stepTokenCounts } : {},
      };

      messages.push({
        id: messageId,
        role: msg.role,
        content: content as unknown as HistoryMessage["content"],
        ...(msg.role === "user" && attachments.length > 0
          ? { attachments }
          : {}),
        metadata,
      });
    }

    const branchableMessages = buildBranchableHistory(messages);
    const repository = ExportedMessageRepository.fromBranchableArray(
      branchableMessages,
      { headId: messages.at(-1)?.id ?? null }
    );
    if (loadGeneration === this.loadGeneration) {
      historicalPlanCache.set(remoteId, restoredPlan);
      if (activeHistoricalConversationId === remoteId) {
        planRegistry.set(restoredPlan);
      }
    }
    return {
      ...repository,
      unstable_resume: detail.streaming_message?.status === "streaming",
    };
  }

  async *resume(
    options: ChatModelRunOptions
  ): AsyncGenerator<ChatModelRunResult, void> {
    const remoteId = this.getRemoteId();
    if (!remoteId) {
      log.warn(
        "[history-adapter] Cannot resume without a remote conversation ID"
      );
      return;
    }

    const custom = (options.runConfig?.custom ?? {}) as Record<string, unknown>;
    const resumedRun = agUIChatModelAdapter.run({
      ...options,
      runConfig: {
        ...options.runConfig,
        custom: {
          ...custom,
          threadId: remoteId,
          resume: true,
        },
      },
    });

    if (Symbol.asyncIterator in resumedRun) {
      yield* resumedRun;
      return;
    }
    yield await resumedRun;
  }

  // `append` is intentionally a no-op: in the remote-thread-list flow, message
  // persistence is owned by the `runAgent` stream endpoint and message history
  // is reloaded via `load()`. Hooking `append` here would prematurely persist
  // draft attachments before the user actually submits the message, which
  // conflicts with the "upload-on-send" semantics. The runtime only requires
  // the method to exist so that composer actions (e.g. add attachment) do not
  // throw "appendMessage is not a function".
  async append(_item: ExportedMessageRepositoryItem): Promise<void> {
    return;
  }

  withFormat<TMessage, TStorageFormat extends Record<string, unknown>>(
    _formatAdapter: MessageFormatAdapter<TMessage, TStorageFormat>
  ): GenericThreadHistoryAdapter<TMessage> {
    return this as unknown as GenericThreadHistoryAdapter<TMessage>;
  }
}

const toRemoteThreadMetadata = (
  item: ConversationListItem
): RemoteThreadMetadata => {
  // Prefer the most recent activity timestamp; fall back to the creation time
  // so the thread list can always group by recency. The timestamp is passed
  // through the `custom` slot because the installed @assistant-ui/react
  // (0.14.15) does not yet thread `lastMessageAt` through the runtime state.
  const timestamp = item.update_time || item.create_time;
  return {
    remoteId: String(item.conversation_id),
    status: "regular",
    title: item.conversation_title ?? "Untitled conversation",
    ...(timestamp || item.agent_id
      ? {
          custom: {
            ...(timestamp
              ? { lastMessageAt: new Date(timestamp).toISOString() }
              : {}),
            ...(item.agent_id ? { agentId: item.agent_id } : {}),
          },
        }
      : {}),
  };
};

const createHistoryProvider = (): FC<PropsWithChildren> => {
  const Provider: FC<PropsWithChildren> = ({ children }) => {
    const aui = useAui();

    const history = useMemo(
      () =>
        new RemoteConversationHistoryAdapter(
          () => aui.threadListItem().getState().remoteId,
          () => aui.threadListItem().initialize()
        ),
      [aui]
    );

    const adapters = useMemo(() => ({ history }), [history]);

    return (
      <RuntimeAdapterProvider adapters={adapters}>
        {children}
      </RuntimeAdapterProvider>
    );
  };

  return Provider;
};

// ---------------------------------------------------------------------------
// Server conversation id registry
// ---------------------------------------------------------------------------
//
// `generateTitle` is invoked by the assistant-ui runtime concurrently with
// `ChatModelAdapter.run()`. For a brand-new thread the adapter's `remoteId`
// is still the empty-string placeholder returned by `initialize()`, while the
// real backend `conversation_id` only lands in the page state after the
// `agent/run` response header is parsed. To avoid sending `conversation_id: 0`
// (which happens because `Number("") === 0`) we let the page register a
// resolver that points at its `serverConversationIdsRef` plus the active
// assistant-ui thread id. `generateTitle` then polls the ref until the real
// id is available before issuing the title request.
type ServerConversationIdState = {
  idsRef: MutableRefObject<Map<string, string>>;
  getActiveThreadId: () => string | undefined;
};

let serverConversationIdState: ServerConversationIdState | null = null;
const titleRequests = new Map<string, Promise<string>>();

export const generateConversationTitle = (
  conversationId: string,
  question: string
): Promise<string> => {
  const existingRequest = titleRequests.get(conversationId);
  if (existingRequest) return existingRequest;

  const request = conversationService
    .generateTitle({
      conversation_id: Number(conversationId),
      question,
    })
    .then((result) => {
      const title = typeof result === "string" ? result.trim() : "";
      if (!title) {
        throw new Error(
          `Title generation returned an empty title for conversation ${conversationId}.`
        );
      }
      return title;
    })
    .catch((error) => {
      titleRequests.delete(conversationId);
      throw error;
    });

  titleRequests.set(conversationId, request);
  return request;
};

export const setServerConversationIdState = (
  state: ServerConversationIdState | null
) => {
  serverConversationIdState = state;
};

const MAX_TITLE_WAIT_MS = 5_000;
const TITLE_POLL_INTERVAL_MS = 50;

const waitForServerConversationId = async (
  fallbackRemoteId: string
): Promise<string | null> => {
  const state = serverConversationIdState;
  if (!state) return fallbackRemoteId || null;

  const { idsRef, getActiveThreadId } = state;
  const startedAt = Date.now();

  // Fast path: the ref is already populated (subsequent runs in a thread
  // that already has a server-side conversation, or an existing thread
  // opened from the sidebar).
  const readNow = (): string | undefined => {
    const activeThreadId = getActiveThreadId();
    if (!activeThreadId) return undefined;
    const fromRef = idsRef.current.get(activeThreadId);
    if (fromRef && Number.isInteger(Number(fromRef)) && Number(fromRef) > 0) {
      return fromRef;
    }
    return undefined;
  };

  const immediate = readNow();
  if (immediate) return immediate;

  // Slow path: poll until `agent/run`'s response header callback lands the
  // server id in the ref, or we time out.
  // eslint-disable-next-line no-constant-condition
  while (true) {
    await new Promise((resolve) => setTimeout(resolve, TITLE_POLL_INTERVAL_MS));
    const next = readNow();
    if (next) return next;
    if (Date.now() - startedAt > MAX_TITLE_WAIT_MS) return null;
  }
};

export const conversationThreadListAdapter: RemoteThreadListAdapter = {
  unstable_Provider: createHistoryProvider(),

  async list(): Promise<RemoteThreadListResponse> {
    try {
      const data = await conversationService.getList();
      return {
        threads: data.map(toRemoteThreadMetadata),
      };
    } catch (error) {
      return { threads: [] };
    }
  },

  async initialize(_threadId: string): Promise<RemoteThreadInitializeResponse> {
    // Conversation creation is now handled lazily by `POST /api/agent/run`:
    // when the request omits `conversation_id`, the backend auto-creates the
    // conversation and returns the new id via the `conversation_id` response
    // header. The remote-chat-model-adapter forwards that id back to the page
    // state, which then rebinds it as `runConfig.custom.threadId` for later
    // messages in the same thread.
    //
    // We intentionally do NOT call `conversationService.create()` here —
    // doing so would create a second, empty conversation that the agent
    // run never reuses (see commit history for details).
    //
    // We return an empty-string `remoteId` rather than `undefined` because
    // the assistant-ui `RemoteThreadListAdapter["initialize"]` contract
    // requires a string. The empty string is a safe placeholder: the page
    // resolves `activeConversationId` with priority
    // `serverConversationIdsRef → remoteId → activeThreadId`, so as soon as
    // the adapter captures the server id from the response header the page
    // starts using the real id instead of this placeholder.
    //
    // `generateTitle` follows the same priority chain: it consults the page's
    // `serverConversationIdsRef` via `waitForServerConversationId` before
    // falling back to the raw `remoteId`, so a brand-new thread no longer
    // triggers a `conversation_id: 0` request (which would silently fail on
    // the backend's `WHERE conversation_id = 0` filter).
    return {
      remoteId: "",
      externalId: "",
    };
  },

  async rename(remoteId: string, newTitle: string): Promise<void> {
    const candidateId = await waitForServerConversationId(remoteId);
    const conversationId = Number(candidateId);
    if (
      !candidateId ||
      !Number.isInteger(conversationId) ||
      conversationId <= 0
    ) {
      throw new Error(
        "Cannot rename a conversation without a backend conversation ID."
      );
    }
    await conversationService.rename(conversationId, newTitle);
  },

  // The backend currently has no archive/unarchive endpoints, so these are
  // intentionally no-ops. Keeping the implementations lets the runtime call
  // them safely (e.g. from sidebar actions) without crashing the page.
  async archive(_remoteId: string): Promise<void> {
    log.warn(
      "[adapter] archive is not supported by the backend yet; ignoring."
    );
  },

  async unarchive(_remoteId: string): Promise<void> {
    log.warn(
      "[adapter] unarchive is not supported by the backend yet; ignoring."
    );
  },

  async delete(remoteId: string): Promise<void> {
    await conversationService.delete(Number(remoteId));
  },

  async fetch(threadId: string): Promise<RemoteThreadMetadata> {
    const [detail, conversations] = await Promise.all([
      conversationService.getById(threadId),
      conversationService.getList(),
    ]);
    const conversation = conversations.find(
      (item) => item.conversation_id === detail.conversation_id
    );

    return toRemoteThreadMetadata(
      conversation ?? {
        conversation_id: detail.conversation_id,
        conversation_title: "Untitled conversation",
        agent_id: detail.agent_id,
        create_time: detail.create_time,
        update_time: detail.create_time,
      }
    );
  },

  async generateTitle(_remoteId, _messages) {
    // Title generation is initiated by the page after agent/run returns the
    // real backend conversation ID. This avoids racing the first run.
    return createAssistantStream(() => {});
  },
};
