"use client";

import {
  useMemo,
  useState,
  useSyncExternalStore,
  type FC,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
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
  Database,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { AuiIf, ComposerPrimitive, useAuiState } from "@assistant-ui/react";
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
import type { SkillFileContent } from "@/types/skill";
import { SkillFileMentionPopover } from "../ui/skill-file-mention";
import { DirectiveChip } from "../ui/directive-text";
import {
  combinedSkillDirectiveFormatter,
  skillDirectiveIconMap,
} from "../ui/skill-directives";
import { RuntimeMetadataEditor } from "@/components/chat/RuntimeMetadataEditor";

export type ChatMode = "planning" | "execution";

export interface ComposerProps {
  models: readonly ModelOption[];
  selectedModelId?: string;
  onModelChange?: (modelId: string) => void;
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

export const Composer: FC<ComposerProps> = ({
  models,
  selectedModelId,
  onModelChange,
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
}) => {
  const { t } = useTranslation();
  const [knowledgeModalOpen, setKnowledgeModalOpen] = useState(false);
  const isRunning = useAuiState((state) => state.thread.isRunning);

  const hasIncompatibleScope = Boolean(
    knowledgeScope &&
    ((knowledgeScope.local.mode === "override" &&
      !knowledgeCapabilities?.sources.local.enabled) ||
      (knowledgeScope.aidp.mode === "override" &&
        !knowledgeCapabilities?.sources.aidp.enabled))
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
    <fieldset
      disabled={disabled}
      aria-disabled={disabled}
      className={cn(
        "relative m-0 flex min-w-0 w-full flex-col overflow-visible rounded-2xl border border-border bg-card p-0 shadow-sm",
        disabled && "cursor-not-allowed opacity-60"
      )}
    >
      {!compact && <PlanView />}

      {/* Mode switcher above input */}
      {!compact && (
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
        <ComposerPrimitive.Root className="flex w-full flex-col px-1 py-1 outline-none">
          {!compact && <ComposerAttachments />}
          {skillFiles ? (
            <LexicalComposerInput
              placeholder={t("chat.composer.placeholder")}
              className="relative mb-1 max-h-32 min-h-14 w-full bg-transparent px-3 py-1 text-sm outline-none [&_.aui-lexical-input]:min-h-12 [&_.aui-lexical-input]:outline-none [&_.aui-lexical-placeholder]:pointer-events-none [&_.aui-lexical-placeholder]:absolute [&_.aui-lexical-placeholder]:top-1 [&_.aui-lexical-placeholder]:text-muted-foreground"
              submitMode="enter"
              autoFocus
              formatter={combinedSkillDirectiveFormatter}
              directiveChip={SkillComposerDirectiveChip}
            />
          ) : (
            <ComposerPrimitive.Input
              placeholder={t("chat.composer.placeholder")}
              className="mb-1 max-h-32 min-h-14 w-full resize-none bg-transparent px-3 py-1 text-sm outline-none placeholder:text-muted-foreground"
              rows={1}
              submitMode="enter"
              autoFocus
            />
          )}
          <div className="relative mx-2 mb-2 flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-1">
              {showModelSelector && (
                <ModelSelector
                  models={models}
                  value={selectedModelId}
                  onValueChange={onModelChange}
                  variant="ghost"
                  size="sm"
                  className="shrink-0 text-xs"
                />
              )}
              {!compact &&
                (knowledgeCapabilities?.sources.local.enabled ||
                  knowledgeCapabilities?.sources.aidp.enabled ||
                  knowledgeScope) && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 min-w-0 max-w-64 gap-1.5 px-2 text-xs text-muted-foreground"
                    onClick={() => setKnowledgeModalOpen(true)}
                    disabled={isRunning}
                    title={
                      isRunning
                        ? t("chat.knowledgeScope.runningDisabled")
                        : knowledgeSummary
                    }
                  >
                    <Database className="size-3.5 shrink-0" />
                    <span className="truncate">{knowledgeSummary}</span>
                  </Button>
                )}
              {!compact && allowRuntimeMetadata && onRuntimeMetadataChange && (
                <RuntimeMetadataEditor
                  value={runtimeMetadata}
                  onChange={onRuntimeMetadataChange}
                  disabled={isRunning}
                />
              )}
            </div>
            <div className="ml-auto flex items-center gap-1">
              {!compact && <ComposerAddAttachment />}
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
                            className="size-8 text-muted-foreground"
                          >
                            <Mic className="size-4" />
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
              <ComposerSendOrCancel />
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
  );
};

// `ComposerPrimitive.Cancel` / `Send` forward their internal `onClick` to the
// direct child via Radix Slot, so the Button MUST be the immediate child for
// the click handler to actually fire. The tooltip wrapper sits outside so its
// Trigger can use `asChild` against the Button. `AuiIf` toggles between the
// two branches declaratively based on `thread.isRunning`.
const ComposerSendOrCancel: FC = () => {
  const { t } = useTranslation();
  const hasText = useAuiState((state) => state.composer.text.trim().length > 0);

  return (
    <>
      <AuiIf condition={(s) => s.thread.isRunning}>
        <TooltipWrapper tooltip={t("chat.composer.stopGenerating")} side="top">
          <ComposerPrimitive.Cancel asChild>
            <Button
              size="icon"
              variant="outline"
              className="size-8 rounded-full ml-2 border-border bg-background text-primary hover:bg-muted"
            >
              <Square className="size-4 fill-current" />
            </Button>
          </ComposerPrimitive.Cancel>
        </TooltipWrapper>
      </AuiIf>
      <AuiIf condition={(s) => !s.thread.isRunning}>
        <TooltipWrapper tooltip={t("chat.composer.send")} side="top">
          <ComposerPrimitive.Send asChild>
            <Button
              size="icon"
              className="size-8 rounded-full ml-2"
              disabled={!hasText}
              aria-label={t("chat.composer.send")}
            >
              <ArrowUp className="size-5" />
            </Button>
          </ComposerPrimitive.Send>
        </TooltipWrapper>
      </AuiIf>
    </>
  );
};
