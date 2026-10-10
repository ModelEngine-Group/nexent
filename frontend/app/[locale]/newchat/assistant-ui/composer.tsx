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
  Send,
  ArrowUp,
  Mic,
  MicOff,
  Square,
  Play,
  Check,
  Circle,
  ListChecks,
  ChevronDown,
  MessageCircleMore,
  Paperclip,
  ChevronRight,
  Database,
  Bot,
  Layers,
  Link2,
  MessagesSquare,
  SearchIcon,
  Settings,
  PlusIcon,
  Sparkles,
} from "lucide-react";
import { StandardInput } from "@/components/common/StandardInput";
import {
  useComposerKnowledgeBases,
  useComposerSkills,
} from "@/hooks/chat/useComposerResources";
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
import { ComposerAttachments, ComposerAddAttachment } from "../ui/attachment";
import {
  useWorkbenchComposerTag,
  setWorkbenchComposerTag,
} from "@/features/workbench/lib/workbench-composer-tag";
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
    <path d="M3.5 6.1C6 4.8 8.9 4.9 11.4 6.4v11.8C8.9 16.7 6 16.6 3.5 17.9Z" />
    <path d="M11.4 6.4c2.5-1.5 5.3-1.6 7.8-.4v7.3" />
    <path
      d="M18.7 14.1q.7 2 2.75 2.75-2.05.75-2.75 2.8-.7-2.05-2.75-2.8 2.05-.75 2.75-2.75Z"
      fill="currentColor"
      stroke="none"
    />
  </svg>
);

export type ChatMode = "planning" | "execution";

