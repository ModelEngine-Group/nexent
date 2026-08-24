"use client";

import { useState, type FC } from "react";
import { useTranslation } from "react-i18next";
import { useAuiState, useMessageTiming } from "@assistant-ui/react";
import { Zap } from "lucide-react";
import {
  stepTokenCounts,
  type StepTokenCount,
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
    <div className="relative">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted ${className ?? ""}`}
      >
        <Zap className="size-3 text-amber-500" />
        <span className="font-medium text-foreground">{usagePercent}%</span>
        <span className="text-muted-foreground/70">
          {t("chat.tokenUsage.used")}
        </span>
      </button>

      {/* Expanded details popover */}
      {expanded && (
        <div className="absolute bottom-full right-0 z-50 mb-1 w-64 rounded-lg border border-border bg-popover p-3 shadow-lg">
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
        </div>
      )}
    </div>
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
      { stepTokenCounts?: StepTokenCount[] } | undefined;
    return custom?.stepTokenCounts;
  });

  // Message-level metadata wins when present; otherwise use the live stream
  // registry. The two sources are never populated simultaneously — historical
  // conversations take the metadata path, live streaming takes the registry.
  const steps: readonly StepTokenCount[] = messageSteps ?? stepTokenCounts;

  if (steps.length === 0) return null;

  const latestStep = steps[steps.length - 1];
  const budget = latestStep.contextBudget;
  const contextWindowTokens = latestStep.contextWindowTokens;
  const tokenThreshold = latestStep.tokenThreshold;
  const maxTokens = contextWindowTokens ?? tokenThreshold;

  if (maxTokens === null) return null;

  const stepCount = steps.length;

  const finalInputTokens = budget?.final_tokens ?? latestStep.stepInputTokens;
  const compositionDenominator = Math.max(1, finalInputTokens);
  const effectiveLimit = budget?.hard_budget ?? maxTokens;
  const outputTokens = latestStep.totalOutputTokens;
  const usagePercent = Math.round((finalInputTokens / effectiveLimit) * 100);
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
  const composition = budget
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

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted ${className ?? ""}`}
      >
        <Zap className="size-3 text-amber-500" />
        <span className="font-medium text-foreground">{usagePercent}%</span>
        <span className="text-muted-foreground/70">
          {t("chat.tokenUsage.turn")}
        </span>
      </button>

      {/* Expanded details popover */}
      {expanded && (
        <div className="absolute bottom-full right-0 z-50 mb-1 w-80 rounded-lg border border-border bg-popover p-4 shadow-lg">
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

          {/* Final request and context composition */}
          <div className="mb-3">
            <div className="mb-1.5 flex justify-between text-xs">
              <span className="font-medium text-foreground">
                {t("chat.tokenUsage.finalRequest")}
              </span>
              <span className="font-medium text-foreground">
                {finalInputTokens.toLocaleString()} /{" "}
                {effectiveLimit.toLocaleString()}
              </span>
            </div>
            <div
              className="flex h-3 overflow-hidden rounded-full bg-muted"
              aria-label={t("chat.tokenUsage.composition")}
            >
              {composition.map((item) => (
                <div
                  key={item.key}
                  className={item.color}
                  style={{ width: `${(item.tokens / effectiveLimit) * 100}%` }}
                  title={`${t(item.label)}: ${item.tokens.toLocaleString()}`}
                />
              ))}
            </div>
          </div>

          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="font-medium text-foreground">
              {t("chat.tokenUsage.composition")}
            </span>
            <span className="rounded bg-primary/10 px-1.5 py-0.5 font-medium text-primary">
              {t("chat.tokenUsage.steps", { count: stepCount })}
            </span>
          </div>

          <div className="space-y-2 text-xs">
            {budget && (
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
                      {item.tokens.toLocaleString()} ·{" "}
                      {Math.round((item.tokens / compositionDenominator) * 100)}
                      %
                    </span>
                  </div>
                ))}
                <div className="mt-2 border-t border-border pt-2 font-medium text-foreground">
                  {t("chat.tokenUsage.responseOutput")}
                </div>
                <div className="flex justify-between text-muted-foreground">
                  <span>{t("chat.tokenUsage.generated")}</span>
                  <span>{outputTokens.toLocaleString()}</span>
                </div>
                {latestStep.outputFinishReason && (
                  <div className="flex justify-between text-muted-foreground">
                    <span>{t("chat.tokenUsage.finishReason")}</span>
                    <span>{latestStep.outputFinishReason}</span>
                  </div>
                )}
                <div className="flex justify-between text-muted-foreground">
                  <span>{t("chat.tokenUsage.countSource")}</span>
                  <span>{budget.count_source}</span>
                </div>
                {budget.compression.attempted && (
                  <div className="flex justify-between text-green-600">
                    <span>{t("chat.tokenUsage.compactionSaved")}</span>
                    <span>
                      {budget.compression.saved_tokens.toLocaleString()} (
                      {Math.round(budget.compression.ratio * 100)}%)
                    </span>
                  </div>
                )}
                {budget.recovery_state !== "not_needed" && (
                  <div className="flex justify-between text-muted-foreground">
                    <span>{t("chat.tokenUsage.recovery")}</span>
                    <span>{budget.recovery_state}</span>
                  </div>
                )}
              </div>
            )}
            {!budget && (
              <div className="text-muted-foreground">
                {t("chat.tokenUsage.breakdownUnavailable")}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

SingleTurnTokenUsage.displayName = "SingleTurnTokenUsage";
