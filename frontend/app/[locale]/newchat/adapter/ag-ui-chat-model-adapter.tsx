"use client";

import type {
  ChatModelAdapter,
  ChatModelRunOptions,
  ChatModelRunResult,
  CompleteAttachment,
} from "@assistant-ui/react";
import type { ThreadMessage } from "@assistant-ui/core";
import {
  HttpAgent,
  type AGUIEvent,
  type BaseEvent,
  type CustomEvent as AGUICustomEvent,
  type RunAgentInput,
} from "@ag-ui/client";

import { API_ENDPOINTS } from "@/services/api";
import { conversationService } from "@/services/conversationService";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import {
  attachSearchContentToTool,
  attachSearchImageToTool,
  clearStepTokenCounts,
  makeSubAgentMetadata,
  markSubAgentRunFinished,
  parsePlan,
  parsePlanStepUpdate,
  parseSkillFileAttachments,
  parseStepTokenCount,
  planRegistry,
  pushStepTokenCount,
  searchSourcesRegistry,
  skillFileUploadsRegistry,
  type SearchSource,
} from "./remote-chat-model-adapter";
import {
  acceptA2UIAction,
  aliasA2UISession,
  completeA2UIAction,
  consumePendingA2UIAction,
  createA2UIDataPart,
  markA2UIFormSubmitted,
  processA2UIEnvelope,
  type A2UIActionSubmission,
} from "../a2ui/runtime";
import {
  parseA2UIFormSubmissionState,
  type A2UIFormSubmissionState,
} from "../a2ui/form-submission-store";

interface MutablePart extends Record<string, unknown> {
  type: string;
  text?: string;
  argsText?: string;
  args?: unknown;
  result?: unknown;
  status?: Record<string, unknown>;
  metadata?: unknown;
}

const extractText = (message: ThreadMessage): string =>
  message.content
    .map((part) =>
      part.type === "text"
        ? (part.text ?? "")
        : part.type === "image"
          ? "[image]"
          : ""
    )
    .join("");

const extractMinioFiles = (message: ThreadMessage | undefined) => {
  const attachments = message?.attachments as
    | Array<
        Record<string, unknown> & {
          name?: string;
          object_name?: string;
          url?: string;
        }
      >
    | undefined;
  return (attachments ?? [])
    .filter((attachment) => attachment.object_name && attachment.url)
    .map((attachment) => ({
      name: attachment.name ?? "attachment",
      object_name: attachment.object_name,
      type: attachment.type ?? attachment.contentType ?? "file",
      size: attachment.size ?? 0,
      url: attachment.url,
      presigned_url: attachment.presigned_url,
    }));
};

const toAGUIMessages = (messages: readonly ThreadMessage[]) =>
  messages
    .filter(
      (message) => message.role === "user" || message.role === "assistant"
    )
    .map((message, index) => ({
      id: message.id || `message-${index}`,
      role: message.role as "user" | "assistant",
      content: extractText(message),
    }));

const valueAsObject = (value: unknown): Record<string, unknown> => {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return parsed && typeof parsed === "object" ? parsed : { value };
    } catch {
      return { value };
    }
  }
  return { value };
};

const toRunResult = (
  parts: MutablePart[],
  messageId: string
): ChatModelRunResult =>
  ({
    content: [...parts] as unknown as ChatModelRunResult["content"],
    messageId,
  }) as ChatModelRunResult;

const findPersistedFormSubmission = (
  messages: Array<{ a2ui_submission?: unknown }> | undefined,
  action: A2UIActionSubmission
): A2UIFormSubmissionState | null => {
  const identity = action.message.action;
  for (const message of messages ?? []) {
    const state = parseA2UIFormSubmissionState(message.a2ui_submission);
    if (
      state?.surfaceId === identity.surfaceId &&
      state.sourceComponentId === identity.sourceComponentId
    ) {
      return state;
    }
  }
  return null;
};

interface QueueItem {
  event?: BaseEvent;
  done?: boolean;
  error?: unknown;
}

class AsyncEventQueue {
  private values: QueueItem[] = [];
  private waiters: Array<(value: QueueItem) => void> = [];

  push(value: QueueItem) {
    const waiter = this.waiters.shift();
    if (waiter) waiter(value);
    else this.values.push(value);
  }

  async next(): Promise<QueueItem> {
    const value = this.values.shift();
    if (value) return value;
    return new Promise((resolve) => this.waiters.push(resolve));
  }
}

