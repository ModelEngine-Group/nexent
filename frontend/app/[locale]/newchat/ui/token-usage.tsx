"use client";

import { useState, type FC } from "react";
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
        <span className="text-muted-foreground/70">已使用</span>
      </button>

      {/* Expanded details popover */}
      {expanded && (
        <div className="absolute bottom-full right-0 z-50 mb-1 w-64 rounded-lg border border-border bg-popover p-3 shadow-lg">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-medium text-foreground">Token 使用详情</span>
            <button
              type="button"
              onClick={() => setExpanded(false)}
              className="text-muted-foreground hover:text-foreground"
            >
              <span className="sr-only">关闭</span>
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
              <span className="text-muted-foreground">上下文使用</span>
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
                输出 Token
              </span>
              <span className="font-medium text-foreground">
                {tokenCount.toLocaleString()}
              </span>
            </div>
            {timing.tokensPerSecond !== undefined && (
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-muted-foreground">
                  <span className="size-2 rounded-full bg-green-500" />
                  速度
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
export const SingleTurnTokenUsage: FC<SingleTurnTokenUsageProps> = ({ className }) => {
  const [expanded, setExpanded] = useState(false);

  const messageSteps = useAuiState((s) => {
    const custom = s.message.metadata?.custom as
      | { stepTokenCounts?: StepTokenCount[] }
      | undefined;
    return custom?.stepTokenCounts;
  });

  // Message-level metadata wins when present; otherwise use the live stream
  // registry. The two sources are never populated simultaneously — historical
  // conversations take the metadata path, live streaming takes the registry.
  const steps: readonly StepTokenCount[] = messageSteps ?? stepTokenCounts;

  if (steps.length === 0) return null;

  const latestStep = steps[steps.length - 1];
  const tokenThreshold = latestStep.tokenThreshold;
  const stepCount = steps.length;

  // Calculate total tokens used (sum of step_input_tokens + step_output_tokens for all steps)
  const totalTokensUsed = steps.reduce(
    (sum, step) => sum + step.stepInputTokens + step.stepOutputTokens,
    0
  );

  const usagePercent = Math.round((totalTokensUsed / tokenThreshold) * 100);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted ${className ?? ""}`}
      >
        <Zap className="size-3 text-amber-500" />
        <span className="font-medium text-foreground">{usagePercent}%</span>
        <span className="text-muted-foreground/70">本轮</span>
      </button>

      {/* Expanded details popover */}
      {expanded && (
        <div className="absolute bottom-full right-0 z-50 mb-1 w-72 rounded-lg border border-border bg-popover p-3 shadow-lg">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-medium text-foreground">
              单轮 Token 使用详情
            </span>
            <button
              type="button"
              onClick={() => setExpanded(false)}
              className="text-muted-foreground hover:text-foreground"
            >
              <span className="sr-only">关闭</span>
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

          {/* Stacked progress bar */}
          <div className="mb-3">
            <div className="mb-1.5 flex justify-between text-xs">
              <span className="text-muted-foreground">上下文使用</span>
              <span className="font-medium text-foreground">
                {totalTokensUsed.toLocaleString()} / {tokenThreshold.toLocaleString()}
              </span>
            </div>
            <div className="flex h-3 overflow-hidden rounded-full bg-muted">
              {steps.map((step, index) => {
                const stepTotal = step.stepInputTokens + step.stepOutputTokens;
                const stepPercent = (stepTotal / tokenThreshold) * 100;
                const inputPercent = (step.stepInputTokens / tokenThreshold) * 100;
                const outputPercent = (step.stepOutputTokens / tokenThreshold) * 100;

                return (
                  <div
                    key={step.stepNumber}
                    className="group relative"
                    style={{
                      width: `${Math.min(stepPercent, 100 - (index > 0 ? steps.slice(0, index).reduce((sum, s) => sum + ((s.stepInputTokens + s.stepOutputTokens) / tokenThreshold) * 100, 0) : 0))}%`,
                    }}
                    title={`Step ${step.stepNumber}: ${step.stepInputTokens} in + ${step.stepOutputTokens} out`}
                  >
                    {/* Input portion (blue) */}
                    <div
                      className="absolute inset-y-0 left-0 bg-blue-500"
                      style={{ width: `${(inputPercent / stepPercent) * 100}%` }}
                    />
                    {/* Output portion (amber) */}
                    <div
                      className="absolute inset-y-0 bg-amber-500"
                      style={{
                        left: `${(inputPercent / stepPercent) * 100}%`,
                        width: `${(outputPercent / stepPercent) * 100}%`,
                      }}
                    />
                    {/* Step number label on hover */}
                    <div className="absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100">
                      <span className="text-[9px] font-medium text-white drop-shadow-md">
                        {step.stepNumber}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Legend */}
          <div className="mb-3 flex items-center justify-between text-xs">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-sm bg-blue-500" />
                <span className="text-muted-foreground">输入</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-sm bg-amber-500" />
                <span className="text-muted-foreground">输出</span>
              </div>
            </div>
            <span className="rounded bg-primary/10 px-1.5 py-0.5 font-medium text-primary">
              {stepCount} Step{stepCount > 1 ? "s" : ""}
            </span>
          </div>

          {/* Step details */}
          <div className="space-y-2 text-xs">
            <div className="flex items-center justify-between border-t border-border pt-2">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <span className="font-medium">总计</span>
              </span>
              <span className="font-medium text-foreground">
                {totalTokensUsed.toLocaleString()} / {tokenThreshold.toLocaleString()}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

SingleTurnTokenUsage.displayName = "SingleTurnTokenUsage";
