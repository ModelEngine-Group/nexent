// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState, type FC } from "react";
import { useTranslation } from "react-i18next";
import { useAuiState, useMessageTiming } from "@assistant-ui/react";
import { Zap } from "lucide-react";
import type { StepTokenCount } from "../adapter/remote-chat-model-adapter";

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

/**
 * Displays the highest observed request-context occupancy in an Agent run.
 *
 * Each request is compared with its own context window. Model calls are not
 * accumulated because cumulative traffic is a cost metric, not context usage.
 * Usage belongs to each message, for both live streams and restored history.
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

  const steps: readonly StepTokenCount[] = messageSteps ?? [];

  if (steps.length === 0) return null;

  const latestStep = steps[steps.length - 1];
  const observedSteps = steps.flatMap((step) => {
    if (
      step.inputKnown === false ||
      step.contextWindowTokens === null ||
      step.contextWindowTokens <= 0
    ) {
      return [];
    }

    return [
      {
        step,
        contextWindowTokens: step.contextWindowTokens,
        usageRatio: step.stepInputTokens / step.contextWindowTokens,
      },
    ];
  });

  const peakContext = observedSteps.reduce<
    (typeof observedSteps)[number] | undefined
  >(
    (peak, current) =>
      peak === undefined || current.usageRatio > peak.usageRatio
        ? current
        : peak,
    undefined
  );

  const unknown = t("chat.tokenUsage.unknown");
  if (peakContext === undefined)
    return (
      <span
        className="text-xs text-muted-foreground"
        data-token-usage="summary"
      >
        {t("chat.tokenUsage.input")}{" "}
        {latestStep.inputKnown === false ? unknown : latestStep.stepInputTokens}
        {" / "}
        {t("chat.tokenUsage.output")}{" "}
        {latestStep.outputKnown === false
          ? unknown
          : latestStep.stepOutputTokens}
      </span>
    );

  const stepCount = steps.length;
  const peakInputTokens = peakContext.step.stepInputTokens;
  const maxTokens = peakContext.contextWindowTokens;
  const usagePercent = Math.round(peakContext.usageRatio * 100);

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
          {t("chat.tokenUsage.peakContext")}
        </span>
      </button>

      {/* Expanded details popover */}
      {expanded && (
        <div className="absolute bottom-full right-0 z-50 mb-1 w-72 rounded-lg border border-border bg-popover p-3 shadow-lg">
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

          {/* Peak request context */}
          <div className="mb-3">
            <div className="mb-1.5 flex justify-between text-xs">
              <span className="text-muted-foreground">
                {t("chat.tokenUsage.peakRequestContext")}
              </span>
              <span className="font-medium text-foreground">
                {peakInputTokens.toLocaleString()} /{" "}
                {maxTokens.toLocaleString()}
              </span>
            </div>
            <div
              className="h-3 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-label={t("chat.tokenUsage.peakRequestContext")}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.min(usagePercent, 100)}
            >
              <div
                className="h-full bg-blue-500"
                data-token-usage="peak-context-bar"
                style={{ width: `${Math.min(usagePercent, 100)}%` }}
              />
            </div>
          </div>

          <div className="mb-3 flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-sm bg-blue-500" />
              <span className="text-muted-foreground">
                {t("chat.tokenUsage.input")}
              </span>
            </div>
            <span className="rounded bg-primary/10 px-1.5 py-0.5 font-medium text-primary">
              {t("chat.tokenUsage.steps", { count: stepCount })}
            </span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex items-center justify-between border-t border-border pt-2">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <span className="font-medium">
                  {t("chat.tokenUsage.peakStep")}
                </span>
              </span>
              <span className="font-medium text-foreground">
                {peakContext.step.stepNumber}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

SingleTurnTokenUsage.displayName = "SingleTurnTokenUsage";
