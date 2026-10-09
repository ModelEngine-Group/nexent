"use client";

import {
  useMemo,
  useState,
  useEffect,
  useSyncExternalStore,
  type FC,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { SelectedResourceChips } from "@/features/workbench/components/SelectedResourceChips";
import { CreationExamples } from "@/features/workbench/components/CreationExamples";
import {
  ArrowUp,
  Mic,
  MicOff,
  Square,
  Lightbulb,
  Play,
  Check,
  Circle,
  ListChecks,
  ChevronDown,
  Compass,
  Database,
  Bot,
  Plus,
  Send,
} from "lucide-react";
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
import { ModelSelector, type ModelOption } from "../ui/model-selector";
import { ComposerAttachments, ComposerAddAttachment } from "../ui/attachment";
import {
  useWorkbenchComposerTag,
  setWorkbenchComposerTag,
} from "@/features/workbench/lib/workbench-composer-tag";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
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

export type ChatMode = "planning" | "execution";

export interface ComposerProps {
  models: readonly ModelOption[];
  selectedModelId?: string;
  onModelChange?: (modelId: string) => void;
  deepThinking?: boolean;
  onDeepThinkingChange?: (enabled: boolean) => void;
  thinkingEffort?: "low" | "medium" | "high";
  onThinkingEffortChange?: (effort: "low" | "medium" | "high") => void;
  chatMode: ChatMode;
  onChatModeChange: (mode: ChatMode) => void;
  showModelSelector?: boolean;
  isDictationConfigured?: boolean;
  knowledgeScope?: ConversationKnowledgeScope | null;
  knowledgePreview?: KnowledgeScopeEffectivePreview | null;
  knowledgeCapabilities?: KnowledgeCapabilities | null;
  onKnowledgeScopeChange?: (
    scope: ConversationKnowledgeScope | null,
    preview?: KnowledgeScopeEffectivePreview | null
  ) => Promise<void> | void;
  compact?: boolean;
  skillFiles?: readonly SkillFileContent[];
  runtimeMetadata?: Record<string, unknown>;
  onRuntimeMetadataChange?: (value: Record<string, unknown>) => void;
  allowRuntimeMetadata?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  workbenchPresentation?: import("@/features/workbench/types").WorkbenchComposerPresentation;
  workbenchResources?: import("@/features/workbench/types").WorkbenchResourceControls;
  onRemoveWorkbenchSkill?: (skillId: number) => void;
  onOpenWorkbenchSkillPicker?: () => void;
  workbenchSkillPopover?: ReactNode;
  workbenchKnowledgePopover?: ReactNode;
}

// Simple tooltip wrapper
const TooltipWrapper: FC<{
  tooltip: string;
  side?: "top" | "bottom" | "left" | "right";
  children: ReactNode;
}> = ({ tooltip, side = "bottom", children }) => {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side}>{tooltip}</TooltipContent>
    </Tooltip>
  );
};