export interface ComposerProps {
  newChatDesign?: boolean;
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
  configurationLayout?: boolean;
  debugLayout?: boolean;
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

const WorkbenchComposerTagPrefix: FC = () => {
  const tag = useWorkbenchComposerTag();
  const text = useAuiState((state) => state.composer.text);

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

// Dot colors for the skill quick panel rows (stable per skill name).
const SKILL_DOT_COLORS = [
  "#14b8a6",
  "#ec4899",
  "#ef4444",
  "#f59e0b",
  "#22c55e",
  "#3b82f6",
  "#a855f7",
];

function hashString(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

// Item row of the workbench "＋" overflow menu, styled after the
// planning-mode menu.
const ComposerPlusItem: FC<{
  icon: ReactNode;
  label: string;
  active?: boolean;
  onSelect: () => void;
}> = ({ icon, label, active, onSelect }) => (
  <button
    type="button"
    className="flex h-10 w-full items-center gap-2 rounded-lg px-2 py-2 text-base font-normal leading-6 text-foreground hover:bg-accent"
    onClick={onSelect}
  >
    {icon}
    {label}
    {active ? <Check className="ml-auto size-4" /> : null}
  </button>
);

export const Composer: FC<ComposerProps> = ({
  newChatDesign = false,
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
  configurationLayout = false,
  debugLayout = false,
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
  const { data: knowledgeBases = [], isLoading: kbLoading } =
    useComposerKnowledgeBases(newChatDesign);
  const { data: skills = [], isLoading: skillsLoading } =
    useComposerSkills(newChatDesign);
  // Category tabs derive from the configured skills' tags (design: 全部 + tags).
  const skillTagTabs = useMemo(() => {
    const tags: string[] = [];
    for (const skill of skills) {
      for (const tag of skill.tags) {
        if (tag && !tags.includes(tag)) tags.push(tag);
      }
    }
    return tags.slice(0, 5);
  }, [skills]);
  const [skillTab, setSkillTab] = useState("");
  const [kbSearch, setKbSearch] = useState("");
  const [skillSearch, setSkillSearch] = useState("");

  const filteredSkills = useMemo(() => {
    const query = skillSearch.trim().toLowerCase();
    return skills
      .filter((skill) => skillTab === "" || skill.tags.includes(skillTab))
      .filter(
        (skill) =>
          !query ||
          (skill.name + (skill.description || "")).toLowerCase().includes(query)
      );
  }, [skills, skillTab, skillSearch]);

  const [actionPanel, setActionPanel] = useState<
    "plus" | "kb" | "skill" | null
  >(null);
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  // TODO(mock): knowledge-base / skill selection is visual only until the
  // conversation scope APIs are wired into the quick panels.
  const [selectedSkillNames, setSelectedSkillNames] = useState<string[]>([]);
  // Overflow menu ("＋") with second-level submenus for the workbench
  // toolbar, so right-side functions stay reachable on narrow windows.
  const [plusOpen, setPlusOpen] = useState(false);
  const [plusSkillOpen, setPlusSkillOpen] = useState(false);
  const [plusKnowledgeOpen, setPlusKnowledgeOpen] = useState(false);
  const isRunning = useAuiState((state) => state.thread.isRunning);
  const hasAttachments = useAuiState(
    (state) => state.composer.attachments.length > 0
  );
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
    <div
      className={cn(
        "relative w-full min-w-0",
        newChatDesign && "mx-auto max-w-[890px]"
      )}
    >
      {/* Creation mode entry buttons ("Skill 创建 / Agent创建") are hidden per
          the workbench design; creation flows remain reachable elsewhere. */}
      {workbenchPresentation && !compact && creationMode && (
        <div className="mb-2 h-7" aria-hidden="true" />
      )}
      <fieldset
        disabled={disabled && !disabledReason}
        aria-disabled={disabled && !disabledReason}
        className={cn(
          newChatDesign
            ? "relative m-0 flex min-w-0 w-full flex-col gap-2 overflow-visible rounded-[20px] border-[0.5px] border-solid border-[#191919] bg-card p-4 shadow-[0_2px_12px_rgba(0,0,0,0.08)]"
            : "relative m-0 flex min-w-0 w-full flex-col overflow-visible rounded-2xl border border-border bg-card p-0 shadow-sm",
          !newChatDesign &&
            workbenchPresentation &&
            "rounded-3xl shadow-[0_12px_36px_-14px_rgba(0,0,0,0.18)]",
          disabled && !disabledReason && "cursor-not-allowed opacity-60",
          configurationLayout &&
            "min-h-[164px] rounded-[20px] border-[0.5px] border-[#191919]/[0.08] bg-white shadow-[0_1px_6px_rgba(0,0,0,0.16)]",
          debugLayout &&
            "min-h-[164px] rounded-[20px] border-0 p-4 outline-[0.5px] outline-[#191919]/[0.08] bg-white shadow-[0_1px_6px_rgba(0,0,0,0.16)]"
        )}
      >
        {disabled && disabledReason ? (
          <p className="px-3 pb-1 text-xs text-amber-700" role="status">
            {disabledReason}
          </p>
        ) : null}
        {!compact && !creationMode && !configurationLayout && !debugLayout && (
          <PlanView />
        )}
        {configurationLayout && (
          <div className="flex px-4 pt-4">
            <span className="inline-flex items-center gap-1 rounded-full bg-[#669fff]/[0.15] px-2 text-xs leading-[22px] text-[#477bd5]">
              <Sparkles size={14} />
              {t("nl2agent.configuration.badge")}
            </span>
          </div>
        )}
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

        {/* Composer Primitive Root */}
        <ComposerPrimitive.Unstable_TriggerPopoverRoot>
          {skillFiles ? <SkillFileMentionPopover files={skillFiles} /> : null}
          <ComposerPrimitive.Root
            className="flex w-full flex-col outline-none"
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
            {!compact && (!debugLayout || hasAttachments) && (
              <ComposerAttachments />
            )}
            {skillFiles ? (
              <LexicalComposerInput
                placeholder={
                  configurationLayout
                    ? ""
                    : newChatDesign
                      ? t("chat.composer.placeholder")
                      : workbenchPresentation
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
              <div
                className={cn(
                  workbenchPresentation && !newChatDesign && "flex items-start"
                )}
              >
                {workbenchPresentation && !newChatDesign && (
                  <WorkbenchComposerTagPrefix />
                )}
                <ComposerPrimitive.Input
                  data-workbench-composer
                  aria-label={t("chat.composer.placeholder")}
                  placeholder={
                    configurationLayout
                      ? ""
                      : newChatDesign
                        ? t("chat.composer.placeholder")
                        : workbenchPresentation
                          ? t("chat.composer.workbenchPlaceholder")
                          : t("chat.composer.placeholder")
                  }
                  className={cn(
                    "max-h-48 min-h-14 w-full resize-none bg-transparent px-0 py-1 text-sm outline-none placeholder:text-muted-foreground",
                    workbenchPresentation && "min-h-[88px] px-4 py-2",
                    workbenchPresentation &&
                      !newChatDesign &&
                      "w-auto min-w-0 flex-1",
                    configurationLayout && "!min-h-[56px] !px-4",
                    debugLayout &&
                      "!mb-0 !min-h-[88px] !px-0 !py-0 !text-base !font-normal !leading-6 !text-[#191919] placeholder:!text-[#191919]/40"
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
                "relative flex items-center justify-between gap-2",
                workbenchPresentation &&
                  (newChatDesign
                    ? "flex-wrap pt-2 sm:flex-nowrap"
                    : "mx-4 flex-wrap pt-2 sm:flex-nowrap"),
                debugLayout && "!mx-0 !mb-0 !mt-1 !h-10"
              )}
            >
              {newChatDesign && actionPanel ? (
                <button
                  type="button"
                  aria-hidden
                  tabIndex={-1}
                  className="fixed inset-0 z-10 cursor-default"
                  onClick={() => setActionPanel(null)}
                />
              ) : null}

              {newChatDesign && actionPanel === "plus" ? (
                <div className="absolute bottom-full left-0 z-20 mb-2 w-56 rounded-xl border border-[#e5e5e5] bg-white p-2 shadow-[0_8px_24px_rgba(0,0,0,0.12)]">
                  <button
                    type="button"
                    className="flex h-10 w-full items-center gap-3 rounded-[6px] px-2 text-left text-[14px] text-[#191919] hover:bg-[#f5f5f5]"
                    onClick={() => setActionPanel("skill")}
                  >
                    <Layers className="size-4 shrink-0" aria-hidden />
                    <span>{t("chat.composer.skills")}</span>
                    <ChevronRight
                      className="ml-auto size-3.5 shrink-0 text-[#808080]"
                      aria-hidden
                    />
                  </button>
                  <button
                    type="button"
                    className="flex h-10 w-full items-center gap-3 rounded-[6px] px-2 text-left text-[14px] text-[#191919] hover:bg-[#f5f5f5]"
                    onClick={() => setActionPanel("kb")}
                  >
                    <Database className="size-4 shrink-0" aria-hidden />
                    <span>{t("chat.composer.knowledge")}</span>
                    <ChevronRight
                      className="ml-auto size-3.5 shrink-0 text-[#808080]"
                      aria-hidden
                    />
                  </button>
                  <ComposerPrimitive.AddAttachment asChild>
                    <button
                      type="button"
                      className="flex h-10 w-full items-center gap-3 rounded-[6px] px-2 text-left text-[14px] text-[#191919] hover:bg-[#f5f5f5]"
                    >
                      <Link2 className="size-4 shrink-0" aria-hidden />
                      <span>{t("chat.composer.uploadFile")}</span>
                    </button>
                  </ComposerPrimitive.AddAttachment>
                  <button
                    type="button"
                    className="flex h-10 w-full items-center gap-3 rounded-[6px] px-2 text-left text-[14px] text-[#191919] hover:bg-[#f5f5f5]"
                    onClick={() => {
                      onChatModeChange("planning");
                      setActionPanel(null);
                    }}
                  >
                    <MessagesSquare className="size-4 shrink-0" aria-hidden />
                    <span>{t("chat.composer.planningMode")}</span>
                    {chatMode === "planning" ? (
                      <Check
                        className="ml-auto size-4 text-[#191919]"
                        aria-hidden
                      />
                    ) : null}
                  </button>
                  <button
                    type="button"
                    className="flex h-10 w-full items-center gap-3 rounded-[6px] px-2 text-left text-[14px] text-[#191919] hover:bg-[#f5f5f5]"
                    onClick={() => {
                      onChatModeChange("execution");
                      setActionPanel(null);
                    }}
                  >
                    <Play className="size-4 shrink-0" aria-hidden />
                    <span>{t("chat.composer.executionMode")}</span>
                    {chatMode === "execution" ? (
                      <Check
                        className="ml-auto size-4 text-[#191919]"
                        aria-hidden
                      />
                    ) : null}
                  </button>
                </div>
              ) : null}

              {newChatDesign && actionPanel === "kb" ? (
                <div className="absolute bottom-full left-0 z-20 mb-2 w-[320px] rounded-xl border border-[#e5e5e5] bg-white p-3 shadow-[0_8px_24px_rgba(0,0,0,0.12)]">
                  <div className="flex items-center gap-2 text-[14px] text-[#191919]">
                    <Database className="size-4" aria-hidden />
                    <span>{t("chat.composer.knowledge")}</span>
                  </div>
                  <StandardInput
                    value={kbSearch}
                    onChange={(event) => setKbSearch(event.target.value)}
                    placeholder={t("chat.composer.searchKnowledge")}
                    prefix={
                      <SearchIcon
                        className="size-3.5 text-[#808080]"
                        aria-hidden
                      />
                    }
                    className="mt-2"
                  />
                  <div className="mt-2 max-h-64 overflow-y-auto">
                    {kbLoading ? (
                      <p className="px-2 py-3 text-[12px] text-[#808080]">
                        {t("chat.composer.loading")}
                      </p>
                    ) : knowledgeBases.length === 0 ? (
                      <p className="px-2 py-3 text-[12px] text-[#808080]">
                        {t("chat.composer.emptyKnowledge")}
                      </p>
                    ) : (
                      knowledgeBases
                        .filter((kb) =>
                          (kb.name + (kb.description || ""))
                            .toLowerCase()
                            .includes(kbSearch.trim().toLowerCase())
                        )
                        .map((kb) => {
                          const selected = selectedKbIds.includes(kb.id);
                          return (
                            <button
                              key={kb.id}
                              type="button"
                              onClick={() =>
                                setSelectedKbIds((prev) =>
                                  prev.includes(kb.id)
                                    ? prev.filter((id) => id !== kb.id)
                                    : [...prev, kb.id]
                                )
                              }
                              className={cn(
                                "flex w-full flex-col items-start gap-0.5 rounded-[6px] px-2 py-2 text-left hover:bg-[#f5f5f5]",
                                selected && "bg-[#f5f5f5]"
                              )}
                            >
                              <span className="text-[14px] leading-[22px] text-[#191919]">
                                {kb.name}
                              </span>
                              {kb.description ? (
                                <span className="text-[12px] leading-[20px] text-[#808080]">
                                  {kb.description}
                                </span>
                              ) : null}
                            </button>
                          );
                        })
                    )}
                  </div>
                  <div className="mt-2 border-t border-[#f0f0f0] pt-2">
                    <button
                      type="button"
                      className="flex items-center gap-2 rounded-[4px] px-1 py-1.5 text-[14px] text-[#191919] hover:bg-[#f5f5f5]"
                      onClick={() => {
                        setActionPanel(null);
                        setKnowledgeModalOpen(true);
                      }}
                    >
                      <Settings className="size-4" aria-hidden />
                      <span>{t("chat.composer.manageKnowledge")}</span>
                    </button>
                  </div>
                </div>
              ) : null}

              {newChatDesign && actionPanel === "skill" ? (
                <div className="absolute bottom-full left-0 z-20 mb-2 w-[340px] rounded-xl border border-[#e5e5e5] bg-white p-3 shadow-[0_8px_24px_rgba(0,0,0,0.12)]">
                  <div className="flex items-center gap-2 text-[14px] text-[#191919]">
                    <Layers className="size-4" aria-hidden />
                    <span>{t("chat.composer.skills")}</span>
                  </div>
                  <div className="mt-2 flex items-center gap-4 overflow-x-auto border-b border-[#f0f0f0] px-1 text-[14px]">
                    <button
                      type="button"
                      onClick={() => setSkillTab("")}
                      className={cn(
                        "relative shrink-0 pb-1.5 pt-1",
                        skillTab === "" ? "text-[#2673e5]" : "text-[#191919]"
                      )}
                    >
                      {t("chat.composer.skillCategoryAll")}
                      {skillTab === "" ? (
                        <span className="absolute inset-x-0 bottom-0 h-0.5 rounded bg-[#2673e5]" />
                      ) : null}
                    </button>
                    {skillTagTabs.map((tag) => (
                      <button
                        key={tag}
                        type="button"
                        onClick={() => setSkillTab(tag)}
                        className={cn(
                          "relative shrink-0 pb-1.5 pt-1",
                          skillTab === tag ? "text-[#2673e5]" : "text-[#191919]"
                        )}
                      >
                        {tag}
                        {skillTab === tag ? (
                          <span className="absolute inset-x-0 bottom-0 h-0.5 rounded bg-[#2673e5]" />
                        ) : null}
                      </button>
                    ))}
                  </div>
                  <StandardInput
                    value={skillSearch}
                    onChange={(event) => setSkillSearch(event.target.value)}
                    placeholder={t("chat.composer.searchSkills")}
                    prefix={
                      <SearchIcon
                        className="size-3.5 text-[#808080]"
                        aria-hidden
                      />
                    }
                    className="mt-2"
                  />
                  <div className="mt-2 max-h-64 overflow-y-auto">
                    {skillsLoading ? (
                      <p className="px-2 py-3 text-[12px] text-[#808080]">
                        {t("chat.composer.loading")}
                      </p>
                    ) : filteredSkills.length === 0 ? (
                      <p className="px-2 py-3 text-[12px] text-[#808080]">
                        {t("chat.composer.emptySkills")}
                      </p>
                    ) : (
                      filteredSkills.map((skill) => {
                        const selected = selectedSkillNames.includes(
                          skill.name
                        );
                        const dotColor =
                          SKILL_DOT_COLORS[
                            Math.abs(hashString(skill.name)) %
                              SKILL_DOT_COLORS.length
                          ];
                        return (
                          <button
                            key={skill.id}
                            type="button"
                            onClick={() =>
                              setSelectedSkillNames((prev) =>
                                prev.includes(skill.name)
                                  ? prev.filter((name) => name !== skill.name)
                                  : [...prev, skill.name]
                              )
                            }
                            className={cn(
                              "flex w-full items-center gap-2 rounded-[6px] px-2 py-2 text-left hover:bg-[#f5f5f5]",
                              selected && "bg-[#f5f5f5]"
                            )}
                          >
                            <span
                              className="size-2 shrink-0 rounded-full"
                              style={{ backgroundColor: dotColor }}
                              aria-hidden
                            />
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-[14px] leading-[22px] text-[#191919]">
                                {skill.name}
                              </span>
                              {skill.description ? (
                                <span className="block truncate text-[12px] leading-[20px] text-[#808080]">
                                  {skill.description}
                                </span>
                              ) : null}
                            </span>
                          </button>
                        );
                      })
                    )}
                  </div>
                  <div className="mt-2 flex flex-col border-t border-[#f0f0f0] pt-2">
                    <button
                      type="button"
                      className="flex items-center gap-2 rounded-[4px] px-1 py-1.5 text-left text-[14px] text-[#191919] hover:bg-[#f5f5f5]"
                      onClick={() => setActionPanel(null)}
                    >
                      <Link2 className="size-4" aria-hidden />
                      <span>{t("chat.composer.addLocalSkill")}</span>
                    </button>
                    <button
                      type="button"
                      className="flex items-center gap-2 rounded-[4px] px-1 py-1.5 text-left text-[14px] text-[#191919] hover:bg-[#f5f5f5]"
                      onClick={() => {
                        setActionPanel(null);
                        onOpenWorkbenchSkillPicker?.();
                      }}
                    >
                      <Settings className="size-4" aria-hidden />
                      <span>{t("chat.composer.manageSkills")}</span>
                    </button>
                  </div>
                </div>
              ) : null}

              <div className="flex shrink-0 items-center gap-1">
                {(configurationLayout || debugLayout) && (
                  <ComposerAddAttachment
                    className={
                      debugLayout
                        ? "!size-10 !p-0 !text-[#191919] [&_svg]:!size-6"
                        : undefined
                    }
                  />
                )}
                {newChatDesign && (
                  <button
                    type="button"
                    aria-label={t("chat.composer.plus")}
                    className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-[4px] text-[#191919] hover:bg-[#f5f5f5]"
                    onClick={() =>
                      setActionPanel((panel) =>
                        panel === "plus" ? null : "plus"
                      )
                    }
                  >
                    <PlusIcon className="size-4" aria-hidden />
                  </button>
                )}
                {!compact && workbenchResources && workbenchPresentation && (
                  <TooltipWrapper tooltip={t("chat.composer.more")}>
                    <Popover open={plusOpen} onOpenChange={setPlusOpen}>
                      <PopoverTrigger asChild>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="size-8 shrink-0 p-0"
                          disabled={isRunning}
                        >
                          <PlusIcon className="size-4" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent align="start" className="w-56 p-1">
                        <Popover
                          open={plusSkillOpen}
                          onOpenChange={setPlusSkillOpen}
                        >
                          <PopoverTrigger asChild>
                            <button
                              type="button"
                              className="flex h-10 w-full items-center gap-2 rounded-lg px-2 py-2 text-base font-normal leading-6 text-foreground hover:bg-accent"
                            >
                              <SkillStackIcon className="size-4" />
                              {t("chat.composer.skills")}
                              <ChevronRight className="ml-auto size-4 opacity-50" />
                            </button>
                          </PopoverTrigger>
                          <PopoverContent
                            side="right"
                            align="start"
                            className="w-80 p-0"
                          >
                            {workbenchSkillPopover}
                          </PopoverContent>
                        </Popover>
                        <Popover
                          open={plusKnowledgeOpen}
                          onOpenChange={setPlusKnowledgeOpen}
                        >
                          <PopoverTrigger asChild>
                            <button
                              type="button"
                              className="flex h-10 w-full items-center gap-2 rounded-lg px-2 py-2 text-base font-normal leading-6 text-foreground hover:bg-accent"
                            >
                              <KnowledgeBookIcon className="size-4" />
                              {t("chat.composer.knowledgeBase")}
                              <ChevronRight className="ml-auto size-4 opacity-50" />
                            </button>
                          </PopoverTrigger>
                          <PopoverContent
                            side="right"
                            align="start"
                            className="w-80 p-0"
                          >
                            {workbenchKnowledgePopover}
                          </PopoverContent>
                        </Popover>
                        <ComposerPrimitive.AddAttachment asChild>
                          <button
                            type="button"
                            className="flex h-10 w-full items-center gap-2 rounded-lg px-2 py-2 text-base font-normal leading-6 text-foreground hover:bg-accent"
                            onClick={() => setPlusOpen(false)}
                          >
                            <Paperclip className="size-4" />
                            {t("chat.composer.uploadFile")}
                          </button>
                        </ComposerPrimitive.AddAttachment>
                        <ComposerPlusItem
                          icon={<MessageCircleMore className="size-4" />}
                          label={t("chat.composer.planningMode")}
                          active={chatMode === "planning"}
                          onSelect={() => {
                            onChatModeChange("planning");
                            setPlusOpen(false);
                          }}
                        />
                        <ComposerPlusItem
                          icon={<Play className="size-4" />}
                          label={t("chat.composer.executionMode")}
                          active={chatMode === "execution"}
                          onSelect={() => {
                            onChatModeChange("execution");
                            setPlusOpen(false);
                          }}
                        />
                      </PopoverContent>
                    </Popover>
                  </TooltipWrapper>
                )}
                {!compact && !creationMode && workbenchPresentation && (
                  <WorkbenchPlanningMenu
                    chatMode={chatMode}
                    onChatModeChange={onChatModeChange}
                    disabled={isRunning}
                  />
                )}
                {!compact && workbenchResources && (
                  <>
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
                          <SkillStackIcon
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
                  </>
                )}
                {newChatDesign ? (
                  <button
                    type="button"
                    className="flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-[4px] px-2 text-[14px] text-[#191919] hover:bg-[#f5f5f5]"
                    onClick={() =>
                      setActionPanel((panel) => (panel === "kb" ? null : "kb"))
                    }
                  >
                    <Database className="size-4" aria-hidden />
                    <span>{t("chat.composer.knowledge")}</span>
                    <ChevronDown
                      className="size-3.5 text-[#808080]"
                      aria-hidden
                    />
                  </button>
                ) : (
                  !compact &&
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
                            "h-8 shrink-0 gap-1.5 px-2 text-xs text-foreground",
                            workbenchPresentation && "text-base leading-6"
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
                          <KnowledgeBookIcon
                            className={cn(
                              "size-3.5",
                              workbenchPresentation && "size-4"
                            )}
                          />
                          <span className="truncate">
                            {workbenchPresentation
                              ? t("chat.composer.knowledgeBase")
                              : knowledgeSummary}
                          </span>
                          {workbenchPresentation && (
                            <ChevronDown
                              className="size-4 shrink-0 opacity-50"
                              aria-hidden
                            />
                          )}
                        </Button>
                      </PopoverTrigger>
                      {workbenchKnowledgePopover ? (
                        <PopoverContent align="start" className="w-80 p-0">
                          {workbenchKnowledgePopover}
                        </PopoverContent>
                      ) : null}
                    </Popover>
                  )
                )}
                {newChatDesign && (
                  <ComposerPrimitive.AddAttachment asChild>
                    <button
                      type="button"
                      className="flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-[4px] px-2 text-[14px] text-[#191919] hover:bg-[#f5f5f5]"
                    >
                      <Link2 className="size-4" aria-hidden />
                      <span>{t("chat.composer.uploadFile")}</span>
                    </button>
                  </ComposerPrimitive.AddAttachment>
                )}
                {!compact && workbenchPresentation && (
                  <ComposerAddAttachment
                    label={t("chat.composer.uploadFile")}
                    icon={<Paperclip className="size-4" />}
                  />
                )}
                {!compact &&
                  !newChatDesign &&
                  !workbenchPresentation &&
                  !configurationLayout &&
                  !debugLayout && <ComposerAddAttachment />}
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
                {!compact &&
                  allowRuntimeMetadata &&
                  onRuntimeMetadataChange && (
                    <RuntimeMetadataEditor
                      value={runtimeMetadata}
                      onChange={onRuntimeMetadataChange}
                      disabled={isRunning}
                    />
                  )}
              </div>
              <div className="ml-auto flex min-w-0 items-center gap-1">
                {showModelSelector && (
                  <ModelSelector
                    models={models}
                    showEffort={newChatDesign || Boolean(workbenchPresentation)}
                    value={selectedModelId}
                    onValueChange={onModelChange}
                    deepThinking={deepThinking}
                    onDeepThinkingChange={onDeepThinkingChange}
                    effort={
                      newChatDesign
                        ? (thinkingEffort ?? "high")
                        : thinkingEffort
                    }
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
                    className={cn(
                      "min-w-0 text-xs text-foreground [&_[data-slot=model-selector-value]]:text-foreground",
                      !debugLayout &&
                        workbenchPresentation &&
                        "text-base leading-6 [&_[data-slot=model-selector-value]]:text-base [&_[data-slot=model-selector-value]]:leading-6",
                      debugLayout &&
                        "min-w-0 max-w-[180px] text-base text-[#191919] [&_[data-slot=model-selector-value]]:text-base [&_[data-slot=model-selector-value]]:text-[#191919]"
                    )}
                  />
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
                              className={
                                configurationLayout || debugLayout
                                  ? "size-10 text-[#191919]"
                                  : "size-8 text-muted-foreground"
                              }
                            >
                              <Mic
                                className={
                                  configurationLayout || debugLayout
                                    ? "size-5"
                                    : "size-4"
                                }
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
                            className="size-8 text-destructive hover:text-destructive"
                          >
                            <MicOff className="size-4" />
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
                  newChatDesign={newChatDesign}
                  configurationLayout={configurationLayout}
                  debugLayout={debugLayout}
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
          {chatMode === "planning" ? (
            <MessageCircleMore className="size-4" />
          ) : (
            <Play className="size-4" />
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
            className="flex h-10 w-full items-center justify-between gap-2 rounded-lg px-2 py-2 text-base font-normal leading-6 hover:bg-accent"
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
  workbench?: boolean;
  newChatDesign?: boolean;
  configurationLayout?: boolean;
  debugLayout?: boolean;
}> = ({
  onSend,
  disabled,
  workbench = false,
  newChatDesign = false,
  configurationLayout = false,
  debugLayout = false,
}) => {
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
              className={cn(
                "size-8 rounded-full ml-2 border-border bg-background text-primary hover:bg-muted",
                debugLayout &&
                  "!ml-0 !size-10 !rounded-full !border-0 !bg-[#191919] !text-white"
              )}
            >
              <Square
                className={
                  debugLayout ? "size-5 fill-current" : "size-4 fill-current"
                }
              />
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
                configurationLayout || debugLayout
                  ? "size-10 rounded-[26px] bg-[#191919] text-white hover:bg-[#191919]/90 disabled:opacity-30 [&_svg]:size-6"
                  : newChatDesign
                    ? "border-0 bg-[#d9d9d9] text-white hover:bg-[#d9d9d9] disabled:bg-[#d9d9d9] disabled:text-white aria-disabled:bg-[#d9d9d9] aria-disabled:text-white [&_svg]:size-4"
                    : workbench &&
                      "size-[30px] bg-[#191919] text-white hover:bg-[#191919]/90 disabled:opacity-70"
              )}
              disabled={disabled || !hasText}
              aria-label={t("chat.composer.send")}
            >
              {configurationLayout || debugLayout ? (
                <Send />
              ) : newChatDesign ? (
                <Send className="-rotate-12" />
              ) : workbench ? (
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
