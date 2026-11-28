// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  useMemo,
  useEffect,
  useState,
  useSyncExternalStore,
  type FC,
  type ReactNode,
} from "react";
import { skipToken, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ComposerAttachment, ComposerDictation } from "./composer-tools";
import { CreationExamples } from "@/features/workbench/components/CreationExamples";
import { SelectedResourceTags } from "@/features/workbench/components/SelectedResourceTags";
import {
  Send,
  CircleStop,
  Play,
  Check,
  Circle,
  ListChecks,
  ChevronDown,
  MessageCircleMore,
  Bot,
  Sparkles,
} from "lucide-react";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { conversationService } from "@/services/conversationService";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  ComposerPrimitive,
  useAui,
  useAuiState,
  type CompleteAttachment,
  type ThreadRuntime,
} from "@assistant-ui/react";
import {
  LexicalComposerInput,
  type DirectiveChipProps as LexicalDirectiveChipProps,
} from "@assistant-ui/react-lexical";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ModelSelector, type ModelOption } from "../ui/model-selector";
import { ComposerAttachments } from "../ui/attachment";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  planRegistry,
  type PlanData,
} from "../adapter/remote-chat-model-adapter";
import type {
  ConversationKnowledgeScope,
  KnowledgeCapabilities,
  KnowledgeScopeEffectivePreview,
} from "@/types/knowledgeScope";
import { ConversationKnowledgeScopeModal } from "./conversation-knowledge-scope-modal";
import { useDeployment } from "@/components/providers/deploymentProvider";
import type { SkillFileContent } from "@/types/skill";
import { SkillFileMentionPopover } from "../ui/skill-file-mention";
import { DirectiveChip } from "../ui/directive-text";
import {
  combinedSkillDirectiveFormatter,
  skillDirectiveIconMap,
} from "../ui/skill-directives";
import { ordinarySendError, protectOrdinarySend } from "../utils/ordinary-send";
import { ComposerAnnotationChip } from "./annotation-chip";
import {
  toMessageAnnotationWireItems,
  type MessageAnnotationsControl,
} from "../utils/message-annotations";
import { RuntimeMetadataEditor } from "@/components/chat/RuntimeMetadataEditor";
import { getConversationResourceLimitMessage } from "@/const/errorMessageI18n";

const SkillStackIcon: FC<{ className?: string }> = ({ className }) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={cn("shrink-0", className)}
    aria-hidden
  >
    <path d="M12 3.8 20 7 12 10.2 4 7 12 3.8Z" />
    <path d="M20.3 12.2c-2.3 1.8-5.2 2.7-8.3 2.7s-6-.9-8.3-2.7" />
    <path d="M20.3 16.4c-2.3 1.8-5.2 2.7-8.3 2.7s-6-.9-8.3-2.7" />
    <path
      d="M18.7 1.7q.7 2 2.75 2.75-2.05.75-2.75 2.8-.7-2.05-2.75-2.8 2.05-.75 2.75-2.75Z"
      fill="currentColor"
      stroke="none"
    />
  </svg>
);

const KnowledgeBookIcon: FC<{ className?: string }> = ({ className }) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={cn("shrink-0", className)}
    aria-hidden
  >
    {/* Open book: left edge, twin peaks across the top, partial right edge */}
    <path d="M3 19.5V6.2c0-1.2 1-2.2 2.2-2.1 1.4.1 3.7 1.5 5.7 6.8 1.4-3.3 3.2-5.9 4.8-6.5 1.4-.5 2.9.2 3.8 1.5.3.4.5.9.5 1.4v7.3" />
    {/* Wavy bottom edge of the left page */}
    <path d="M3.2 19.4c2.4-.8 5.2-.7 7.8.2" />
    {/* Center spine */}
    <path d="M10.9 11.2v8.2" />
    {/* Solid four-point sparkle */}
    <path
      d="M19.8 14.1q.85 2.2 3.05 3.05-2.2.85-3.05 3.05-.85-2.2-3.05-3.05 2.2-.85 3.05-3.05Z"
      fill="currentColor"
      stroke="none"
    />
  </svg>
);

export type ChatMode = "planning" | "execution";

/**
 * Drops the annotation payload from the composer runConfig.
 *
 * The fallback send path (in-flight attachment uploads) parks the structured
 * annotations on the composer runConfig because the library owns the append
 * there. Once the run settles the payload must be cleared again so it cannot
 * ride a later programmatic send that bypasses `prepareSend` (edit resends,
 * clarification cards).
 */
function clearComposerMessageAnnotations(thread: ThreadRuntime) {
  const config = thread.composer.getState().runConfig;
  thread.composer.setRunConfig({
    ...config,
    custom: { ...config.custom, messageAnnotations: undefined },
  });
}

export interface ComposerInputTools {
  attachments?: boolean;
  dictationConfigured?: boolean;
}

