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

import {
  CONVERSATION_PAGE_SIZE,
  conversationService,
} from "@/services/conversationService";
import { getConversationDateBoundaries } from "@/lib/conversationViewport";
import { toMessageCreatedAt } from "@/lib/messageDate";

import { storageService } from "@/services/storageService";
import { parseAutomationProposal } from "@/features/agentAutomation/parseProposal";
import type { ConversationListItem } from "@/types/conversation";
import type { ApiConversationDetail, ApiMessage } from "@/types/conversation";
import { collapseRefreshUserMessages } from "./history-branching";
import log from "@/lib/logger";
import { createAssistantStream } from "assistant-stream";
import type { AttachmentType } from "../utils/attachment-type";
import {
  attachExecutionLogsToTool,
  collapseSubAgentParts,
  attachSearchContentToTool,
  buildToolCallPart,
  conversationSourcesRegistry,
  extractAidpImageKeys,
  searchImagesRegistry,
  isReasoningChunkType,
  skillFileUploadsRegistry,
  remoteChatModelAdapter,
  parseStepTokenCount,
  parseContextBudget,
  parseProviderCallUsage,
  parseTurnUsage,
  parsePlan,
  parsePlanStepUpdate,
  planRegistry,
  type PlanData,
  type SearchSource,
  type ContextBudgetEvent,
  type ProviderCallUsageV2,
  type TurnUsageV2,
  type StepTokenCount,
} from "./remote-chat-model-adapter";

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
  ((mode: HistoricalChatMode) => void) | undefined;
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

