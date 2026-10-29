// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ReasoningEffort } from "@/types/modelConfig";
import { isReasoningEffort } from "@/lib/modelReasoning";

import {
  useMemo,
  useState,
  useSyncExternalStore,
  type FC,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { App } from "antd";
import log from "@/lib/logger";
import { SelectedResourceChips } from "@/features/workbench/components/SelectedResourceChips";
import { SkillPicker } from "@/features/workbench/components/SkillPicker";
import type { WorkbenchSkillMount } from "@/features/workbench/types";
import { CreationExamples } from "@/features/workbench/components/CreationExamples";
import {
  Send,
  Square,
  Play,
  Check,
  Circle,
  ListChecks,
  ChevronDown,
  MessageCircleMore,
  Bot,
  Sparkles,
  X,
} from "lucide-react";
import { useComposerKnowledgeBases } from "@/hooks/chat/useComposerResources";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  AuiIf,
  ComposerPrimitive,
  useAui,
  useAuiState,
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

export interface ComposerProps {
  conversationId?: number;
  models: readonly ModelOption[];
  selectedModelId?: string;
  onModelChange?: (modelId: string) => void;
  chatMode: ChatMode;
  onChatModeChange?: (mode: ChatMode) => void;
  showModelSelector?: boolean;
  children?: ReactNode;
  knowledgeScope?: ConversationKnowledgeScope | null;
  knowledgePreview?: KnowledgeScopeEffectivePreview | null;
  knowledgeCapabilities?: KnowledgeCapabilities | null;
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
  workbenchPresentation?: import("@/features/workbench/types").WorkbenchComposerPresentation;
  workbenchResources?: import("@/features/workbench/types").WorkbenchResourceControls;
  onRemoveWorkbenchSkill?: (skillId: number) => void;
  onOpenWorkbenchSkillPicker?: () => void;
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
  knowledgeScope = null,
  knowledgePreview = null,
  knowledgeCapabilities = null,
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
  workbenchPresentation,
  workbenchResources,
  onRemoveWorkbenchSkill,
  onOpenWorkbenchSkillPicker,
}) => {
  const conversationResources =
    !workbenchResources &&
    !workbenchPresentation &&
    Boolean(onKnowledgeScopeChange);
  const { t, i18n } = useTranslation();
  const aui = useAui();
  const runtime = aui.threads().__internal_getAssistantRuntime?.();
  const [sendError, setSendError] = useState("");
  const prepareSend = () => {
    if (!runtime || runtime.thread.getState().isRunning) return;
    const threadId = runtime.threads.getState().mainThreadId;
    const thread = runtime.threads.getById(threadId);
    const config = thread.composer.getState().runConfig;
    setSendError("");
    const feedback = protectOrdinarySend(thread, {
      restoreDraft: true,
      onRejected: (error) => {
        if (runtime.threads.getState().mainThreadId === threadId) {
          setSendError(
            ordinarySendError(error, i18n.language, (value) =>
              getConversationResourceLimitMessage(value, t)
            )
          );
        }
      },
    });
    thread.composer.setRunConfig({
      ...config,
      custom: {
        ...config.custom,
        ...feedback,
        modelPreferenceScope: modelParameterScope,
      },
    });
  };
  const [skillPickerOpen, setSkillPickerOpen] = useState(false);
  const [conversationSkills, setConversationSkills] = useState<
    Array<WorkbenchSkillMount & { name: string }>
  >([]);
  const { message } = App.useApp();
  const creationMode =
    workbenchPresentation?.mode === "skill_create" ||
    workbenchPresentation?.mode === "agent_create"
      ? workbenchPresentation.mode
      : null;
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();
  const knowledgeSource = enableAidpKnowledge ? "aidp" : "local";
  const isWorkbench = Boolean(workbenchPresentation || workbenchResources);
  const canSelectKnowledge = Boolean(
    isDeploymentReady &&
    !creationMode &&
    onKnowledgeScopeChange &&
    (isWorkbench || knowledgeCapabilities?.sources[knowledgeSource].enabled)
  );
  const knowledgeAccessKey = isWorkbench
    ? `workbench:${knowledgeSource}:${canSelectKnowledge}`
    : `${knowledgeCapabilities?.agent_id}:${knowledgeCapabilities?.version_no}:${knowledgeSource}:${canSelectKnowledge}`;
  const [knowledgeModalState, setKnowledgeModalState] = useState({
    key: knowledgeAccessKey,
    open: false,
  });
  if (knowledgeModalState.key !== knowledgeAccessKey) {
    setKnowledgeModalState({ key: knowledgeAccessKey, open: false });
  }
  const knowledgeModalOpen =
    canSelectKnowledge &&
    knowledgeModalState.key === knowledgeAccessKey &&
    knowledgeModalState.open;
  const setKnowledgeModalOpen = (open: boolean) =>
    setKnowledgeModalState((current) =>
      current.key === knowledgeAccessKey
        ? { key: knowledgeAccessKey, open }
        : current
    );
  const { data: knowledgeBases = [] } = useComposerKnowledgeBases(
    conversationResources && canSelectKnowledge,
    enableAidpKnowledge
  );
  const selectedSkillNames = conversationSkills.map((skill) => skill.name);

  const isRunning = useAuiState((state) => state.thread.isRunning);
  const modelParameterScope = useAuiState(
    (state) => state.threads?.mainThreadId
  );
  const hasAttachments = useAuiState(
    (state) => state.composer.attachments.length > 0
  );
  const [knowledgeSaving, setKnowledgeSaving] = useState(false);
  const sourceScope = knowledgeScope?.[knowledgeSource];
  const selectedKbIds =
    sourceScope?.mode === "disabled"
      ? []
      : sourceScope?.mode === "override"
        ? knowledgeSource === "local"
          ? knowledgeScope!.local.knowledge_ids
          : knowledgeScope!.aidp.kds_ids
        : knowledgeCapabilities?.sources[knowledgeSource]
            .default_knowledge_ids || [];
  const selectedKnowledgeBaseChips = selectedKbIds.map((id) => {
    const knowledgeBase = knowledgeBases.find((item) => item.id === id);
    const previewNames =
      knowledgeSource === "local"
        ? knowledgePreview?.local.display_names
        : knowledgePreview?.aidp.display_names;
    const previewIds =
      knowledgeSource === "local"
        ? knowledgePreview?.local.knowledge_ids
        : knowledgePreview?.aidp.kds_ids;
    const previewIndex = previewIds?.indexOf(id) ?? -1;
    return {
      id,
      name:
        knowledgeBase?.name ||
        (previewIndex >= 0 ? previewNames?.[previewIndex] : undefined) ||
        id,
    };
  });
  const toggleKnowledgeBase = async (id: string) => {
    if (
      isRunning ||
      knowledgeSaving ||
      !canSelectKnowledge ||
      !onKnowledgeScopeChange
    )
      return;
    const capabilities = knowledgeCapabilities?.sources[knowledgeSource];
    const ids = selectedKbIds.includes(id)
      ? selectedKbIds.filter((value) => value !== id)
      : [...selectedKbIds, id];
    const maxSelect =
      capabilities?.max_select ?? (enableAidpKnowledge ? 10 : 50);
    if (maxSelect > 0 && ids.length > maxSelect) {
      message.warning(t("chat.knowledgeScope.maxSelect", { count: maxSelect }));
      return;
    }
    if (
      !enableAidpKnowledge &&
      new Set(
        knowledgeBases
          .filter((kb) => ids.includes(kb.id))
          .map((kb) => kb.embeddingModel)
          .filter(Boolean)
      ).size > 1
    ) {
      message.error(t("chat.knowledgeScope.embeddingMismatch"));
      return;
    }
    const scope: ConversationKnowledgeScope = {
      schema_version: 1,
      ...(knowledgeScope?.retrieval_config
        ? { retrieval_config: knowledgeScope.retrieval_config }
        : {}),
      local: {
        mode: !enableAidpKnowledge && ids.length ? "override" : "disabled",
        knowledge_ids: enableAidpKnowledge ? [] : ids,
      },
      aidp: {
        mode: enableAidpKnowledge && ids.length ? "override" : "disabled",
        kds_ids: enableAidpKnowledge ? ids : [],
      },
    };
    setKnowledgeSaving(true);
    try {
      await onKnowledgeScopeChange(scope);
    } catch (error) {
      log.error("Failed to update composer knowledge scope", error);
    } finally {
      setKnowledgeSaving(false);
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
        disabled={fieldsetDisabled}
        aria-disabled={fieldsetDisabled}
        className={cn(
          "relative m-0 flex min-w-0 w-full flex-col overflow-visible gap-2 rounded-[20px] border-[0.5px] border-solid border-[#191919]/[0.08] bg-white px-4 pb-4 pt-5 shadow-[0_1px_6px_0_rgba(0,0,0,0.16)]",
          fieldsetDisabled && "cursor-not-allowed opacity-60",
          configurationLayout &&
            "min-h-[164px] rounded-[20px] border-[0.5px] border-[#191919]/[0.08] bg-white shadow-[0_1px_6px_rgba(0,0,0,0.16)]"
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
            className="flex w-full flex-col gap-2.5 outline-none"
            onSubmit={(event) => {
              if (isRunning) event.preventDefault();
              else prepareSend();
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
            {hasAttachments && <ComposerAttachments className="px-0" />}
            {conversationResources &&
              (selectedSkillNames.length > 0 ||
                (canSelectKnowledge &&
                  selectedKnowledgeBaseChips.length > 0)) && (
                <div className="flex min-w-0 flex-wrap gap-2 px-2">
                  {selectedSkillNames.map((name) => (
                    <span
                      key={`skill-${name}`}
                      className="inline-flex h-7 max-w-60 items-center gap-1 rounded-md border border-[#e5e5e5] bg-[#f7f7f7] px-2 text-xs text-[#191919]"
                    >
                      <SkillStackIcon
                        className="size-3.5 shrink-0 text-[#666]"
                        aria-hidden
                      />
                      <span className="truncate" title={name}>
                        {name}
                      </span>
                      <button
                        type="button"
                        aria-label={`${t("common.delete")} ${name}`}
                        disabled={isRunning || disabled}
                        className="ml-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded text-[#808080] hover:bg-[#e9e9e9] hover:text-[#191919] disabled:cursor-not-allowed"
                        onClick={() =>
                          setConversationSkills((current) =>
                            current.filter((skill) => skill.name !== name)
                          )
                        }
                      >
                        <X className="size-3" aria-hidden />
                      </button>
                    </span>
                  ))}
                  {(canSelectKnowledge ? selectedKnowledgeBaseChips : []).map(
                    ({ id, name }) => (
                      <span
                        key={id}
                        className="inline-flex h-7 max-w-60 items-center gap-1 rounded-md border border-[#e5e5e5] bg-[#f7f7f7] px-2 text-xs text-[#191919]"
                      >
                        <KnowledgeBookIcon
                          className="size-3.5 shrink-0 text-[#666]"
                          aria-hidden
                        />
                        <span className="truncate" title={name}>
                          {name}
                        </span>
                        <button
                          type="button"
                          disabled={isRunning || knowledgeSaving}
                          aria-label={`${t("common.delete")} ${name}`}
                          className="ml-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded text-[#808080] hover:bg-[#e9e9e9] hover:text-[#191919] disabled:cursor-not-allowed"
                          onClick={() => void toggleKnowledgeBase(id)}
                        >
                          <X className="size-3" aria-hidden />
                        </button>
                      </span>
                    )
                  )}
                </div>
              )}
            {skillFiles ? (
              <LexicalComposerInput
                aria-label={t("chat.composer.inputLabel")}
                placeholder=""
                className="relative mb-0 max-h-48 min-h-20 w-full bg-transparent px-0 py-0 text-sm text-[#191919] outline-none [&_.aui-lexical-input]:min-h-20 [&_.aui-lexical-input]:outline-none [&_.aui-lexical-placeholder]:pointer-events-none [&_.aui-lexical-placeholder]:absolute [&_.aui-lexical-placeholder]:top-0 [&_.aui-lexical-placeholder]:text-muted-foreground"
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
                    "max-h-48 min-h-20 min-w-0 w-auto flex-1 resize-none bg-transparent px-0 py-0 text-sm text-[#191919] outline-none placeholder:text-muted-foreground",
                    configurationLayout && "!min-h-[56px] !px-4"
                  )}
                  rows={1}
                  submitMode="enter"
                  autoFocus
                />
              </div>
            )}
            {workbenchResources && (
              <SelectedResourceChips
                resources={workbenchResources}
                scope={knowledgeScope}
                knowledgeNames={{
                  local: Object.fromEntries(
                    (knowledgePreview?.local.knowledge_ids || []).map(
                      (id, index) => [
                        id,
                        knowledgePreview?.local.display_names[index] ||
                          `#${id}`,
                      ]
                    )
                  ),
                  aidp: Object.fromEntries(
                    (knowledgePreview?.aidp.kds_ids || []).map((id, index) => [
                      id,
                      knowledgePreview?.aidp.display_names[index] || `#${id}`,
                    ])
                  ),
                }}
                disabled={isRunning}
                onEditSkill={onOpenWorkbenchSkillPicker}
                onRemoveSkill={onRemoveWorkbenchSkill}
                onEditKnowledge={() => setKnowledgeModalOpen(true)}
                onKnowledgeChange={(scope) => {
                  // The controller presents save/conflict errors; keep rejected saves out of the event loop.
                  void Promise.resolve(onKnowledgeScopeChange?.(scope)).catch(
                    () => undefined
                  );
                }}
              />
            )}
            <div className="relative flex min-h-8 flex-wrap items-center justify-between gap-2">
              <div className="flex min-w-0 flex-wrap items-center gap-1">
                {!creationMode && onChatModeChange && (
                  <WorkbenchPlanningMenu
                    chatMode={chatMode}
                    onChatModeChange={onChatModeChange}
                    disabled={isRunning || disabled}
                  />
                )}
                {!creationMode && workbenchResources?.onSelectAgent && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={isRunning || disabled}
                    className="h-8 text-sm font-normal text-muted-foreground"
                    onClick={workbenchResources.onSelectAgent}
                    aria-label={t("workbench.controls.agents", "智能体")}
                  >
                    <Bot className="size-5" />
                    {t("workbench.controls.agents", "智能体")}
                  </Button>
                )}
                {!creationMode && canSelectKnowledge && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={isRunning || disabled}
                    className="h-8 text-sm font-normal text-muted-foreground"
                    onClick={() => setKnowledgeModalOpen(true)}
                    aria-label={t("chat.composer.knowledgeBase")}
                    title={knowledgeSummary}
                  >
                    <KnowledgeBookIcon className="size-5" />
                    {t("chat.composer.knowledgeBase")}
                  </Button>
                )}
                {!creationMode && onOpenWorkbenchSkillPicker && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={isRunning || disabled}
                    className="h-8 text-sm font-normal text-muted-foreground"
                    onClick={onOpenWorkbenchSkillPicker}
                    aria-label={t("chat.composer.skills")}
                  >
                    <SkillStackIcon className="size-5" />
                    {t("chat.composer.skills")}
                  </Button>
                )}
                {allowRuntimeMetadata && onRuntimeMetadataChange && (
                  <RuntimeMetadataEditor
                    value={runtimeMetadata}
                    onChange={onRuntimeMetadataChange}
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
                    className="min-w-0 max-w-[280px] text-sm font-normal leading-5 text-muted-foreground [&_[data-slot=model-selector-value]]:text-sm [&_[data-slot=model-selector-value]]:leading-5 [&_[data-slot=model-selector-value]]:text-muted-foreground [&_[data-slot=model-selector-value]_span]:font-normal"
                  />
                )}
                {children}
                <ComposerSendOrCancel
                  onSend={prepareSend}
                  disabled={disabled || knowledgeSaving}
                />
              </div>
            </div>
          </ComposerPrimitive.Root>
          {canSelectKnowledge && (
            <ConversationKnowledgeScopeModal
              presentation="drawer"
              disabled={isRunning || disabled}
              open={knowledgeModalOpen}
              value={knowledgeScope}
              capabilities={knowledgeCapabilities}
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
      {conversationResources && skillPickerOpen && (
        <SkillPicker
          open
          disabled={isRunning || disabled}
          selected={conversationSkills}
          onCancel={() => setSkillPickerOpen(false)}
          onConfirm={(mounts, skills) => {
            if (isRunning || disabled) return;
            setConversationSkills(
              mounts.map((mount) => ({
                ...mount,
                name:
                  skills.find(
                    (skill) => Number(skill.skill_id) === mount.skill_id
                  )?.name || String(mount.skill_id),
              }))
            );
            setSkillPickerOpen(false);
          }}
        />
      )}
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
          className="-ml-2 h-8 shrink-0 gap-1.5 px-2 text-sm font-normal leading-5 text-muted-foreground"
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
// Trigger can use `asChild` against the Button. `AuiIf` toggles between the
// two branches declaratively based on `thread.isRunning`.
const ComposerSendOrCancel: FC<{
  onSend: () => void;
  disabled?: boolean;
}> = ({ onSend, disabled }) => {
  const { t } = useTranslation();
  const hasText = useAuiState((state) => state.composer.text.trim().length > 0);

  return (
    <>
      <AuiIf condition={(s) => s.thread.isRunning}>
        <TooltipWrapper
          tooltip={t("chat.composer.stopGenerating")}
          side="bottom"
          wrapTrigger
        >
          <ComposerPrimitive.Cancel
            asChild
            aria-label={t("chat.composer.stopGenerating")}
          >
            <Button
              size="icon"
              variant="outline"
              aria-label={t("chat.composer.stopGenerating")}
              className="size-8 rounded-full ml-2 border-border bg-background text-primary hover:bg-muted"
            >
              <Square className="size-4 fill-current" />
            </Button>
          </ComposerPrimitive.Cancel>
        </TooltipWrapper>
      </AuiIf>
      <AuiIf condition={(s) => !s.thread.isRunning}>
        <TooltipWrapper
          tooltip={t("chat.composer.send")}
          side="bottom"
          wrapTrigger
        >
          <ComposerPrimitive.Send asChild onClick={onSend}>
            <Button
              size="icon"
              className="size-8 ml-0 rounded-md border-0 bg-transparent text-muted-foreground hover:bg-transparent hover:text-foreground disabled:bg-transparent disabled:text-muted-foreground disabled:opacity-50 aria-disabled:bg-transparent aria-disabled:text-muted-foreground [&_svg]:size-4"
              disabled={disabled || !hasText}
              aria-label={t("chat.composer.send")}
            >
              <Send />
            </Button>
          </ComposerPrimitive.Send>
        </TooltipWrapper>
      </AuiIf>
    </>
  );
};