export interface ComposerProps {
  conversationId?: number;
  models: readonly ModelOption[];
  selectedModelId?: string;
  onModelChange?: (modelId: string) => void;
  chatMode: ChatMode;
  onChatModeChange?: (mode: ChatMode) => void;
  showModelSelector?: boolean;
  children?: ReactNode;
  inputTools?: ComposerInputTools;
  knowledgeScope?: ConversationKnowledgeScope | null;
  knowledgePreview?: KnowledgeScopeEffectivePreview | null;
  knowledgeCapabilities?: KnowledgeCapabilities | null;
  knowledgeAgent?: {
    id: number;
    versionNo?: number;
    sources?: { local: boolean; aidp: boolean };
  };
  onKnowledgeScopeChange?: (
    scope: ConversationKnowledgeScope | null,
    preview?: KnowledgeScopeEffectivePreview | null
  ) => Promise<void> | void;
  skillFiles?: readonly SkillFileContent[];
  runtimeMetadata?: Record<string, unknown>;
  onRuntimeMetadataChange?: (value: Record<string, unknown>) => void;
  allowRuntimeMetadata?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  modelSelectionDisabled?: boolean;
  configurationLayout?: boolean;
  hidePlan?: boolean;
  /** Override send and cancel for a shared draft. An accepted send clears the input. */
  submission?: {
    isRunning: boolean;
    send: (text: string) => boolean;
    cancel: () => void;
  };
  workbenchPresentation?: import("@/features/workbench/types").WorkbenchComposerPresentation;
  workbenchResources?: import("@/features/workbench/types").WorkbenchResourceControls;
  onOpenWorkbenchSkillPicker?: () => void;
  /** Pending reply annotations attached to the next outgoing message. */
  annotations?: MessageAnnotationsControl;
}

// Simple tooltip wrapper
const TooltipWrapper: FC<{
  tooltip: string;
  side?: "top" | "bottom" | "left" | "right";
  wrapTrigger?: boolean;
  children: ReactNode;
}> = ({ tooltip, side = "bottom", wrapTrigger = false, children }) => {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {wrapTrigger ? (
          <span className="inline-flex">{children}</span>
        ) : (
          children
        )}
      </TooltipTrigger>
      <TooltipContent side={side}>{tooltip}</TooltipContent>
    </Tooltip>
  );
};