export const cacheHistoricalChatMode = (
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

const parseImageMetadata = (value: unknown) => {
  if (typeof value !== "string") return null;

  try {
    const metadata = JSON.parse(value) as {
      source_file?: string;
      image_url?: string;
    };
    return typeof metadata.image_url === "string" ? metadata : null;
  } catch {
    return null;
  }
};

const toToolSearchItem = (value: unknown) => {
  if (typeof value !== "object" || value === null) return null;

  const item = value as Record<string, unknown>;
  const url = typeof item.url === "string" ? item.url : "";
  const filename = typeof item.filename === "string" ? item.filename : "";
  const sourceFile = typeof item.source_file === "string" ? item.source_file : "";
  const imageMetadata = parseImageMetadata(item.text);
  const resolvedUrl = imageMetadata?.image_url || url;
  const title =
    (typeof item.title === "string" && item.title) ||
    filename ||
    sourceFile ||
    imageMetadata?.source_file ||
    resolvedUrl;
  const citeIndex =
    typeof item.cite_index === "number"
      ? item.cite_index
      : typeof item.citeIndex === "number"
        ? item.citeIndex
        : undefined;
  const toolSign = typeof item.tool_sign === "string" ? item.tool_sign : undefined;

  return resolvedUrl || sourceFile
    ? {
        url: resolvedUrl,
        title,
        text: imageMetadata ? undefined : typeof item.text === "string" ? item.text : undefined,
        sourceType: typeof item.source_type === "string" ? item.source_type : undefined,
        filename: filename || undefined,
        sourceFile: sourceFile || imageMetadata?.source_file || undefined,
        objectName: typeof item.object_name === "string" ? item.object_name : undefined,
        citeIndex,
        toolSign,
        isImage: Boolean(imageMetadata),
      }
    : null;
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

  for (let groupStart = 0; groupStart < messages.length;) {
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

export class RemoteConversationHistoryAdapter implements ThreadHistoryAdapter {
  private loadGeneration = 0;

  constructor(
    private readonly getRemoteId: () => string | undefined,
    private readonly initializeThread: () => Promise<RemoteThreadInitializeResponse>,
    private readonly loadDetail?: () => Promise<
      ApiConversationDetail | undefined
    >
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
    const detail = this.loadDetail
      ? await this.loadDetail()
      : (await conversationService.getDetail(Number(remoteId))).data?.[0];
    if (!detail) {
      return { messages: [] };
    }
    cacheHistoricalChatMode(remoteId, detail.chat_mode);
    if (!detail.message) {
      return { messages: [] };
    }

    const messages: HistoryMessage[] = [];
    let assistantIdx = 0;

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
      const persistedAnswerImageKeys = extractAidpImageKeys(
        messageParts.flatMap((part) =>
          (part.type === "final_answer" || part.type === "text") &&
          typeof part.content === "string"
            ? [part.content]
            : []
        )
      );

      // Collect token_count units so the per-message `SingleTurnTokenUsage`
      // can render the historical step breakdown. The streaming adapter writes
      // the same data into the global registry, but historical restores have
      // no streaming run to read from.
      const stepTokenCounts: StepTokenCount[] = [];
      const pendingContextBudgets = new Map<number, ContextBudgetEvent>();
      const providerCallUsages: ProviderCallUsageV2[] = [];
      let turnUsage: TurnUsageV2 | null = null;

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
              const derivedImageKey = `${item.tool_sign ?? ""}${item.cite_index ?? ""}`;
              const isImage =
                (item.score_details as Record<string, unknown> | undefined)
                  ?.chunk_type === "image" ||
                persistedAnswerImageKeys.includes(derivedImageKey);
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
                isImage,
                imageKey:
                  (item.image_key as string | undefined) ||
                  (isImage ? derivedImageKey : undefined),
              });
            }
          }
        }
        if (sources.length > 0) {
          conversationSourcesRegistry.set(messageId, sources);
        }
      }

      const content: any[] = [];

      if (msg.role === "user") {
        const text = messageParts
          .filter((part) => part.type === "text")
          .map((part) => part.content)
          .join("\n");
        if (text) content.push({ type: "text", text });
      } else {
        let reasoningText = "";
        // Per-invocation map of currently-open sub-agent runs reconstructed
        // from persisted ``subagent_start`` / ``subagent_end`` units. We do
        // not route inner parts into a separate ``subagent-group`` array;
        // instead we stamp a ``metadata`` block on every reasoning / tool /
        // source part so ``MessagePrimitive.GroupedParts`` in ``thread.tsx``
        // can cluster them under the matching ``group-subagent-<id>-<runId>``
        // header.
        //
        // Parallel siblings must not collapse onto one LIFO stack: two
        // siblings persisted with overlapping units would otherwise swap
        // ``runId`` for any interleaved chunk. Each ``subagent_start``
        // carries a stable ``invocation_id`` so we open a fresh slot per
        // id, and the matching ``subagent_end`` closes exactly that slot
        // (instead of popping the most-recently-opened entry).
        type ActiveSubAgent = {
          runId: string;
          agentId: number | string;
          agentName: string;
          task?: string;
          depth: number;
          invocationId: string;
          reasoningText: string;
        };
        const activeSubAgents = new Map<string, ActiveSubAgent>();
        let historicalRunCounter = 0;
        // For history replay we keep a deterministic ordering of "active"
        // scopes by tracking insertion order explicitly. Map iteration is
        // already insertion-ordered, so the first remaining entry is the
        // best "default" attribution when a chunk lacks its own id.
        const currentSubAgent = (
          invocationId?: string
        ): ActiveSubAgent | null => {
          if (invocationId) return activeSubAgents.get(invocationId) ?? null;
          return null;
        };
        const buildMetadata = (
          invocationId?: string
        ):
          | {
              subagentId: number | string;
              runId: string;
              agentName: string;
              depth: number;
              task?: string;
              isRunning: boolean;
            }
          | undefined => {
          const top = currentSubAgent(invocationId);
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

        const flushReasoning = (invocationId?: string) => {
          const entry = invocationId ? activeSubAgents.get(invocationId) : null;
          if (entry?.reasoningText) {
            content.push({
              type: "reasoning",
              text: entry.reasoningText,
              status: { type: "done" },
              metadata: {
                subagentId: entry.agentId,
                runId: entry.runId,
                agentName: entry.agentName,
                depth: entry.depth,
                task: entry.task,
                isRunning: false,
              },
            });
            entry.reasoningText = "";
          }
          if (!invocationId && reasoningText) {
            content.push({
              type: "reasoning",
              text: reasoningText,
              status: { type: "done" },
            });
            reasoningText = "";
          }
        };

        const answerImageKeys = persistedAnswerImageKeys;
        const persistedImageSources = Array.isArray(msg.search)
          ? msg.search.filter(
              (searchItem) =>
                typeof searchItem === "object" && searchItem !== null
            )
          : [];
        const restoredImageUrls = new Set<string>();
        const restoredImages: any[] = [];
        const appendHistoricalImage = (imageUrl: string) => {
          if (!imageUrl || restoredImageUrls.has(imageUrl)) return;
          const imageIndex = restoredImageUrls.size;
          const imageKey = answerImageKeys[imageIndex];
          const metadata = persistedImageSources.find((searchItem) => {
            const item = searchItem as Record<string, unknown>;
            return (
              imageKey === `${item.tool_sign ?? ""}${item.cite_index ?? ""}`
            );
          }) as Record<string, unknown> | undefined;
          const title = (metadata?.title as string | undefined) || imageUrl;
          const imagePart: any = {
            type: "source",
            sourceType: "url",
            url: imageUrl,
            title,
            text: metadata?.text as string | undefined,
            citeIndex:
              (metadata?.cite_index as number | undefined) ?? undefined,
            isImage: true,
            imageKey:
              (metadata?.image_key as string | undefined) ||
              (metadata?.tool_sign && metadata?.cite_index !== undefined
                ? `${metadata.tool_sign}${metadata.cite_index}`
                : undefined) ||
              imageKey,
          };
          const meta = buildMetadata();
          if (meta) imagePart.metadata = meta;
          restoredImageUrls.add(imageUrl);
          restoredImages.push(imagePart);
          return imagePart;
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
            if (parsed) {
              const pendingBudget = pendingContextBudgets.get(
                parsed.stepNumber
              );
              if (pendingBudget) {
                parsed.contextBudget = pendingBudget;
                pendingContextBudgets.delete(parsed.stepNumber);
              }
              stepTokenCounts.push(parsed);
            }
            continue;
          }
          if (part.type === "context_budget") {
            const budget = parseContextBudget(part.content);
            if (budget) {
              const step = [...stepTokenCounts]
                .reverse()
                .find((item) => item.stepNumber === budget.step_number);
              if (step) step.contextBudget = budget;
              else pendingContextBudgets.set(budget.step_number, budget);
            }
            continue;
          }
          if (part.type === "llm_usage") {
            const usage = parseProviderCallUsage(part.content);
            if (usage) providerCallUsages.push(usage);
            continue;
          }
          if (part.type === "turn_usage") {
            turnUsage = parseTurnUsage(part.content);
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
              const imagePart = appendHistoricalImage(imageUrl);
              if (imagePart) {
                attachSearchContentToTool(
                  content,
                  {
                    url: imagePart.url,
                    title: imagePart.title,
                    text: imagePart.text,
                    isImage: true,
                    imageKey: imagePart.imageKey,
                  },
                  part.tool_call_id,
                );
              }
            }
            continue;
          }

          if (part.type === "skill_file_uploads") {
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

          // ``subagent_start`` allocates a fresh ``runId`` and opens a new
          // per-invocation slot so subsequent reasoning / tool / source parts
          // inherit its ``metadata``. We also push a ``data`` boundary stamp
          // (same shape as the streaming adapter emits) so the
          // ``group-subagent-*`` cluster appears immediately when the
          // conversation is reloaded. Parallel siblings are stored in a map
          // keyed by the stable ``invocation_id`` so they never collide on
          // the same ``runId`` or share reasoning text.
          if (part.type === "subagent_start") {
            flushReasoning();
            let payload: {
              agent_id?: number | string;
              agent_name?: string;
              task?: string;
              invocation_id?: string;
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
            const invocationId =
              payload.invocation_id ?? part.invocation_id ?? runId;
            const descriptor: ActiveSubAgent = {
              runId,
              agentId: payload.agent_id ?? "unknown",
              agentName: payload.agent_name || "subagent",
              task: payload.task,
              depth: activeSubAgents.size + 1,
              invocationId,
              reasoningText: "",
            };
            activeSubAgents.set(invocationId, descriptor);
            const stampMeta = buildMetadata(invocationId);
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
                invocationId,
              },
              metadata: stampMeta,
            });
            continue;
          }

          if (part.type === "subagent_end") {
            const endInvocationId = (() => {
              try {
                const parsed = JSON.parse(part.content || "{}");
                return parsed && typeof parsed === "object"
                  ? (parsed as { invocation_id?: string }).invocation_id
                  : undefined;
              } catch {
                return part.invocation_id;
              }
            })();
            flushReasoning(endInvocationId ?? part.invocation_id);
            let payload: {
              invocation_id?: string;
            } = {};
            try {
              const parsed = JSON.parse(part.content || "{}");
              if (parsed && typeof parsed === "object") {
                payload = parsed as typeof payload;
              }
            } catch {
              // Legacy subagent_end payloads may not be JSON; fall through.
            }
            const invocationId = payload.invocation_id ?? part.invocation_id;
            if (invocationId && activeSubAgents.has(invocationId)) {
              const closing = activeSubAgents.get(invocationId)!;
              if (closing.reasoningText) {
                content.push({
                  type: "reasoning",
                  text: closing.reasoningText,
                  status: { type: "done" },
                  metadata: {
                    subagentId: closing.agentId,
                    runId: closing.runId,
                    agentName: closing.agentName,
                    depth: closing.depth,
                    task: closing.task,
                    isRunning: false,
                  },
                });
                closing.reasoningText = "";
              }
              activeSubAgents.delete(invocationId);
            } else if (activeSubAgents.size > 0) {
              // No id supplied (very old payload): fall back to closing the
              // first active invocation so we stay balanced.
              const firstKey = activeSubAgents.keys().next().value;
              if (firstKey) {
                activeSubAgents.delete(firstKey);
              }
            }
            continue;
          }

          if (part.type === "step_count") {
            if (part.content) {
              const top = currentSubAgent(part.invocation_id);
              if (top) top.reasoningText += part.content;
              else reasoningText += part.content;
            }
            continue;
          }

          if (isReasoningChunkType(part.type)) {
            if (part.content) {
              const top = currentSubAgent(part.invocation_id);
              if (top) top.reasoningText += part.content;
              else reasoningText += part.content;
            }
            continue;
          }

          if (part.type === "tool" || part.type === "tool-call") {
            flushReasoning(part.invocation_id);
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
            const meta = buildMetadata(part.invocation_id);
            if (meta) toolCallPart.metadata = meta;
            content.push(toolCallPart);
            continue;
          }

          if (part.type === "execution_logs") {
            flushReasoning(part.invocation_id);
            attachExecutionLogsToTool(content, part);
            continue;
          }

          if (part.type === "error") {
            flushReasoning(part.invocation_id);
            if (part.content) {
              const errorPart: any = {
                type: "text",
                text: part.content,
                isError: true,
              };
              const meta = buildMetadata(part.invocation_id);
              if (meta) errorPart.metadata = meta;
              content.push(errorPart);
            }
            continue;
          }

          if (part.type === "automation_proposal") {
            flushReasoning();
            const proposal = parseAutomationProposal(part.content);
            if (proposal) {
              content.push({
                type: "data",
                name: "automation-proposal",
                data: proposal,
              });
            } else {
              log.warn("[history-adapter] Failed to parse automation proposal");
            }
            continue;
          }

          if (part.type === "final_answer") {
            flushReasoning(part.invocation_id);
            if (part.content) {
              const textPart: any = { type: "text", text: part.content };
              const meta = buildMetadata(part.invocation_id);
              if (meta) textPart.metadata = meta;
              content.push(textPart);
            }
          }
        }

        flushReasoning();

        // Flush any incomplete sub-agent reasoning without changing the
        // order in which persisted units were reconstructed.
        for (const entry of activeSubAgents.values()) {
          flushReasoning(entry.invocationId);
        }
        activeSubAgents.clear();

        // Some older records only persist the message-level image list.
        if (Array.isArray(msg.picture) && msg.picture.length > 0) {
          for (const imageUrl of msg.picture) {
            if (typeof imageUrl === "string" && imageUrl) {
              appendHistoricalImage(imageUrl);
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

        const restoredImageMap = new Map<string, SearchSource>();
        for (const image of restoredImages) {
          if (image.imageKey) restoredImageMap.set(image.imageKey, image);
        }
        if (restoredImageMap.size > 0) {
          searchImagesRegistry.set(messageId, restoredImageMap);
        }
        const restoredConversationSources =
          conversationSourcesRegistry.get(messageId) ?? [];
        conversationSourcesRegistry.set(messageId, [
          ...restoredConversationSources.filter((source) => !source.isImage),
          ...restoredImages,
        ]);

        // Emit a `source` part for each persisted search result so the
        // `group-source` block renders the inline "检索结果" trigger button.
        // Mirrors the streaming adapter's end-of-stream emission, but uses the
        // already-aggregated `msg.search` data instead of rebuilding it from
        // the raw SSE chunks.
        if (Array.isArray(msg.search) && msg.search.length > 0) {
          for (const searchItem of msg.search) {
            if (typeof searchItem === "object" && searchItem !== null) {
              const item = searchItem as Record<string, unknown>;
              const scoreDetails = item.score_details as
                Record<string, unknown> | undefined;
              const searchImageKey = `${item.tool_sign ?? ""}${item.cite_index ?? ""}`;
              if (
                scoreDetails?.chunk_type === "image" ||
                answerImageKeys.includes(searchImageKey)
              )
                continue;
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

        // Keep image sources adjacent to regular sources so GroupedParts
        // creates one unified source button and side panel selection.
        for (const image of restoredImages) {
          content.push(image);
        }
      }

      const orderedContent = collapseSubAgentParts(content);
      content.splice(0, content.length, ...orderedContent);

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
        if (msg.role === "assistant") assistantIdx++;
        continue;
      }

      // Persist the historical step breakdown on message metadata so
      // `SingleTurnTokenUsage` can find it via the same selector it uses for
      // the streaming flow (which writes to a global registry). assistant-ui
      // requires `metadata.custom` to be present on every message, so we
      // always include the field and only set the token bucket when we have
      // historical step data.
      const createdAt = toMessageCreatedAt(msg.create_time);
      const metadata = {
        custom: {
          ...(stepTokenCounts.length > 0 ? { stepTokenCounts } : {}),
          ...(createdAt ? { databaseCreateTime: createdAt.getTime() } : {}),
          ...(providerCallUsages.length > 0 ? { providerCallUsages } : {}),
          ...(turnUsage ? { turnUsage } : {}),
        },
      };

      messages.push({
        id: messageId,
        role: msg.role,
        content,
        ...(createdAt ? { createdAt } : {}),
        ...(msg.role === "user" && attachments.length > 0
          ? { attachments }
          : {}),
        metadata,
      });

      if (msg.role === "assistant") assistantIdx++;
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
    const resumedRun = remoteChatModelAdapter.run({
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

const INITIAL_CONVERSATION_PAGE_SIZE = 30;

const parseConversationListOffset = (after: string | undefined): number => {
  if (after === undefined) return 0;

  const offset = Number(after);
  return Number.isSafeInteger(offset) &&
    offset >= 0 &&
    offset <= Number.MAX_SAFE_INTEGER - CONVERSATION_PAGE_SIZE
    ? offset
    : 0;
};

const createHistoryProvider = (): FC<PropsWithChildren> => {
  const Provider: FC<PropsWithChildren> = ({ children }) => {
    const aui = useAui();

    const history = useMemo(
      () =>
        new RemoteConversationHistoryAdapter(
          () => aui.threadListItem.getState().remoteId,
          () => aui.threadListItem.initialize()
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

const createShareHistoryProvider = (
  snapshot: ApiConversationDetail
): FC<PropsWithChildren> => {
  const Provider: FC<PropsWithChildren> = ({ children }) => {
    const aui = useAui();
    const history = useMemo(
      () =>
        new RemoteConversationHistoryAdapter(
          () => aui.threadListItem.getState().remoteId,
          () => aui.threadListItem.initialize(),
          async () => snapshot
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

/**
 * Creates a single, read-only thread adapter for a public new-chat share.
 * It deliberately reuses RemoteConversationHistoryAdapter so the snapshot is
 * reconstructed with the exact same Tool Call, Reasoning, source and
 * attachment mapping used by a normal historical conversation.
 */
export const createShareThreadListAdapter = (
  snapshot: ApiConversationDetail
): RemoteThreadListAdapter => {
  const remoteId = String(snapshot.conversation_id);
  const title =
    (snapshot as ApiConversationDetail & { conversation_title?: string })
      .conversation_title || "Shared conversation";
  const metadata: RemoteThreadMetadata = {
    remoteId,
    status: "regular",
    title,
  };

  return {
    unstable_Provider: createShareHistoryProvider(snapshot),
    async list(): Promise<RemoteThreadListResponse> {
      return { threads: [metadata] };
    },
    async initialize(): Promise<RemoteThreadInitializeResponse> {
      return { remoteId, externalId: remoteId };
    },
    async fetch(): Promise<RemoteThreadMetadata> {
      return metadata;
    },
    async rename(): Promise<void> {},
    async archive(): Promise<void> {},
    async unarchive(): Promise<void> {},
    async delete(): Promise<void> {},
    async generateTitle() {
      return createAssistantStream(() => {});
    },
  };
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

let pendingThreadOperationId: string | undefined;

export const setPendingThreadOperationId = (threadId: string | undefined) => {
  pendingThreadOperationId = threadId;
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

  const isValidConversationId = (value: string | undefined): value is string =>
    Boolean(value) && Number.isInteger(Number(value)) && Number(value) > 0;

  // Existing threads already have a server id in `remoteId`, which is more
  // reliable than the active-thread registry while the sidebar is switching.
  if (isValidConversationId(fallbackRemoteId)) return fallbackRemoteId;

  // New threads use an empty remoteId until they are reloaded from the
  // backend. The sidebar captures the local ID before calling rename/delete,
  // because assistant-ui may switch the active thread as part of that action.
  const readNow = (): string | undefined => {
    if (pendingThreadOperationId) {
      const fromPendingThread = idsRef.current.get(pendingThreadOperationId);
      if (isValidConversationId(fromPendingThread)) return fromPendingThread;
    }

    const activeThreadId = getActiveThreadId();
    if (!activeThreadId) return undefined;
    const fromActiveThread = idsRef.current.get(activeThreadId);
    return isValidConversationId(fromActiveThread)
      ? fromActiveThread
      : undefined;
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

  async list({ after } = {}): Promise<RemoteThreadListResponse> {
    const { todayStartMs, weekStartMs } = getConversationDateBoundaries();
    const offset = parseConversationListOffset(after);
    const limit =
      offset === 0 ? INITIAL_CONVERSATION_PAGE_SIZE : CONVERSATION_PAGE_SIZE;
    const data = await conversationService.getList({
      offset,
      limit,
      todayStartMs,
      weekStartMs,
    });
    const nextOffset = offset + data.items.length;

    return {
      threads: data.items.map(toRemoteThreadMetadata),
      nextCursor:
        nextOffset < data.metadata.total ? String(nextOffset) : undefined,
    };
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
    const candidateId = await waitForServerConversationId(remoteId);
    const conversationId = Number(candidateId);
    if (
      !candidateId ||
      !Number.isInteger(conversationId) ||
      conversationId <= 0
    ) {
      throw new Error(
        "Cannot delete a conversation without a backend conversation ID."
      );
    }
    await conversationService.delete(conversationId);
  },

  async fetch(threadId: string): Promise<RemoteThreadMetadata> {
    const detail = await conversationService.getById(threadId);

    return toRemoteThreadMetadata({
      conversation_id: Number(detail.conversation_id),
      conversation_title: detail.conversation_title ?? "Untitled conversation",
      agent_id: detail.agent_id,
      create_time: detail.create_time,
      update_time: detail.create_time,
    });
  },

  async generateTitle(_remoteId, _messages) {
    // Title generation is initiated by the page after agent/run returns the
    // real backend conversation ID. This avoids racing the first run.
    return createAssistantStream(() => {});
  },
};
