"use client";

import React from "react";
import { TokenMetrics } from "@/types/chat";
import { Tooltip } from "antd";

interface TokenUsageIndicatorProps {
  latestMetrics: TokenMetrics | null;
}

function formatNumber(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export function TokenUsageIndicator({
  latestMetrics,
}: TokenUsageIndicatorProps) {
  // Matches backend _TOKEN_THRESHOLD_LEGACY_FALLBACK; shown only when the
  // backend stream does not carry a real token_threshold (rare once W2 ships).
  // Sized for the typical 32K-context band shared by most production LLMs.
  const DEFAULT_THRESHOLD = 32768;

  const estimated_context_tokens =
    latestMetrics?.estimated_context_tokens ?? null;
  const token_threshold = latestMetrics?.token_threshold ?? null;
  const hardInputBudget = latestMetrics?.hard_input_budget_tokens ?? null;
  const processingMode = latestMetrics?.context_processing_mode ?? null;
  const outputFinishReason = latestMetrics?.output_finish_reason ?? null;
  const total_output_tokens = latestMetrics?.total_output_tokens ?? 0;

  // Prefer provider-reported input usage; fall back to the pre-call estimate.
  const contextTokens =
    latestMetrics?.step_input_tokens ?? estimated_context_tokens ?? 0;
  const threshold = hardInputBudget ?? token_threshold ?? DEFAULT_THRESHOLD;
  const usageRatio =
    latestMetrics && threshold > 0 ? contextTokens / threshold : 0;
  const ratio = Math.min(usageRatio, 1);
  const pct = Math.round(usageRatio * 100);
  const isDefaultThreshold =
    hardInputBudget === null &&
    (token_threshold === null || token_threshold === undefined);

  // SVG ring parameters
  const size = 28;
  const strokeWidth = 3;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference * (1 - ratio);

  // Color: green → yellow → red
  const color = ratio < 0.6 ? "#52c41a" : ratio < 0.85 ? "#faad14" : "#ff4d4f";

  const tooltipContent = latestMetrics ? (
    <div className="text-xs space-y-1 min-w-[160px]">
      <div className="font-medium text-white mb-1">Token Usage</div>
      <div className="flex justify-between gap-4">
        <span className="text-gray-300">Context</span>
        <span className="text-white">
          {formatNumber(contextTokens)} / {formatNumber(threshold)}
          {isDefaultThreshold ? "*" : ""} ({pct}%)
        </span>
      </div>
      {outputFinishReason !== null && (
        <div className="flex justify-between gap-4">
          <span className="text-gray-300">Output stopped by</span>
          <span
            className={
              outputFinishReason === "length" ? "text-red-300" : "text-white"
            }
          >
            {outputFinishReason}
          </span>
        </div>
      )}
      {hardInputBudget !== null && token_threshold !== null && (
        <div className="flex justify-between gap-4">
          <span className="text-gray-300">Compression starts at</span>
          <span className="text-white">{formatNumber(token_threshold)}</span>
        </div>
      )}
      {processingMode !== null && (
        <div className="flex justify-between gap-4">
          <span className="text-gray-300">Policy</span>
          <span className="text-white">{processingMode}</span>
        </div>
      )}
      {isDefaultThreshold && (
        <div className="text-gray-400 text-xs">* estimated limit</div>
      )}
      <div className="flex justify-between gap-4">
        <span className="text-gray-300">Output</span>
        <span className="text-white">
          {formatNumber(total_output_tokens)} tokens
        </span>
      </div>
    </div>
  ) : (
    <div className="text-xs text-gray-300">No token data yet</div>
  );

  return (
    <Tooltip title={tooltipContent} placement="topRight">
      <div
        className="flex items-center justify-center cursor-default select-none"
        style={{ width: size, height: size }}
      >
        <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
          {/* Background ring */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="#e8e8e8"
            strokeWidth={strokeWidth}
          />
          {/* Fill ring */}
          {ratio > 0 && (
            <circle
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={color}
              strokeWidth={strokeWidth}
              strokeDasharray={circumference}
              strokeDashoffset={strokeDashoffset}
              strokeLinecap="round"
              style={{
                transition: "stroke-dashoffset 0.4s ease, stroke 0.4s ease",
              }}
            />
          )}
        </svg>
      </div>
    </Tooltip>
  );
}