const PlanView: FC<{ className?: string }> = ({ className }) => {
  const { t } = useTranslation();
  const plan = useSyncExternalStore<PlanData | null>(
    planRegistry.subscribe,
    () => planRegistry.data,
    () => null
  );

  if (!plan || plan.steps.length === 0) return null;

  return (
    <Collapsible asChild defaultOpen>
      <section
        className={cn("border-b border-border", className)}
        aria-label={t("chat.composer.plan")}
      >
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full cursor-pointer items-center gap-2 px-4 py-3 text-left text-xs font-medium text-foreground transition-colors hover:bg-muted/40 data-[state=closed]:[&_svg.plan-chevron]:rotate-180"
          >
            <ListChecks className="size-4 shrink-0 text-primary" aria-hidden />
            <span className="min-w-0 flex-1 truncate">{plan.title}</span>
            <ChevronDown
              className="plan-chevron size-4 shrink-0 text-muted-foreground transition-transform duration-200"
              aria-hidden
            />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <ol className="space-y-1.5 px-4 pb-3">
            {plan.steps.map((step) => {
              const completed = step.status === "completed";
              return (
                <li
                  key={step.id}
                  className={cn(
                    "flex min-w-0 items-center gap-3 text-xs leading-5 text-muted-foreground",
                    completed && "text-muted-foreground/60"
                  )}
                >
                  {completed ? (
                    <Check
                      className="size-4 shrink-0 text-emerald-600"
                      aria-hidden
                    />
                  ) : (
                    <Circle className="size-4 shrink-0" aria-hidden />
                  )}
                  <span
                    className={cn(
                      "min-w-0 max-w-[40%] shrink-0 truncate font-medium text-foreground",
                      completed && "text-muted-foreground/60 line-through"
                    )}
                    title={step.title}
                  >
                    {step.title}
                  </span>
                  {step.description && (
                    <span
                      className={cn(
                        "min-w-0 flex-1 truncate text-left",
                        completed && "line-through"
                      )}
                      title={step.description}
                    >
                      {step.description}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </CollapsibleContent>
      </section>
    </Collapsible>
  );
};

const SkillComposerDirectiveChip: FC<LexicalDirectiveChipProps> = ({
  directiveId,
  directiveType,
  label,
}) => (
  <DirectiveChip
    segment={{
      kind: "mention",
      id: directiveId,
      type: directiveType,
      label,
    }}
    iconMap={skillDirectiveIconMap}
  />
);

export const Composer: FC<ComposerProps> = ({
  conversationId,
  models,
  selectedModelId,
  onModelChange,
  chatMode,
  onChatModeChange,
  showModelSelector = true,
  children,
  inputTools,
  knowledgeScope = null,
  knowledgePreview = null,
  knowledgeCapabilities: suppliedKnowledgeCapabilities = null,
  knowledgeAgent,
  onKnowledgeScopeChange,
  skillFiles,
  runtimeMetadata = {},
  onRuntimeMetadataChange,
  allowRuntimeMetadata = false,
  disabled = false,
  disabledReason,
  modelSelectionDisabled,
  configurationLayout = false,
  hidePlan = false,
  submission,
  workbenchPresentation,
  workbenchResources,
  onOpenWorkbenchSkillPicker,
  annotations,
}) => {
  const { t, i18n } = useTranslation();
  const aui = useAui();
  const modelParameterScope = useAuiState(
    (state) => state.threads?.mainThreadId
  );
  const runtime = aui.threads().__internal_getAssistantRuntime?.();
  const [sendError, setSendError] = useState("");
  const [removingResource, setRemovingResource] = useState(false);
  const prepareSend = (event?: { preventDefault: () => void }) => {
    if (!runtime || runtime.thread.getState().isRunning) return;
    const threadId = runtime.threads.getState().mainThreadId;
    const thread = runtime.threads.getById(threadId);
    const composerState = thread.composer.getState();
    if (submission) {
      event?.preventDefault();
      if (
        !disabled &&
        !submission.isRunning &&
        submission.send(composerState.text)
      ) {
        thread.composer.setText("");
      }
      return;
    }
    const config = composerState.runConfig;
    setSendError("");
    const pendingAnnotations = annotations?.annotations ?? [];
    const feedback = protectOrdinarySend(thread, {
      restoreDraft: true,
      // Annotations attach to exactly one outgoing message: consume them
      // once the run accepts them. A rejected send keeps them (together
      // with the restored draft) so the user can retry.
      onStarted: pendingAnnotations.length
        ? () => {
            annotations?.consumeAnnotations();
            clearComposerMessageAnnotations(thread);
          }
        : undefined,
      onRejected: (error) => {
        clearComposerMessageAnnotations(thread);
        if (runtime.threads.getState().mainThreadId === threadId) {
          setSendError(
            ordinarySendError(error, i18n.language, (value) =>
              getConversationResourceLimitMessage(value, t)
            )
          );
        }
      },
    });
    if (!pendingAnnotations.length) {
      // Ordinary send: keep the library-managed composer submit untouched.
      // The explicit undefined drops any annotation payload left on the
      // composer runConfig by a previous fallback send.
      thread.composer.setRunConfig({
        ...config,
        custom: {
          ...config.custom,
          ...feedback,
          modelPreferenceScope: modelParameterScope,
          messageAnnotations: undefined,
        },
      });
      return;
    }

    // Reply annotations travel as a structured field alongside the clean
    // composer text; the backend persists them as a unit and merges them
    // into the model-facing text at request time.
    const annotationItems = toMessageAnnotationWireItems(pendingAnnotations);
    const attachmentsReady = composerState.attachments.every(
      (attachment) => attachment.status.type === "complete"
    );
    if (!attachmentsReady) {
      // In-flight uploads must go through the library submission flow,
      // which waits for uploads before appending; ride the annotations via
      // the runConfig channel there (the optimistic bubble shows no cards
      // until reload).
      thread.composer.setRunConfig({
        ...config,
        custom: {
          ...config.custom,
          ...feedback,
          modelPreferenceScope: modelParameterScope,
          messageAnnotations: annotationItems,
        },
      });
      return;
    }

    // Take over the append so the optimistic message carries the structured
    // annotation metadata (rendered as cards on the user bubble). Preventing
    // the default keeps the library from appending a second message; the
    // composer draft is cleared manually to match the library send behavior.
    event?.preventDefault();
    if (composerState.dictation) {
      thread.composer.stopDictation();
    }
    const completeAttachments = composerState.attachments.filter(
      (attachment): attachment is CompleteAttachment =>
        attachment.status.type === "complete"
    );
    thread.append({
      role: "user",
      content: composerState.text
        ? [{ type: "text", text: composerState.text }]
        : [],
      attachments: completeAttachments,
      metadata: { custom: { annotations: annotationItems } },
      runConfig: {
        ...config,
        custom: {
          ...config.custom,
          ...feedback,
          modelPreferenceScope: modelParameterScope,
          messageAnnotations: annotationItems,
        },
      },
    });
    thread.composer.setText("");
    void thread.composer.clearAttachments();
  };
  const creationMode =
    workbenchPresentation?.mode === "skill_create" ||
    workbenchPresentation?.mode === "agent_create"
      ? workbenchPresentation.mode
      : null;
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();
  const knowledgeSource = enableAidpKnowledge ? "aidp" : "local";
  const allowsSessionKnowledge =
    workbenchPresentation?.allowsSessionKnowledge === true;
  const hasKnowledgeControl = Boolean(
    isDeploymentReady && !creationMode && onKnowledgeScopeChange
  );
  const loadKnowledgeOnOpen = !allowsSessionKnowledge && !!knowledgeAgent;
  const configuredKnowledgeSource =
    knowledgeAgent?.sources?.[knowledgeSource] === true;
  const { user } = useAuthorizationContext();
  const suppliedSourceEnabled =
    suppliedKnowledgeCapabilities?.sources[knowledgeSource].enabled;
  const knowledgeEntryEnabled =
    hasKnowledgeControl &&
    (allowsSessionKnowledge ||
      (loadKnowledgeOnOpen
        ? configuredKnowledgeSource
        : suppliedSourceEnabled === true));
  const knowledgeAccessKey = loadKnowledgeOnOpen
    ? JSON.stringify([
        user?.tenantId,
        user?.id,
        knowledgeAgent?.id,
        knowledgeAgent?.versionNo,
        knowledgeSource,
        configuredKnowledgeSource,
        modelParameterScope,
      ])
    : allowsSessionKnowledge
      ? `session:${knowledgeSource}:${modelParameterScope}:${knowledgeEntryEnabled}`
      : `${suppliedKnowledgeCapabilities?.agent_id}:${suppliedKnowledgeCapabilities?.version_no}:${knowledgeSource}:${hasKnowledgeControl && suppliedSourceEnabled === true}`;
  const [knowledgeModalState, setKnowledgeModalState] = useState({
    key: knowledgeAccessKey,
    open: false,
  });
  if (knowledgeModalState.key !== knowledgeAccessKey) {
    setKnowledgeModalState({ key: knowledgeAccessKey, open: false });
  }
  const knowledgeModalOpen =
    knowledgeEntryEnabled &&
    knowledgeModalState.key === knowledgeAccessKey &&
    knowledgeModalState.open;
  const setKnowledgeModalOpen = (open: boolean) =>
    setKnowledgeModalState((current) =>
      current.key === knowledgeAccessKey
        ? { key: knowledgeAccessKey, open }
        : current
    );
  const agentId = knowledgeAgent?.id;
  const versionNo = knowledgeAgent?.versionNo;
  const capabilityQuery = useQuery({
    queryKey: [
      "agent-chat-knowledge-capabilities",
      user?.tenantId,
      user?.id,
      agentId,
      versionNo,
      knowledgeSource,
    ],
    enabled: loadKnowledgeOnOpen && knowledgeModalOpen,
    queryFn:
      loadKnowledgeOnOpen && agentId !== undefined
        ? async () => {
            const capabilities =
              await conversationService.getKnowledgeCapabilities(
                agentId,
                versionNo
              );
            if (
              capabilities?.agent_id !== agentId ||
              (versionNo !== undefined && capabilities.version_no !== versionNo)
            ) {
              throw new Error(
                "Knowledge capabilities do not match the current agent"
              );
            }
            return capabilities;
          }
        : skipToken,
    staleTime: 30_000,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const knowledgeCapabilities = loadKnowledgeOnOpen
    ? (capabilityQuery.data ?? null)
    : suppliedKnowledgeCapabilities;
  const sourceEnabled = knowledgeCapabilities?.sources[knowledgeSource].enabled;
  const canSelectKnowledge =
    knowledgeEntryEnabled && (allowsSessionKnowledge || sourceEnabled === true);
  const toolbar = {
    mode: !creationMode ? onChatModeChange : undefined,
    agent: !creationMode ? workbenchResources?.onSelectAgent : undefined,
    knowledge: knowledgeEntryEnabled,
    skill: !creationMode ? onOpenWorkbenchSkillPicker : undefined,
    metadata: allowRuntimeMetadata ? onRuntimeMetadataChange : undefined,
  };
  const onKnowledgeOpenChange = workbenchPresentation?.onKnowledgeOpenChange;
  useEffect(() => {
    onKnowledgeOpenChange?.(knowledgeModalOpen);
    return () => onKnowledgeOpenChange?.(false);
  }, [knowledgeModalOpen, onKnowledgeOpenChange]);
  const isThreadRunning = useAuiState((state) => state.thread.isRunning);
  const isRunning = submission?.isRunning ?? isThreadRunning;
  const hasAttachments = useAuiState(
    (state) => state.composer.attachments.length > 0
  );
  const agentCount = workbenchResources?.agents.length ?? 0;
  const skillCount = workbenchResources?.skills.length ?? 0;
  const knowledgeIds =
    knowledgeSource === "local"
      ? knowledgeScope?.local.mode === "override"
        ? knowledgeScope.local.knowledge_ids
        : []
      : knowledgeScope?.aidp.mode === "override"
        ? knowledgeScope.aidp.kds_ids
        : [];
  const knowledgeCount = knowledgeIds.length;
  const knowledgePreviewIds =
    knowledgeSource === "local"
      ? knowledgePreview?.local.knowledge_ids
      : knowledgePreview?.aidp.kds_ids;
  const knowledgePreviewNames =
    knowledgePreview?.[knowledgeSource].display_names;
  const knowledgeNamesById = new Map(
    knowledgePreviewIds?.map((id, index) => [
      id,
      knowledgePreviewNames?.[index],
    ])
  );
  const knowledgeResources = knowledgeIds.map((id) => ({
    id,
    name: knowledgeNamesById.get(id) || `#${id}`,
  }));
  const removeKnowledge = (id: string) => {
    if (!knowledgeScope || !onKnowledgeScopeChange) return;
    const remaining = knowledgeResources.filter((item) => item.id !== id);
    const ids = remaining.map((item) => item.id);
    const display_names = remaining.map((item) => item.name);
    const mode = ids.length > 0 ? "override" : "disabled";
    const local = knowledgeSource === "local";
    const nextScope: ConversationKnowledgeScope = {
      ...knowledgeScope,
      local: local ? { mode, knowledge_ids: ids } : knowledgeScope.local,
      aidp: local ? knowledgeScope.aidp : { mode, kds_ids: ids },
    };
    return onKnowledgeScopeChange(nextScope, {
      local: local
        ? { disabled: !ids.length, knowledge_ids: ids, display_names }
        : (knowledgePreview?.local ?? {
            disabled: nextScope.local.mode === "disabled",
            knowledge_ids: [],
            display_names: [],
          }),
      aidp: local
        ? (knowledgePreview?.aidp ?? {
            disabled: nextScope.aidp.mode === "disabled",
            kds_ids: [],
            display_names: [],
          })
        : { disabled: !ids.length, kds_ids: ids, display_names },
    });
  };
  const resourceTags = [
    ...(toolbar.agent && workbenchResources
      ? workbenchResources.agents.map(({ id, name }) => ({
          id: `agent:${id}`,
          name,
          icon: <Bot className="size-3.5" />,
          remove: () => workbenchResources.onRemoveAgent(id),
        }))
      : []),
    ...(toolbar.knowledge
      ? knowledgeResources.map(({ id, name }) => ({
          id: `knowledge:${id}`,
          name,
          icon: <KnowledgeBookIcon className="size-3.5" />,
          remove: () => removeKnowledge(id),
        }))
      : []),
    ...(toolbar.skill && workbenchResources
      ? workbenchResources.skills.map(({ id, name }) => ({
          id: `skill:${id}`,
          name,
          icon: <SkillStackIcon className="size-3.5" />,
          remove: () => workbenchResources.onRemoveSkill(id),
        }))
      : []),
  ];
  const onRemoveResource = async (id: string) => {
    const resource = resourceTags.find((item) => item.id === id);
    if (!resource || removingResource || disabled || isRunning) return;
    setRemovingResource(true);
    setSendError("");
    try {
      await resource.remove();
    } catch (error) {
      setSendError(
        error instanceof Error
          ? error.message
          : t("workbench.controls.saveConfigFailed")
      );
    } finally {
      setRemovingResource(false);
    }
  };

  const hasIncompatibleScope = Boolean(
    isDeploymentReady &&
    knowledgeScope &&
    ((knowledgeScope.local.mode === "override" && enableAidpKnowledge) ||
      (knowledgeScope.aidp.mode === "override" && !enableAidpKnowledge))
  );

  const knowledgeSummary = useMemo(() => {
    if (!knowledgeScope) return t("chat.knowledgeScope.summaryDefault");
    const selectedCount =
      (knowledgeScope.local.mode === "override"
        ? knowledgeScope.local.knowledge_ids.length
        : 0) +
      (knowledgeScope.aidp.mode === "override"
        ? knowledgeScope.aidp.kds_ids.length
        : 0);
    const selectedNames = [
      ...(knowledgeScope.local.mode === "override"
        ? (knowledgePreview?.local.display_names ?? [])
        : []),
      ...(knowledgeScope.aidp.mode === "override"
        ? (knowledgePreview?.aidp.display_names ?? [])
        : []),
    ];
    const buildSummary = (value: string) => {
      const summary = t("chat.knowledgeScope.summary", { value });
      return hasIncompatibleScope
        ? `${summary} · ${t("chat.knowledgeScope.incompatibleShort")}`
        : summary;
    };
    if (
      knowledgeScope.local.mode === "disabled" &&
      knowledgeScope.aidp.mode === "disabled"
    ) {
      return buildSummary(t("chat.knowledgeScope.summaryDisabled"));
    }
    if (
      knowledgeScope.local.mode === "inherit" &&
      knowledgeScope.aidp.mode === "inherit"
    ) {
      return t("chat.knowledgeScope.summaryDefault");
    }
    if (selectedCount === 1 && selectedNames.length === 1) {
      return buildSummary(selectedNames[0]);
    }
    if (selectedCount > 1 && selectedNames.length > 0) {
      return buildSummary(
        t("chat.knowledgeScope.summaryMultiple", {
          name: selectedNames[0],
          count: selectedCount,
        })
      );
    }
    const parts: string[] = [];
    if (knowledgeCapabilities?.sources.local.enabled) {
      parts.push(
        knowledgeScope.local.mode === "disabled"
          ? t("chat.knowledgeScope.summaryLocalDisabled")
          : knowledgeScope.local.mode === "override"
            ? t("chat.knowledgeScope.summaryLocalOverride", {
                count: knowledgeScope.local.knowledge_ids.length,
              })
            : t("chat.knowledgeScope.summaryLocalDefault")
      );
    }
    if (knowledgeCapabilities?.sources.aidp.enabled) {
      parts.push(
        knowledgeScope.aidp.mode === "disabled"
          ? t("chat.knowledgeScope.summaryAidpDisabled")
          : knowledgeScope.aidp.mode === "override"
            ? t("chat.knowledgeScope.summaryAidpOverride", {
                count: knowledgeScope.aidp.kds_ids.length,
              })
            : t("chat.knowledgeScope.summaryAidpDefault")
      );
    }
    return buildSummary(
      parts.join(" · ") || t("chat.knowledgeScope.unavailable")
    );
  }, [
    knowledgeScope,
    knowledgePreview,
    knowledgeCapabilities,
    hasIncompatibleScope,
    t,
  ]);

  const fieldsetDisabled =
    disabled && !disabledReason && modelSelectionDisabled !== false;

  return (
    <div className="relative w-full min-w-0 font-sans">
      {workbenchPresentation && workbenchPresentation.actions}
      <fieldset
        data-slot="chat-composer"
        disabled={fieldsetDisabled}
        aria-disabled={fieldsetDisabled}
        className={cn(
          "relative m-0 flex w-full min-w-0 flex-col overflow-visible gap-3 rounded-[20px] border border-[var(--color-border-separator)] bg-card p-3 text-foreground shadow-sm sm:p-4",
          fieldsetDisabled && "cursor-not-allowed opacity-60",
          configurationLayout && "min-h-[164px]"
        )}
      >
        {disabled && disabledReason ? (
          <p className="px-3 pb-1 text-xs text-amber-700" role="status">
            {disabledReason}
          </p>
        ) : null}
        {onChatModeChange &&
          !creationMode &&
          !configurationLayout &&
          !hidePlan && <PlanView className="-mx-4" />}
        {configurationLayout && (
          <div className="flex px-4 pt-4">
            <span className="inline-flex items-center gap-1 rounded-full bg-[#669fff]/[0.15] px-2 text-xs leading-[22px] text-[#477bd5]">
              <Sparkles size={14} />
              {t("nl2agent.configuration.badge")}
            </span>
          </div>
        )}
        {creationMode && !workbenchPresentation && (
          <div className="flex items-center border-b border-border px-3 py-2">
            <span className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-xs text-primary">
              {creationMode === "skill_create"
                ? t("workbench.controls.skillCreate", "技能创建")
                : t("workbench.controls.agentCreate", "智能体创建")}
            </span>
          </div>
        )}

        {/* Composer Primitive Root */}
        <ComposerPrimitive.Unstable_TriggerPopoverRoot>
          {skillFiles ? <SkillFileMentionPopover files={skillFiles} /> : null}
          <ComposerPrimitive.Root
            className="flex w-full min-w-0 flex-col gap-3 outline-none"
            onSubmit={(event) => {
              if (isRunning) event.preventDefault();
              else prepareSend(event);
            }}
            onKeyDownCapture={(event) => {
              if (isRunning && event.key === "Enter" && !event.shiftKey)
                event.preventDefault();
            }}
            onSubmitCapture={(event) => {
              if (disabled) {
                event.preventDefault();
                event.stopPropagation();
              }
            }}
          >
            {(resourceTags.length > 0 || hasAttachments) && (
              <div className="flex min-w-0 flex-col gap-2">
                <SelectedResourceTags
                  items={resourceTags}
                  compact
                  disabled={disabled || isRunning || removingResource}
                  onRemove={(id) => void onRemoveResource(id)}
                />
                {hasAttachments && <ComposerAttachments />}
              </div>
            )}
            <ComposerAnnotationChip
              annotations={annotations?.annotations ?? []}
              disabled={isRunning || disabled}
              onEditComment={(id, comment) =>
                annotations?.updateAnnotationComment(id, comment)
              }
              onRemove={(id) => annotations?.removeAnnotation(id)}
              onClear={() => annotations?.clearAnnotations()}
            />
            {skillFiles ? (
              <LexicalComposerInput
                aria-label={t("chat.composer.inputLabel")}
                placeholder=""
                className="relative mb-0 max-h-48 min-h-20 w-full bg-transparent px-0 py-0 text-sm text-foreground outline-none [&_.aui-lexical-input]:min-h-20 [&_.aui-lexical-input]:outline-none [&_.aui-lexical-placeholder]:pointer-events-none [&_.aui-lexical-placeholder]:absolute [&_.aui-lexical-placeholder]:top-0 [&_.aui-lexical-placeholder]:text-muted-foreground"
                submitMode="enter"
                autoFocus
                formatter={combinedSkillDirectiveFormatter}
                directiveChip={SkillComposerDirectiveChip}
              />
            ) : (
              <div className="flex items-start">
                <ComposerPrimitive.Input
                  data-workbench-composer
                  aria-label={t("chat.composer.inputLabel")}
                  placeholder=""
                  className={cn(
                    "max-h-48 min-h-20 min-w-0 w-auto flex-1 resize-none bg-transparent px-0 py-0 text-sm text-foreground outline-none placeholder:text-muted-foreground",
                    configurationLayout && "!min-h-[56px]"
                  )}
                  rows={1}
                  submitMode="enter"
                  autoFocus
                />
              </div>
            )}
            <div className="flex min-h-8 flex-wrap items-center justify-between gap-x-3 gap-y-2">
              <div className="flex min-w-0 flex-wrap items-center gap-1">
                {toolbar.mode && (
                  <WorkbenchPlanningMenu
                    chatMode={chatMode}
                    onChatModeChange={toolbar.mode}
                    disabled={isRunning || disabled}
                  />
                )}
                {toolbar.agent && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={isRunning || disabled || removingResource}
                    className={resourceButtonClass(agentCount)}
                    onClick={toolbar.agent}
                    aria-label={t("workbench.controls.agents", "智能体")}
                    aria-description={
                      agentCount > 0
                        ? t("knowledgeBase.selected.count", {
                            count: agentCount,
                          })
                        : undefined
                    }
                  >
                    <Bot className="size-4" />
                    {t("workbench.controls.agents", "智能体")}
                    <ResourceCount count={agentCount} />
                  </Button>
                )}
                {toolbar.knowledge && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={isRunning || disabled || removingResource}
                    className={resourceButtonClass(knowledgeCount)}
                    onClick={() => setKnowledgeModalOpen(true)}
                    aria-label={t("chat.composer.knowledgeBase")}
                    aria-description={
                      knowledgeCount > 0
                        ? t("knowledgeBase.selected.count", {
                            count: knowledgeCount,
                          })
                        : undefined
                    }
                    title={knowledgeSummary}
                  >
                    <KnowledgeBookIcon className="size-4" />
                    {t("chat.composer.knowledgeBase")}
                    <ResourceCount count={knowledgeCount} />
                  </Button>
                )}
                {toolbar.skill && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={isRunning || disabled || removingResource}
                    className={resourceButtonClass(skillCount)}
                    onClick={toolbar.skill}
                    aria-label={t("chat.composer.skills")}
                    aria-description={
                      skillCount > 0
                        ? t("knowledgeBase.selected.count", {
                            count: skillCount,
                          })
                        : undefined
                    }
                  >
                    <SkillStackIcon className="size-4" />
                    {t("chat.composer.skills")}
                    <ResourceCount count={skillCount} />
                  </Button>
                )}
                {toolbar.metadata && (
                  <RuntimeMetadataEditor
                    value={runtimeMetadata}
                    onChange={toolbar.metadata}
                    disabled={isRunning}
                  />
                )}
              </div>
              <div className="flex min-w-0 flex-[1_1_16rem] items-center justify-end gap-1">
                {showModelSelector && (
                  <ModelSelector
                    conversationId={conversationId}
                    models={models}
                    disabled={(modelSelectionDisabled ?? disabled) || isRunning}
                    parameterSettingsScopeKey={modelParameterScope}
                    parameterSettingsDisabled={disabled || isRunning}
                    showEffort
                    value={selectedModelId}
                    onValueChange={onModelChange}
                    variant="ghost"
                    size="sm"
                    className="min-w-0 max-w-[280px] text-sm font-normal leading-5 text-foreground [&_[data-slot=model-selector-value]]:text-sm [&_[data-slot=model-selector-value]]:leading-5 [&_[data-slot=model-selector-value]]:text-foreground [&_[data-slot=model-selector-value]_span]:font-normal"
                  />
                )}
                {inputTools?.attachments && <ComposerAttachment />}
                {inputTools?.dictationConfigured !== undefined && (
                  <ComposerDictation
                    configured={inputTools.dictationConfigured}
                  />
                )}
                {children}
                <ComposerSendOrCancel
                  onSend={prepareSend}
                  onCancel={submission?.cancel}
                  isRunning={isRunning}
                  disabled={disabled}
                  hasAnnotations={(annotations?.annotations.length ?? 0) > 0}
                />
              </div>
            </div>
          </ComposerPrimitive.Root>
          {knowledgeModalOpen && (
            <ConversationKnowledgeScopeModal
              key={loadKnowledgeOnOpen ? knowledgeAccessKey : undefined}
              presentation="drawer"
              disabled={isRunning || disabled}
              open={knowledgeModalOpen}
              value={knowledgeScope}
              capabilities={knowledgeCapabilities}
              requireEnabledSource={loadKnowledgeOnOpen}
              onRetryCapabilities={
                loadKnowledgeOnOpen
                  ? () => void capabilityQuery.refetch()
                  : workbenchPresentation?.onKnowledgeRetry
              }
              capabilitiesPending={
                loadKnowledgeOnOpen
                  ? !knowledgeCapabilities &&
                    (!capabilityQuery.isError || capabilityQuery.isFetching)
                  : Boolean(
                      workbenchPresentation?.onKnowledgeOpenChange &&
                      !knowledgeCapabilities &&
                      !workbenchPresentation?.knowledgeUnavailable
                    ) || workbenchPresentation?.knowledgePending
              }
              capabilitiesUnavailable={
                loadKnowledgeOnOpen
                  ? !knowledgeCapabilities &&
                    capabilityQuery.isError &&
                    !capabilityQuery.isFetching
                  : workbenchPresentation?.knowledgeUnavailable
              }
              onCancel={() => setKnowledgeModalOpen(false)}
              onConfirm={async (scope, preview) => {
                if (!canSelectKnowledge) return;
                await onKnowledgeScopeChange?.(scope, preview);
                setKnowledgeModalOpen(false);
              }}
            />
          )}
        </ComposerPrimitive.Unstable_TriggerPopoverRoot>
      </fieldset>
      {creationMode && workbenchPresentation && (
        <div className="mt-6">
          <CreationExamples mode={creationMode} />
        </div>
      )}
      {sendError ? (
        <p role="alert" className="mt-2 px-3 text-xs text-destructive">
          {sendError}
        </p>
      ) : null}
    </div>
  );
};

const resourceButtonClass = (count: number) =>
  cn(
    "h-8 gap-1.5 rounded-base px-2 text-sm font-normal text-foreground",
    count > 0 &&
      "bg-brand-soft text-primary hover:bg-brand-soft hover:text-primary"
  );

function ResourceCount({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <span className="inline-flex min-w-4 items-center justify-center rounded-base bg-primary px-1 text-xs font-medium leading-4 text-white">
      {count}
    </span>
  );
}

const WorkbenchPlanningMenu: FC<{
  chatMode: ChatMode;
  onChatModeChange: (mode: ChatMode) => void;
  disabled?: boolean;
}> = ({ chatMode, onChatModeChange, disabled }) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const options: { value: ChatMode; label: string }[] = [
    { value: "planning", label: t("chat.composer.planningMode") },
    { value: "execution", label: t("chat.composer.executionMode") },
  ];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          className="h-8 shrink-0 gap-1.5 px-2 text-sm font-normal leading-5 text-foreground"
        >
          {chatMode === "planning" ? (
            <MessageCircleMore className="size-5" />
          ) : (
            <Play className="size-5" />
          )}
          {chatMode === "planning"
            ? t("chat.composer.planningMode")
            : t("chat.composer.executionMode")}
          <ChevronDown className="size-4 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-56 p-1">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            className="flex h-10 w-full items-center justify-between gap-2 rounded-lg px-2 py-2 text-sm font-normal leading-5 hover:bg-accent"
            onClick={() => {
              onChatModeChange(option.value);
              setOpen(false);
            }}
          >
            {option.label}
            {chatMode === option.value && <Check className="size-4" />}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
};

// `ComposerPrimitive.Cancel` / `Send` forward their internal `onClick` to the
// direct child via Radix Slot, so the Button MUST be the immediate child for
// the click handler to actually fire. The tooltip wrapper sits outside so its
// Trigger can use `asChild` against the Button.
const ComposerSendOrCancel: FC<{
  onSend: (event?: { preventDefault: () => void }) => void;
  onCancel?: () => void;
  isRunning: boolean;
  disabled?: boolean;
  hasAnnotations?: boolean;
}> = ({ onSend, onCancel, isRunning, disabled, hasAnnotations = false }) => {
  const { t } = useTranslation();
  const hasText = useAuiState((state) => state.composer.text.trim().length > 0);

  if (isRunning) {
    const cancelButton = (
      <Button
        type="button"
        size="icon"
        variant="ghost"
        aria-label={t("chat.composer.stopGenerating")}
        className="size-8 rounded-base text-foreground hover:bg-accent"
        onClick={onCancel}
      >
        <CircleStop aria-hidden="true" className="size-5" />
      </Button>
    );
    return (
      <TooltipWrapper tooltip={t("chat.composer.stopGenerating")} wrapTrigger>
        {onCancel ? (
          cancelButton
        ) : (
          <ComposerPrimitive.Cancel asChild>
            {cancelButton}
          </ComposerPrimitive.Cancel>
        )}
      </TooltipWrapper>
    );
  }

  return (
    <TooltipWrapper tooltip={t("chat.composer.send")} wrapTrigger>
      <ComposerPrimitive.Send asChild onClick={onSend}>
        <Button
          size="icon"
          className="size-8 ml-0 rounded-md border-0 bg-transparent text-muted-foreground hover:bg-transparent hover:text-foreground disabled:bg-transparent disabled:text-muted-foreground disabled:opacity-50 aria-disabled:bg-transparent aria-disabled:text-muted-foreground [&_svg]:size-4"
          disabled={disabled || (!hasText && !hasAnnotations)}
          aria-label={t("chat.composer.send")}
        >
          <Send />
        </Button>
      </ComposerPrimitive.Send>
    </TooltipWrapper>
  );
};