export const agUIChatModelAdapter: ChatModelAdapter = {
  async *run({
    messages,
    abortSignal,
    context,
    runConfig,
    unstable_threadId,
  }: ChatModelRunOptions): AsyncGenerator<ChatModelRunResult, void> {
    clearStepTokenCounts();
    const custom = (runConfig?.custom ?? {}) as {
      threadId?: string;
      a2uiSessionKey?: string;
      agentId?: string | number;
      enablePlan?: boolean;
      resume?: boolean;
      onServerConversationId?: (
        serverId: string,
        initialQuestion?: string
      ) => void;
    };
    const sessionKey =
      custom.a2uiSessionKey ||
      custom.threadId ||
      unstable_threadId ||
      crypto.randomUUID();
    const numericConversationId = Number(custom.threadId);
    const hasConversationId =
      Number.isInteger(numericConversationId) && numericConversationId > 0;
    const lastUserMessage = [...messages]
      .reverse()
      .find((message) => message.role === "user");
    if (!custom.resume && !lastUserMessage) return;

    const pendingAction = consumePendingA2UIAction(sessionKey);
    const submissionId = pendingAction?.submissionId;
    const isFormAction = pendingAction?.formSubmission !== undefined;
    let formAccepted = !isFormAction;
    const forwardedProps = {
      nexent: {
        conversationId: hasConversationId ? numericConversationId : null,
        agentId: custom.agentId == null ? null : Number(custom.agentId),
        modelId: context.config?.modelName
          ? Number(context.config.modelName)
          : null,
        versionNo: 0,
        requestedOutputTokens: null,
        minioFiles: custom.resume ? [] : extractMinioFiles(lastUserMessage),
        isDebug: false,
        enablePlan: custom.enablePlan === true,
        toolParams: null,
        contextPolicy: null,
        resume: custom.resume === true,
        capabilities: { a2ui: { versions: ["v0.9"], catalogId: "nexent.v1" } },
        a2uiAction: pendingAction,
      },
    };
    const threadId =
      unstable_threadId ?? custom.threadId ?? crypto.randomUUID();
    const runId = crypto.randomUUID();
    const messageId = `agui-${runId}`;
    const input: RunAgentInput = {
      threadId,
      runId,
      state: {},
      messages: toAGUIMessages(messages),
      tools: [],
      context: [],
      forwardedProps,
    };
    const queue = new AsyncEventQueue();
    let agent: HttpAgent;
    let subscription: { unsubscribe: () => void };
    try {
      agent = new HttpAgent({
        url: API_ENDPOINTS.agent.runAgUi,
        headers: getAuthHeaders(),
        threadId,
      });
      subscription = agent.run(input).subscribe({
        next: (event) => queue.push({ event }),
        error: (error) => queue.push({ error }),
        complete: () => queue.push({ done: true }),
      });
    } catch (error) {
      completeA2UIAction(submissionId);
      throw error;
    }
    const onAbort = () => {
      agent.abortRun();
      if (hasConversationId) {
        void conversationService
          .stop(numericConversationId)
          .catch((error) =>
            log.warn("[AG-UI] Failed to stop backend run:", error)
          );
      }
    };
    abortSignal.addEventListener("abort", onAbort, { once: true });

    const parts: MutablePart[] = [];
    const reasoningById = new Map<string, MutablePart>();
    const textById = new Map<string, MutablePart>();
    const toolById = new Map<string, MutablePart>();
    const surfaces = new Set<string>();
    const searchSources: SearchSource[] = [];
    let skillFileAttachments: CompleteAttachment[] = [];
    let skillFilesPart: MutablePart | undefined;
    const subAgentStack: Array<ReturnType<typeof makeSubAgentMetadata>> = [];
    const applyMetadata = (part: MutablePart) => {
      const metadata = subAgentStack.at(-1);
      if (metadata) part.metadata = { ...metadata };
    };

    try {
      while (true) {
        const item = await queue.next();
        if (item.error) throw item.error;
        if (item.done) break;
        const event = item.event as AGUIEvent;
        let changed = false;
        switch (event.type) {
          case "REASONING_MESSAGE_START": {
            const part: MutablePart = {
              type: "reasoning",
              text: "",
              status: { type: "running" },
            };
            applyMetadata(part);
            reasoningById.set(event.messageId, part);
            parts.push(part);
            changed = true;
            break;
          }
          case "REASONING_MESSAGE_CONTENT": {
            const part = reasoningById.get(event.messageId);
            if (part) {
              part.text = `${part.text ?? ""}${event.delta}`;
              changed = true;
            }
            break;
          }
          case "REASONING_MESSAGE_END": {
            const part = reasoningById.get(event.messageId);
            if (part) {
              part.status = { type: "done" };
              changed = true;
            }
            break;
          }
          case "TEXT_MESSAGE_START": {
            const part: MutablePart = { type: "text", text: "" };
            applyMetadata(part);
            textById.set(event.messageId, part);
            parts.push(part);
            changed = true;
            break;
          }
          case "TEXT_MESSAGE_CONTENT": {
            const part = textById.get(event.messageId);
            if (part) {
              part.text = `${part.text ?? ""}${event.delta}`;
              changed = true;
            }
            break;
          }
          case "TOOL_CALL_START": {
            const part: MutablePart = {
              type: "tool-call",
              toolCallId: event.toolCallId,
              tool_call_id: event.toolCallId,
              toolName: event.toolCallName,
              args: {},
              argsText: "",
              status: { type: "running", isError: false },
            };
            applyMetadata(part);
            toolById.set(event.toolCallId, part);
            parts.push(part);
            changed = true;
            break;
          }
          case "TOOL_CALL_ARGS": {
            const part = toolById.get(event.toolCallId);
            if (part) {
              part.argsText = `${part.argsText ?? ""}${event.delta}`;
              try {
                part.args = JSON.parse(part.argsText);
              } catch {
                /* partial JSON */
              }
              changed = true;
            }
            break;
          }
          case "TOOL_CALL_END": {
            const part = toolById.get(event.toolCallId);
            if (part) {
              part.status = { type: "requires-action", reason: "tool-call" };
              changed = true;
            }
            break;
          }
          case "TOOL_CALL_RESULT": {
            const part = toolById.get(event.toolCallId);
            if (part) {
              part.result = event.content;
              part.status = { type: "complete" };
              changed = true;
            }
            break;
          }
          case "ACTIVITY_SNAPSHOT": {
            if (event.activityType === "nexent.plan") {
              const plan = parsePlan(
                typeof event.content === "string"
                  ? event.content
                  : JSON.stringify(event.content)
              );
              if (plan) planRegistry.set(plan);
            }
            break;
          }
          case "ACTIVITY_DELTA": {
            if (event.activityType === "nexent.plan") {
              for (const patch of event.patch ?? []) {
                const update = parsePlanStepUpdate(
                  typeof patch.value === "string"
                    ? patch.value
                    : JSON.stringify(patch.value)
                );
                if (update)
                  planRegistry.updateStep(update.stepId, update.status);
              }
            }
            break;
          }
          case "CUSTOM": {
            const customEvent = event as AGUICustomEvent;
            const value = customEvent.value;
            if (customEvent.name === "nexent.a2ui") {
              const result = processA2UIEnvelope(sessionKey, value);
              const rawSurfaceId = valueAsObject(value).surfaceId;
              const surfaceId =
                result.surfaceId ??
                (typeof rawSurfaceId === "string" ? rawSurfaceId : "invalid");
              if (
                (result.shouldRender || result.error) &&
                !surfaces.has(surfaceId)
              ) {
                parts.push(
                  createA2UIDataPart(sessionKey, surfaceId, result.error)
                );
                surfaces.add(surfaceId);
              }
              changed = true;
            } else if (customEvent.name === "nexent.a2ui.form.submitted") {
              const state = parseA2UIFormSubmissionState(value);
              if (state) {
                markA2UIFormSubmitted(sessionKey, state);
                if (state.submissionId === submissionId) {
                  formAccepted = true;
                }
              }
            } else if (customEvent.name === "nexent.conversation.created") {
              const payload = valueAsObject(value);
              const conversationId =
                payload.conversation_id ?? payload.conversationId;
              if (conversationId != null) {
                aliasA2UISession(sessionKey, String(conversationId));
                custom.onServerConversationId?.(
                  String(conversationId),
                  lastUserMessage ? extractText(lastUserMessage) : undefined
                );
              }
            } else if (customEvent.name === "nexent.token.usage") {
              const parsed = parseStepTokenCount(
                typeof value === "string" ? value : JSON.stringify(value)
              );
              if (parsed) pushStepTokenCount(parsed);
            } else if (customEvent.name === "nexent.source.search") {
              const values = Array.isArray(value) ? value : [value];
              for (const raw of values) {
                const source = valueAsObject(raw);
                const url = String(source.url ?? "");
                if (!url) continue;
                const title = String(source.title ?? url);
                attachSearchContentToTool(
                  parts,
                  { url, title },
                  typeof source.tool_call_id === "string"
                    ? source.tool_call_id
                    : undefined
                );
                searchSources.push({
                  citeIndex: Number(
                    source.cite_index ??
                      source.citeIndex ??
                      searchSources.length
                  ),
                  url,
                  title,
                  text:
                    typeof source.text === "string" ? source.text : undefined,
                  sourceType:
                    typeof source.source_type === "string"
                      ? source.source_type
                      : "url",
                });
                searchSourcesRegistry.set(messageId, [...searchSources]);
                parts.push({
                  type: "source",
                  sourceType: "url",
                  url,
                  title,
                  messageId,
                });
                changed = true;
              }
            } else if (customEvent.name === "nexent.source.image") {
              const payload = valueAsObject(value);
              const images = Array.isArray(payload.images_url)
                ? payload.images_url
                : [];
              for (const imageUrl of images) {
                if (typeof imageUrl !== "string") continue;
                attachSearchImageToTool(
                  parts,
                  imageUrl,
                  typeof payload.tool_call_id === "string"
                    ? payload.tool_call_id
                    : undefined
                );
                parts.push({
                  type: "source",
                  sourceType: "url",
                  url: imageUrl,
                  title: imageUrl,
                  isImage: true,
                });
                changed = true;
              }
            } else if (customEvent.name === "nexent.attachment") {
              const attachments = parseSkillFileAttachments(
                typeof value === "string" ? value : JSON.stringify(value),
                messageId
              );
              if (attachments.length > 0) {
                skillFileAttachments = [
                  ...skillFileAttachments,
                  ...attachments,
                ];
                skillFileUploadsRegistry.set(messageId, skillFileAttachments);
                if (skillFilesPart) {
                  skillFilesPart.skillFileAttachments = skillFileAttachments;
                } else {
                  skillFilesPart = {
                    type: "text",
                    text: "",
                    isSkillFiles: true,
                    skillFileAttachments,
                  };
                  applyMetadata(skillFilesPart);
                  parts.push(skillFilesPart);
                }
                changed = true;
              }
            } else if (customEvent.name === "nexent.subagent.start") {
              const payload = valueAsObject(value);
              const metadata = makeSubAgentMetadata({
                subagentId:
                  typeof payload.agent_id === "string" ||
                  typeof payload.agent_id === "number"
                    ? payload.agent_id
                    : "unknown",
                runId: `run-${crypto.randomUUID()}`,
                agentName: String(payload.agent_name ?? "subagent"),
                depth: Number(payload.depth ?? subAgentStack.length + 1),
                task:
                  typeof payload.task === "string" ? payload.task : undefined,
              });
              subAgentStack.push(metadata);
              parts.push({
                type: "data",
                name: "subagent-boundary",
                data: { kind: "start", ...metadata },
                metadata,
              });
              changed = true;
            } else if (customEvent.name === "nexent.subagent.end") {
              const metadata = subAgentStack.pop();
              if (metadata) markSubAgentRunFinished(parts, metadata.runId);
              changed = true;
            }
            break;
          }
          case "RUN_ERROR": {
            parts.push({
              type: "text",
              text: event.message || "Agent run failed",
              isError: true,
            });
            changed = true;
            break;
          }
        }
        if (changed) yield toRunResult(parts, messageId);
      }
      yield toRunResult(parts, messageId);
    } catch (error) {
      if (!abortSignal.aborted) {
        log.error("[AG-UI] Stream failed:", error);
        parts.push({
          type: "text",
          text: error instanceof Error ? error.message : "Agent run failed",
          isError: true,
        });
        yield toRunResult(parts, messageId);
      }
    } finally {
      if (isFormAction && !formAccepted && pendingAction && hasConversationId) {
        try {
          const response = await conversationService.getDetail(
            numericConversationId
          );
          const state = findPersistedFormSubmission(
            response.data?.[0]?.message,
            pendingAction
          );
          if (state) {
            markA2UIFormSubmitted(sessionKey, state);
            acceptA2UIAction(submissionId, sessionKey);
            formAccepted = true;
          }
        } catch (error) {
          log.warn("[AG-UI] Failed to reconcile A2UI Form state:", error);
        }
      }
      if (!formAccepted) completeA2UIAction(submissionId);
      else if (!isFormAction) completeA2UIAction(submissionId);
      abortSignal.removeEventListener("abort", onAbort);
      subscription.unsubscribe();
    }
  },
};
