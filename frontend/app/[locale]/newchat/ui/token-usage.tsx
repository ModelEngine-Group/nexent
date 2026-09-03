"use client";

import { useState, type FC } from "react";
import { useTranslation } from "react-i18next";
import { useAuiState, useMessageTiming } from "@assistant-ui/react";
import { Zap } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  stepTokenCounts,
  type ProviderCallUsageV2,
  type StepTokenCount,
  type TurnUsageV2,
} from "../adapter/remote-chat-model-adapter";

interface TokenUsageProps {
  className?: string;
}

/**
 * Displays conversation-level token usage (for future use).
 * Currently not implemented - reserved for total conversation token tracking.
 */
export const TokenUsage: FC<TokenUsageProps> = ({ className }) => {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const timing = useMessageTiming();

  if (!timing?.tokenCount) return null;

  const tokenCount = timing.tokenCount;
  const usagePercent = Math.round((tokenCount / 128000) * 100);

  return (
    <Popover open={expanded} onOpenChange={setExpanded}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted ${className ?? ""}`}
        >
          <Zap className="size-3 text-amber-500" />
          <span className="font-medium text-foreground">{usagePercent}%</span>
          <span className="text-muted-foreground/70">
            {t("chat.tokenUsage.used")}
          </span>
        </button>
      </PopoverTrigger>

      <PopoverContent
        side="top"
        align="end"
        sideOffset={4}
        collisionPadding={8}
        sticky="always"
        className="max-h-[var(--radix-popover-content-available-height)] w-[min(16rem,calc(100vw-1rem))] max-w-[var(--radix-popover-content-available-width)] overflow-y-auto rounded-lg p-3"
      >
        <div className="mb-3 flex items-center justify-between">
          <span className="text-xs font-medium text-foreground">
            {t("chat.tokenUsage.details")}
          </span>
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className="text-muted-foreground hover:text-foreground"
          >
            <span className="sr-only">{t("chat.tokenUsage.close")}</span>
            <svg
              className="size-3.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Progress bar */}
        <div className="mb-3">
          <div className="mb-1 flex justify-between text-xs">
            <span className="text-muted-foreground">
              {t("chat.tokenUsage.context")}
            </span>
            <span className="font-medium text-foreground">
              {tokenCount.toLocaleString()} / 128000
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-amber-500 transition-all"
              style={{ width: `${Math.min(usagePercent, 100)}%` }}
            />
          </div>
        </div>

        {/* Details */}
        <div className="space-y-2 text-xs">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className="size-2 rounded-full bg-blue-500" />
              {t("chat.tokenUsage.output")}
            </span>
            <span className="font-medium text-foreground">
              {tokenCount.toLocaleString()}
            </span>
          </div>
          {timing.tokensPerSecond !== undefined && (
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <span className="size-2 rounded-full bg-green-500" />
                {t("chat.tokenUsage.speed")}
              </span>
              <span className="font-medium text-foreground">
                {timing.tokensPerSecond.toFixed(1)} tok/s
              </span>
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
};

TokenUsage.displayName = "TokenUsage";

// ============================================================
// SingleTurnTokenUsage - Per-turn step-by-step token display
// ============================================================

interface SingleTurnTokenUsageProps {
  className?: string;
}

const CONTEXT_COMPONENTS = [
  ["message_text", "chat.tokenUsage.components.messageText", "bg-blue-500"],
  [
    "message_framing",
    "chat.tokenUsage.components.messageFraming",
    "bg-cyan-500",
  ],
  ["tools", "chat.tokenUsage.components.tools", "bg-violet-500"],
  ["media", "chat.tokenUsage.components.media", "bg-pink-500"],
  ["reasoning", "chat.tokenUsage.components.reasoning", "bg-amber-500"],
  [
    "other_semantic",
    "chat.tokenUsage.components.otherSemantic",
    "bg-emerald-500",
  ],
] as const;

const V2_CONTEXT_COMPONENTS = [
  [
    "system_instructions",
    "chat.tokenUsage.components.systemInstructions",
    "bg-blue-500",
  ],
  ["user_history", "chat.tokenUsage.components.userHistory", "bg-cyan-500"],
  [
    "assistant_history",
    "chat.tokenUsage.components.assistantHistory",
    "bg-sky-500",
  ],
  [
    "current_request",
    "chat.tokenUsage.components.currentRequest",
    "bg-indigo-500",
  ],
  [
    "retrieved_context",
    "chat.tokenUsage.components.retrievedContext",
    "bg-emerald-500",
  ],
  [
    "tool_definitions",
    "chat.tokenUsage.components.toolDefinitions",
    "bg-violet-500",
  ],
  [
    "tool_calls_results",
    "chat.tokenUsage.components.toolResults",
    "bg-fuchsia-500",
  ],
  [
    "attachments_media",
    "chat.tokenUsage.components.attachmentsMedia",
    "bg-pink-500",
  ],
] as const;

const countSourceKey = (value: string) =>
  `chat.tokenUsage.countSources.${value}`;
const recoveryStateKey = (value: string) =>
  `chat.tokenUsage.recoveryStates.${value}`;

/**
 * Displays per-step token consumption with a stacked progress bar.
 * Each step shows input tokens (blue) + output tokens (amber) relative to the token threshold.
 *
 * Data source resolution:
 * - Prefer per-message metadata (`metadata.custom.stepTokenCounts`) so historical
 *   conversations restored via the thread history adapter can render the exact
 *   step breakdown persisted in the database.
 * - Fall back to the global `stepTokenCounts` registry written during live
 *   streaming runs.
 */
export const SingleTurnTokenUsage: FC<SingleTurnTokenUsageProps> = ({
  className,
}) => {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const messageSteps = useAuiState((s) => {
    const custom = s.message.metadata?.custom as
      | {
          stepTokenCounts?: StepTokenCount[];
          providerCallUsages?: ProviderCallUsageV2[];
          turnUsage?: TurnUsageV2;
        }
      | undefined;
    return custom?.stepTokenCounts;
  });
  const providerCallUsages = useAuiState((s) => {
    const custom = s.message.metadata?.custom as
      | {
          providerCallUsages?: ProviderCallUsageV2[];
        }
      | undefined;
    return custom?.providerCallUsages;
  });
  const turnUsage = useAuiState((s) => {
    const custom = s.message.metadata?.custom as
      | {
          turnUsage?: TurnUsageV2;
        }
      | undefined;
    return custom?.turnUsage;
  });

  // Message-level metadata wins when present; otherwise use the live stream
  // registry. The two sources are never populated simultaneously — historical
  // conversations take the metadata path, live streaming takes the registry.
  const steps: readonly StepTokenCount[] = messageSteps ?? stepTokenCounts;

  if (steps.length === 0 && !turnUsage) return null;

  const latestStep = steps[steps.length - 1];
  const recoveryStep = [...steps].reverse().find((step) => {
    const state = step.contextBudget?.recovery_state;
    return Boolean(state && !["not_needed", "not_attempted"].includes(state));
  });
  // Recovery commonly happens on the action step before a second step emits
  // the final answer. Preserve that recovery evidence instead of hiding it
  // behind the last step's ordinary, non-recovery budget snapshot.
  const budget = recoveryStep?.contextBudget ?? latestStep?.contextBudget;
  const contextWindowTokens = latestStep?.contextWindowTokens ?? null;
  const tokenThreshold = latestStep?.tokenThreshold ?? null;
  const maxTokens = contextWindowTokens ?? tokenThreshold;

  const stepCount = steps.length;
  const finalProviderCall = [...(providerCallUsages ?? [])]
    .reverse()
    .find((call) => call.status === "completed" && call.source === "provider");
  const observedTurnUsage =
    turnUsage?.schema_version === 3 || turnUsage?.data_quality === "provider"
      ? turnUsage
      : null;
  const peakContext = observedTurnUsage?.peak_context;
  const finalInputTokens =
    peakContext?.input_tokens ??
    budget?.final_tokens ??
    latestStep?.stepInputTokens;
  if (finalInputTokens === undefined || finalInputTokens === null) return null;
  const effectiveLimit =
    peakContext?.limit_tokens ?? budget?.hard_budget ?? maxTokens;
  const outputTokens = finalProviderCall?.usage.output_tokens;
  const exactUsagePercent = effectiveLimit
    ? (finalInputTokens / effectiveLimit) * 100
    : null;
  const usagePercentLabel =
    exactUsagePercent === null
      ? null
      : exactUsagePercent > 0 && exactUsagePercent < 1
        ? "<1%"
        : `${Math.round(exactUsagePercent)}%`;
  const contextBarDenominator = Math.max(1, effectiveLimit ?? finalInputTokens);
  const unusedContextTokens = effectiveLimit
    ? Math.max(0, effectiveLimit - finalInputTokens)
    : null;
  const peakCall = providerCallUsages?.find(
    (call) => call.call_id === peakContext?.call_id
  );
  const v2Composition = peakCall?.context_composition;
  const knownComponents = budget
    ? CONTEXT_COMPONENTS.map(([key, label, color]) => ({
        key,
        label,
        color,
        tokens: Math.max(0, budget.components[key] ?? 0),
      })).filter((item) => item.tokens > 0)
    : [];
  const knownComponentTotal = knownComponents.reduce(
    (sum, item) => sum + item.tokens,
    0
  );
  const unclassifiedTokens = Math.max(
    0,
    finalInputTokens - knownComponentTotal
  );
  const composition = v2Composition
    ? V2_CONTEXT_COMPONENTS.map(([key, label, color]) => ({
        key,
        label,
        color,
        tokens: Math.max(0, v2Composition.segments[key] ?? 0),
      })).filter((item) => item.tokens > 0)
    : budget
      ? [
          ...knownComponents,
          ...(unclassifiedTokens > 0
            ? [
                {
                  key: "unclassified",
                  label: "chat.tokenUsage.components.unclassified",
                  color: "bg-slate-400",
                  tokens: unclassifiedTokens,
                },
              ]
            : []),
        ]
      : [];
  const estimatedCompositionTotal = Math.max(
    1,
    composition.reduce((sum, item) => sum + item.tokens, 0)
  );

  const recoveryExhausted =
    budget?.recovery_state === "exhausted" ||
    Boolean(budget?.recovery?.terminal_reason);

  return (
    <div className="flex flex-wrap items-center justify-end gap-1.5">
      {budget?.recovery?.auto_continued && (
        <span className="rounded bg-green-50 px-1.5 py-0.5 text-xs text-green-700">
          {t("taskWindow.contextBudget.autoContinued")}
        </span>
      )}
      {recoveryExhausted && budget?.recovery?.partial_preserved && (
        <span className="rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-700">
          {t("chat.tokenUsage.recoveryExhausted")}
        </span>
      )}
      <Popover open={expanded} onOpenChange={setExpanded}>
        <PopoverTrigger asChild>
          <button
            type="button"
            className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted ${className ?? ""}`}
          >
            <Zap className="size-3 text-amber-500" />
            <span className="font-medium text-foreground">
              {usagePercentLabel === null
                ? `${finalInputTokens.toLocaleString()} input`
                : usagePercentLabel}
            </span>
            <span className="text-muted-foreground/70">
              {t("chat.tokenUsage.turn")}
            </span>
          </button>
        </PopoverTrigger>

        <PopoverContent
          side="top"
          align="end"
          sideOffset={4}
          collisionPadding={8}
          sticky="always"
          className="max-h-[var(--radix-popover-content-available-height)] w-[min(52rem,calc(100vw-1rem))] max-w-[var(--radix-popover-content-available-width)] overflow-y-auto rounded-lg p-4"
        >
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-medium text-foreground">
              {t("chat.tokenUsage.turnDetails")}
            </span>
            <button
              type="button"
              onClick={() => setExpanded(false)}
              className="text-muted-foreground hover:text-foreground"
            >
              <span className="sr-only">{t("chat.tokenUsage.close")}</span>
              <svg
                className="size-3.5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>

          {/* Row 1: request capacity and semantic distribution */}
          <section className="rounded-lg border border-border bg-muted/20 p-3">
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-xs">
              <span className="font-medium text-foreground">
                {t("chat.tokenUsage.observedPeakRequest")}
              </span>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground">
                <span className="font-medium text-foreground">
                  {effectiveLimit
                    ? `${finalInputTokens.toLocaleString()} / ${effectiveLimit.toLocaleString()}`
                    : `${finalInputTokens.toLocaleString()} input`}
                </span>
                {exactUsagePercent !== null && (
                  <span>
                    {t("chat.tokenUsage.contextUsed", {
                      percent:
                        exactUsagePercent > 0 && exactUsagePercent < 0.1
                          ? exactUsagePercent.toFixed(2)
                          : exactUsagePercent.toFixed(1),
                    })}
                  </span>
                )}
                {unusedContextTokens !== null && (
                  <span>
                    {t("chat.tokenUsage.contextUnused", {
                      count: unusedContextTokens.toLocaleString(),
                    })}
                  </span>
                )}
              </div>
            </div>
            <div
              className="flex h-3 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700"
              aria-label={t("chat.tokenUsage.observedPeakRequest")}
            >
              <div
                className="bg-blue-500"
                style={{
                  width: `${Math.min(100, (finalInputTokens / contextBarDenominator) * 100)}%`,
                }}
                title={`${t("chat.tokenUsage.observedInput")}: ${finalInputTokens.toLocaleString()}`}
              />
            </div>
            <div className="mt-3 mb-1 flex flex-wrap items-center justify-between gap-2 text-[11px]">
              <span className="font-medium text-foreground">
                {t("chat.tokenUsage.estimatedComposition")}
              </span>
              {budget && (
                <span className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
                  {t("chat.tokenUsage.requestBudgetCountMethod")}:{" "}
                  {t(countSourceKey(budget.count_source), {
                    defaultValue: budget.count_source,
                  })}
                </span>
              )}
            </div>
            <div className="flex h-3 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              {composition.map((item) => (
                <div
                  key={item.key}
                  className={item.color}
                  style={{
                    width: `${(item.tokens / estimatedCompositionTotal) * 100}%`,
                  }}
                />
              ))}
            </div>
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
              {composition.map((item) => (
                <span key={item.key} className="inline-flex items-center gap-1">
                  <span className={`size-2 rounded-sm ${item.color}`} />
                  {t(item.label)} ·{" "}
                  {Math.round((item.tokens / estimatedCompositionTotal) * 100)}%
                </span>
              ))}
              <span className="ml-auto rounded bg-primary/10 px-1.5 py-0.5 font-medium text-primary">
                {t("chat.tokenUsage.steps", { count: stepCount })}
              </span>
            </div>
          </section>

          {/* Row 2: compact multi-column details */}
          <div className="mt-3 grid gap-3 text-xs md:grid-cols-3">
            <section className="min-w-0 rounded-lg border border-border p-3">
              <h3 className="mb-2 font-medium text-foreground">
                {t("chat.tokenUsage.modelCallCost")}
              </h3>
              {finalProviderCall && (
                <div className="space-y-1">
                  {(
                    [
                      ["input_tokens", "chat.tokenUsage.input"],
                      ["cache_read_tokens", "chat.tokenUsage.cacheRead"],
                      ["cache_write_tokens", "chat.tokenUsage.cacheWrite"],
                      ["output_tokens", "chat.tokenUsage.output"],
                      ["reasoning_tokens", "chat.tokenUsage.reasoning"],
                      ["total_tokens", "chat.tokenUsage.total"],
                    ] as const
                  ).map(([key, label]) => {
                    const value = finalProviderCall.usage[key];
                    return (
                      <div
                        key={key}
                        className="flex justify-between text-muted-foreground"
                      >
                        <span>{t(label)}</span>
                        <span>
                          {value === null || value === undefined
                            ? "—"
                            : value.toLocaleString()}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
              {!finalProviderCall && (
                <div className="text-muted-foreground">
                  {t("chat.tokenUsage.apiUsageUnavailable")}
                </div>
              )}
            </section>

            <section className="min-w-0 rounded-lg border border-border p-3">
              <h3 className="mb-2 font-medium text-foreground">
                {t("chat.tokenUsage.composition")}
              </h3>
              {composition.length > 0 && (
                <div className="space-y-1">
                  {composition.map((item) => (
                    <div
                      key={item.key}
                      className="flex justify-between text-muted-foreground"
                    >
                      <span className="flex items-center gap-1.5">
                        <span className={`size-2 rounded-sm ${item.color}`} />
                        {t(item.label)}
                      </span>
                      <span>
                        {Math.round(
                          (item.tokens / estimatedCompositionTotal) * 100
                        )}
                        %
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {composition.length === 0 && (
                <div className="text-muted-foreground">
                  {t("chat.tokenUsage.breakdownUnavailable")}
                </div>
              )}
            </section>

            <section className="min-w-0 rounded-lg border border-border p-3">
              <h3 className="mb-2 font-medium text-foreground">
                {t("chat.tokenUsage.responseOutput")}
              </h3>
              <div className="space-y-1">
                <div className="flex justify-between text-muted-foreground">
                  <span>{t("chat.tokenUsage.generated")}</span>
                  <span>{outputTokens?.toLocaleString() ?? "—"}</span>
                </div>
                {latestStep?.outputFinishReason && (
                  <div className="flex justify-between text-muted-foreground">
                    <span>{t("chat.tokenUsage.finishReason")}</span>
                    <span>{latestStep.outputFinishReason}</span>
                  </div>
                )}
                {budget?.compression.attempted && (
                  <div className="flex justify-between text-green-600">
                    <span>{t("chat.tokenUsage.compactionSaved")}</span>
                    <span>
                      {budget.compression.saved_tokens.toLocaleString()} (
                      {Math.round(budget.compression.ratio * 100)}%)
                    </span>
                  </div>
                )}
                {budget && budget.recovery_state !== "not_needed" && (
                  <div className="flex justify-between text-muted-foreground">
                    <span>{t("chat.tokenUsage.recovery")}</span>
                    <span>
                      {t(recoveryStateKey(budget.recovery_state), {
                        defaultValue: budget.recovery_state,
                      })}
                    </span>
                  </div>
                )}
                {budget?.recovery?.archive_active && (
                  <div className="flex justify-between text-muted-foreground">
                    <span>{t("chat.tokenUsage.archive")}</span>
                    <span>
                      {budget.recovery.archived_item_count ?? 0} /{" "}
                      {budget.recovery.retained_item_count ?? 0}
                    </span>
                  </div>
                )}
                {(budget?.recovery?.recalled_tokens ?? 0) > 0 && (
                  <div className="flex justify-between text-muted-foreground">
                    <span>{t("chat.tokenUsage.recalledTokens")}</span>
                    <span>
                      {budget?.recovery?.recalled_tokens?.toLocaleString()}
                    </span>
                  </div>
                )}
              </div>
            </section>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
};

SingleTurnTokenUsage.displayName = "SingleTurnTokenUsage";
