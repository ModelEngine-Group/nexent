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
 * Displays context-window occupancy when a completed Agent turn ends.
 *
 * The last model request in a completed turn is the request that produced the
 * final answer. Earlier requests are intentionally ignored: they describe
 * intermediate Agent work rather than how much context remains for the next
 * user turn. Usage belongs to each message, for both live streams and restored
 * history.
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
  const unknown = t("chat.tokenUsage.unknown");
  if (
    latestStep.inputKnown === false ||
    latestStep.contextWindowTokens === null ||
    latestStep.contextWindowTokens <= 0
  )
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

  const inputTokens = latestStep.stepInputTokens;
  const maxTokens = latestStep.contextWindowTokens;
  const remainingTokens = Math.max(maxTokens - inputTokens, 0);
  const usagePercent = Math.round((inputTokens / maxTokens) * 100);
  const remainingPercent = Math.max(100 - usagePercent, 0);

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
          {t("chat.tokenUsage.contextUsed")}
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

          {/* Context window at turn completion */}
          <div className="mb-3">
            <div className="mb-1.5 flex justify-between text-xs">
              <span className="text-muted-foreground">
                {t("chat.tokenUsage.turnEndContext")}
              </span>
              <span className="font-medium text-foreground">
                {inputTokens.toLocaleString()} / {maxTokens.toLocaleString()}
              </span>
            </div>
            <div
              className="h-3 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-label={t("chat.tokenUsage.turnEndContext")}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.min(usagePercent, 100)}
            >
              <div
                className="h-full bg-blue-500"
                data-token-usage="turn-end-context-bar"
                style={{ width: `${Math.min(usagePercent, 100)}%` }}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 border-t border-border pt-2 text-xs">
            <div>
              <div className="text-muted-foreground">
                {t("chat.tokenUsage.used")}
              </div>
              <div className="font-medium text-foreground">
                {inputTokens.toLocaleString()} · {usagePercent}%
              </div>
            </div>
            <div className="text-right">
              <div className="text-muted-foreground">
                {t("chat.tokenUsage.remaining")}
              </div>
              <div className="font-medium text-foreground">
                {remainingTokens.toLocaleString()} · {remainingPercent}%
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

SingleTurnTokenUsage.displayName = "SingleTurnTokenUsage";
