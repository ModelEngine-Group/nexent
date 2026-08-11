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
} from "@/types/knowledgeScope";
import { ConversationKnowledgeScopeModal } from "./conversation-knowledge-scope-modal";

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
  knowledgeCapabilities?: KnowledgeCapabilities | null;
  onKnowledgeScopeChange?: (
    scope: ConversationKnowledgeScope | null
  ) => Promise<void> | void;
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

export const Composer: FC<ComposerProps> = ({
  models,
  selectedModelId,
  onModelChange,
  chatMode,
  onChatModeChange,
  showModelSelector = true,
  isDictationConfigured = false,
  knowledgeScope = null,
  knowledgeCapabilities = null,
  onKnowledgeScopeChange,
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
    const summary = t("chat.knowledgeScope.summary", {
      value: parts.join(" · ") || t("chat.knowledgeScope.unavailable"),
    });
    return hasIncompatibleScope
      ? `${summary} · ${t("chat.knowledgeScope.incompatibleShort")}`
      : summary;
  }, [knowledgeScope, knowledgeCapabilities, hasIncompatibleScope, t]);

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
      <PlanView />

      {/* Mode switcher above input */}
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

      {/* Composer Primitive Root */}
      <ComposerPrimitive.Root className="flex w-full flex-col px-1 py-1 outline-none">
        <ComposerAttachments />
        <ComposerPrimitive.Input
          placeholder={t("chat.composer.placeholder")}
          className="mb-1 max-h-32 min-h-14 w-full resize-none bg-transparent px-3 py-1 text-sm outline-none placeholder:text-muted-foreground"
          rows={1}
          submitMode="enter"
          autoFocus
        />
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
            {(knowledgeCapabilities?.sources.local.enabled ||
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
          </div>
          <div className="ml-auto flex items-center gap-1">
            <ComposerAddAttachment />
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
            <ComposerSendOrCancel />
          </div>
        </div>
      </ComposerPrimitive.Root>
      <ConversationKnowledgeScopeModal
        open={knowledgeModalOpen}
        value={knowledgeScope}
        capabilities={knowledgeCapabilities}
        onCancel={() => setKnowledgeModalOpen(false)}
        onConfirm={async (scope) => {
          await onKnowledgeScopeChange?.(scope);
          setKnowledgeModalOpen(false);
        }}
        onRestoreDefault={async () => {
          await onKnowledgeScopeChange?.(null);
          setKnowledgeModalOpen(false);
        }}
      />
    </div>
  );
};

// `ComposerPrimitive.Cancel` / `Send` forward their internal `onClick` to the
// direct child via Radix Slot, so the Button MUST be the immediate child for
// the click handler to actually fire. The tooltip wrapper sits outside so its
// Trigger can use `asChild` against the Button. `AuiIf` toggles between the
// two branches declaratively based on `thread.isRunning`.
const ComposerSendOrCancel: FC = () => {
  const { t } = useTranslation();

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
            <Button size="icon" className="size-8 rounded-full ml-2">
              <ArrowUp className="size-5" />
            </Button>
          </ComposerPrimitive.Send>
        </TooltipWrapper>
      </AuiIf>
    </>
  );
};