const PlanView: FC = () => {
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
        className="border-b border-border"
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

// Blue category tag rendered inline before the composer text after clicking
// a landing example; auto-clears when the composer text is emptied.
const WorkbenchComposerTagPrefix: FC = () => {
  const tag = useWorkbenchComposerTag();
  const text = useAuiState((s) => s.composer.text);

  useEffect(() => {
    if (!text?.trim()) setWorkbenchComposerTag(null);
  }, [text]);

  if (!tag || !text?.trim()) return null;
  return (
    <span className="shrink-0 py-2 pl-4 text-xs font-normal leading-5 text-[#197BD5]">
      {tag}
    </span>
  );
};

// Workbench toolbar dropdown that replaces the standalone planning/execution
// switcher row, matching the design's "规划模式" entry in the composer toolbar.
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
          className="h-8 shrink-0 gap-1.5 px-2 text-base leading-6 text-foreground"
        >
          <Compass className="size-4" />
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
            className={cn(
              "flex h-10 w-full items-center justify-between gap-2 rounded-lg px-2 py-2 text-base font-normal leading-6 hover:bg-accent",
              chatMode === option.value ? "text-foreground" : "text-foreground"
            )}
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

export const Composer: FC<ComposerProps> = ({
  models,
  selectedModelId,
  onModelChange,
  deepThinking,
  onDeepThinkingChange,
  thinkingEffort,
  onThinkingEffortChange,
  chatMode,
  onChatModeChange,
  showModelSelector = true,
  isDictationConfigured = false,
  knowledgeScope = null,
  knowledgePreview = null,
  knowledgeCapabilities = null,
  onKnowledgeScopeChange,
  compact = false,
  skillFiles,
  runtimeMetadata = {},
  onRuntimeMetadataChange,
  allowRuntimeMetadata = false,
  disabled = false,
  disabledReason,
  workbenchPresentation,
  workbenchResources,
  onRemoveWorkbenchSkill,
  onOpenWorkbenchSkillPicker,
  workbenchSkillPopover,
  workbenchKnowledgePopover,
}) => {
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
      custom: { ...config.custom, ...feedback },
    });
  };
  const [knowledgeModalOpen, setKnowledgeModalOpen] = useState(false);
  const isRunning = useAuiState((state) => state.thread.isRunning);
  const creationMode =
    workbenchPresentation?.mode === "skill_create" ||
    workbenchPresentation?.mode === "agent_create"
      ? workbenchPresentation.mode
      : null;

  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();
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

  return (
    <div className="relative w-full min-w-0">
      {/* Creation mode entry buttons ("Skill 创建 / Agent创建") are hidden per
          the workbench design; creation flows remain reachable elsewhere. */}
      {workbenchPresentation && !compact && creationMode && (
        <div className="mb-2 h-7" aria-hidden="true" />
      )}
      <fieldset
        disabled={disabled && !disabledReason}
        aria-disabled={disabled && !disabledReason}
        className={cn(
          "relative m-0 flex min-w-0 w-full flex-col overflow-visible rounded-2xl border border-border bg-card p-0 shadow-sm",
          workbenchPresentation &&
            "rounded-3xl shadow-[0_12px_36px_-14px_rgba(0,0,0,0.18)]",
          disabled && !disabledReason && "cursor-not-allowed opacity-60"
        )}
      >
        {disabled && disabledReason ? (
          <p className="px-3 pb-1 text-xs text-amber-700" role="status">
            {disabledReason}
          </p>
        ) : null}
        {!compact && !creationMode && <PlanView />}
        {creationMode && (
          <div className="flex items-center border-b border-border px-3 py-2">
            <button
              type="button"
              onClick={workbenchPresentation?.onExitCreation}
              disabled={isRunning}
              className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-xs text-primary"
              aria-label="退出创建模式"
            >
              {creationMode === "skill_create" ? "Skill 创建" : "Agent创建"}
              <span aria-hidden>×</span>
            </button>
          </div>
        )}

        {/* Mode switcher above input */}
        {!compact && !creationMode && !workbenchPresentation && (
          <div className="flex items-center border-b border-border px-3 py-2">
            {/* Mode switcher */}
            <div className="flex items-center rounded-lg border border-border bg-muted/50 p-0.5">
              <Button
                variant="ghost"
                size="sm"
                className={cn(
                  "h-6 gap-1 rounded-md px-2 text-xs transition-colors",
                  chatMode === "planning" &&
                    "bg-blue-50 text-blue-600 hover:bg-blue-50"
                )}
                onClick={() => onChatModeChange("planning")}
              >
                <Lightbulb
                  className={cn(
                    "size-3",
                    chatMode === "planning" ? "text-blue-600" : ""
                  )}
                />
                {t("chat.composer.planning")}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className={cn(
                  "h-6 gap-1 rounded-md px-2 text-xs transition-colors",
                  chatMode === "execution" &&
                    "bg-blue-50 text-blue-600 hover:bg-blue-50"
                )}
                onClick={() => onChatModeChange("execution")}
              >
                <Play className="size-3" />
                {t("chat.composer.execution")}
              </Button>
            </div>
          </div>
        )}

        {/* Composer Primitive Root */}
        <ComposerPrimitive.Unstable_TriggerPopoverRoot>
          {skillFiles ? <SkillFileMentionPopover files={skillFiles} /> : null}
          <ComposerPrimitive.Root
            className="flex w-full flex-col px-1 py-1 outline-none"
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
            {!compact && <ComposerAttachments />}
            {skillFiles ? (
              <LexicalComposerInput
                placeholder={
                  workbenchPresentation
                    ? t("chat.composer.workbenchPlaceholder")
                    : t("chat.composer.placeholder")
                }
                className="relative mb-1 max-h-32 min-h-14 w-full bg-transparent px-3 py-1 text-sm outline-none [&_.aui-lexical-input]:min-h-12 [&_.aui-lexical-input]:outline-none [&_.aui-lexical-placeholder]:pointer-events-none [&_.aui-lexical-placeholder]:absolute [&_.aui-lexical-placeholder]:top-1 [&_.aui-lexical-placeholder]:text-muted-foreground"
                submitMode="enter"
                autoFocus
                formatter={combinedSkillDirectiveFormatter}
                directiveChip={SkillComposerDirectiveChip}
              />
            ) : (
              <div className="flex items-start">
                {workbenchPresentation && <WorkbenchComposerTagPrefix />}
                <ComposerPrimitive.Input
                  data-workbench-composer
                  placeholder={
                    workbenchPresentation
                      ? t("chat.composer.workbenchPlaceholder")
                      : t("chat.composer.placeholder")
                  }
                  className={cn(
                    "mb-1 max-h-48 min-h-14 w-full resize-none bg-transparent px-3 py-1 text-sm outline-none placeholder:text-muted-foreground",
                    workbenchPresentation && "min-h-[88px] px-4 py-2",
                    workbenchPresentation && "w-auto min-w-0 flex-1"
                  )}
                  rows={1}
                  submitMode="enter"
                  autoFocus
                />
              </div>
            )}
            {!compact && workbenchResources && (
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
            <div
              className={cn(
                "relative mx-2 mb-2 flex items-center justify-between gap-2",
                workbenchPresentation && "mx-4 flex-wrap pt-2 sm:flex-nowrap"
              )}
            >
              <div
                className={cn(
                  "flex min-w-0 items-center gap-1",
                  workbenchPresentation && "flex-wrap sm:flex-nowrap"
                )}
              >
                {!compact && !workbenchPresentation && showModelSelector && (
                  <ModelSelector
                    models={models}
                    value={selectedModelId}
                    onValueChange={onModelChange}
                    deepThinking={deepThinking}
                    onDeepThinkingChange={onDeepThinkingChange}
                    effort={thinkingEffort}
                    onEffortChange={(value) => {
                      if (
                        value === "low" ||
                        value === "medium" ||
                        value === "high"
                      )
                        onThinkingEffortChange?.(value);
                    }}
                    variant="ghost"
                    size="sm"
                    className="shrink-0 text-xs text-foreground [&_[data-slot=model-selector-value]]:text-foreground"
                  />
                )}
                {!compact && workbenchResources && workbenchPresentation && (
                  <TooltipWrapper tooltip={t("chat.composer.addAgent")}>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="size-8 shrink-0 p-0"
                      disabled={isRunning}
                      onClick={workbenchResources.onSelectAgent}
                    >
                      <Plus className="size-4" />
                    </Button>
                  </TooltipWrapper>
                )}
                {!compact && !creationMode && workbenchPresentation && (
                  <WorkbenchPlanningMenu
                    chatMode={chatMode}
                    onChatModeChange={onChatModeChange}
                    disabled={isRunning}
                  />
                )}
                {!compact && workbenchResources && !workbenchPresentation && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 shrink-0 gap-1.5 px-2 text-xs"
                    disabled={isRunning}
                    onClick={workbenchResources.onSelectAgent}
                  >
                    <Bot className="size-3.5" />
                    Agent
                  </Button>
                )}
                {!compact && workbenchResources && (
                  <Popover>
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className={cn(
                          "h-8 shrink-0 gap-1.5 px-2 text-xs",
                          workbenchPresentation &&
                            "text-base leading-6 text-foreground"
                        )}
                        disabled={isRunning}
                        onClick={
                          workbenchSkillPopover
                            ? undefined
                            : onOpenWorkbenchSkillPicker
                        }
                      >
                        <Lightbulb
                          className={cn(
                            "size-3.5",
                            workbenchPresentation && "size-4"
                          )}
                        />
                        {workbenchPresentation
                          ? t("chat.composer.skills")
                          : "Skills"}
                        {workbenchPresentation && (
                          <ChevronDown className="size-4 opacity-50" />
                        )}
                      </Button>
                    </PopoverTrigger>
                    {workbenchSkillPopover ? (
                      <PopoverContent align="start" className="w-80 p-0">
                        {workbenchSkillPopover}
                      </PopoverContent>
                    ) : null}
                  </Popover>
                )}
                {!compact &&
                  !creationMode &&
                  (workbenchPresentation ||
                    knowledgeCapabilities?.sources.local.enabled ||
                    knowledgeCapabilities?.sources.aidp.enabled ||
                    knowledgeScope) && (
                    <Popover>
                      <PopoverTrigger asChild>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className={cn(
                            "h-8 min-w-0 max-w-64 gap-1.5 px-2 text-xs text-foreground",
                            workbenchPresentation &&
                              "text-base leading-6 text-foreground"
                          )}
                          onClick={
                            workbenchKnowledgePopover
                              ? undefined
                              : () => setKnowledgeModalOpen(true)
                          }
                          disabled={isRunning}
                          title={
                            isRunning
                              ? t("chat.knowledgeScope.runningDisabled")
                              : knowledgeSummary
                          }
                        >
                          <Database
                            className={cn(
                              "size-3.5 shrink-0",
                              workbenchPresentation && "size-4"
                            )}
                          />
                          <span className="truncate">
                            {workbenchPresentation
                              ? t("chat.composer.knowledgeBase")
                              : knowledgeSummary}
                          </span>
                          {workbenchPresentation && (
                            <ChevronDown className="size-4 shrink-0 opacity-50" />
                          )}
                        </Button>
                      </PopoverTrigger>
                      {workbenchKnowledgePopover ? (
                        <PopoverContent align="start" className="w-80 p-0">
                          {workbenchKnowledgePopover}
                        </PopoverContent>
                      ) : null}
                    </Popover>
                  )}
                {!compact &&
                  allowRuntimeMetadata &&
                  onRuntimeMetadataChange && (
                    <RuntimeMetadataEditor
                      value={runtimeMetadata}
                      onChange={onRuntimeMetadataChange}
                      disabled={isRunning}
                    />
                  )}
                {!compact && workbenchPresentation && (
                  <ComposerAddAttachment
                    label={t("chat.composer.uploadFile")}
                  />
                )}
              </div>
              <div className="ml-auto flex shrink-0 items-center gap-1">
                {!compact && workbenchPresentation && showModelSelector && (
                  <ModelSelector
                    models={models}
                    value={selectedModelId}
                    onValueChange={onModelChange}
                    deepThinking={deepThinking}
                    onDeepThinkingChange={onDeepThinkingChange}
                    effort={thinkingEffort}
                    showEffort={Boolean(workbenchPresentation)}
                    onEffortChange={(value) => {
                      if (
                        value === "low" ||
                        value === "medium" ||
                        value === "high"
                      )
                        onThinkingEffortChange?.(value);
                    }}
                    variant="ghost"
                    size="sm"
                    className="shrink-0 text-base leading-6 text-foreground [&_[data-slot=model-selector-value]]:text-base [&_[data-slot=model-selector-value]]:leading-6"
                  />
                )}
                {!compact && !workbenchPresentation && (
                  <ComposerAddAttachment />
                )}
                {!compact && (
                  <AuiIf condition={(s) => !s.composer.dictation}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="inline-flex">
                          <ComposerPrimitive.Dictate asChild>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              disabled={!isDictationConfigured}
                              className={cn(
                                "size-8 text-muted-foreground",
                                workbenchPresentation && "size-9"
                              )}
                            >
                              <Mic
                                className={cn(
                                  "size-4",
                                  workbenchPresentation && "size-6"
                                )}
                              />
                            </Button>
                          </ComposerPrimitive.Dictate>
                        </span>
                      </TooltipTrigger>
                      <TooltipContent>
                        {isDictationConfigured
                          ? t("chat.composer.voiceInput")
                          : t("chat.composer.voiceInputDisabled")}
                      </TooltipContent>
                    </Tooltip>
                  </AuiIf>
                )}
                {!compact && (
                  <AuiIf condition={(s) => !!s.composer.dictation}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <ComposerPrimitive.StopDictation asChild>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className={cn(
                              "size-8 text-destructive hover:text-destructive",
                              workbenchPresentation && "size-9"
                            )}
                          >
                            <MicOff
                              className={cn(
                                "size-4",
                                workbenchPresentation && "size-6"
                              )}
                            />
                          </Button>
                        </ComposerPrimitive.StopDictation>
                      </TooltipTrigger>
                      <TooltipContent>
                        {t("chat.composer.stopVoiceInput")}
                      </TooltipContent>
                    </Tooltip>
                  </AuiIf>
                )}
                <ComposerSendOrCancel
                  onSend={prepareSend}
                  disabled={disabled}
                  workbench={Boolean(workbenchPresentation)}
                />
              </div>
            </div>
          </ComposerPrimitive.Root>
          {!compact && (
            <ConversationKnowledgeScopeModal
              open={knowledgeModalOpen}
              value={knowledgeScope}
              capabilities={knowledgeCapabilities}
              onCancel={() => setKnowledgeModalOpen(false)}
              onConfirm={async (scope, preview) => {
                await onKnowledgeScopeChange?.(scope, preview);
                setKnowledgeModalOpen(false);
              }}
            />
          )}
        </ComposerPrimitive.Unstable_TriggerPopoverRoot>
      </fieldset>
      {creationMode && !compact && workbenchPresentation && (
        <div className="absolute inset-x-0 top-full z-10">
          <CreationExamples
            mode={creationMode}
            onBack={workbenchPresentation.onExitCreation}
          />
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

// `ComposerPrimitive.Cancel` / `Send` forward their internal `onClick` to the
// direct child via Radix Slot, so the Button MUST be the immediate child for
// the click handler to actually fire. The tooltip wrapper sits outside so its
// Trigger can use `asChild` against the Button. `AuiIf` toggles between the
// two branches declaratively based on `thread.isRunning`.
const ComposerSendOrCancel: FC<{
  onSend: () => void;
  disabled?: boolean;
  workbench?: boolean;
}> = ({ onSend, disabled, workbench = false }) => {
  const { t } = useTranslation();
  const hasText = useAuiState((state) => state.composer.text.trim().length > 0);

  return (
    <>
      <AuiIf condition={(s) => s.thread.isRunning}>
        <TooltipWrapper tooltip={t("chat.composer.stopGenerating")} side="top">
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
        <TooltipWrapper tooltip={t("chat.composer.send")} side="top">
          <ComposerPrimitive.Send asChild onClick={onSend}>
            <Button
              size="icon"
              className={cn(
                "size-8 rounded-full ml-2",
                workbench &&
                  "size-[30px] bg-[#191919] text-white hover:bg-[#191919]/90 disabled:opacity-70"
              )}
              disabled={disabled || !hasText}
              aria-label={t("chat.composer.send")}
            >
              {workbench ? (
                <Send className="size-5" />
              ) : (
                <ArrowUp className="size-5" />
              )}
            </Button>
          </ComposerPrimitive.Send>
        </TooltipWrapper>
      </AuiIf>
    </>
  );
};
