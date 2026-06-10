"use client";

import React from "react";
import { Tooltip } from "@/components/ui/tooltip";
import { TokenMetrics } from "@/types/chat";

interface TokenUsageIndicatorProps {
  latestMetrics: TokenMetrics | null;
}

function formatNumber(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export function TokenUsageIndicator({ latestMetrics }: TokenUsageIndicatorProps) {
  const DEFAULT_THRESHOLD = 32000;

  const estimated_context_tokens = latestMetrics?.estimated_context_tokens ?? null;
  const token_threshold = latestMetrics?.token_threshold ?? null;
  const total_output_tokens = latestMetrics?.total_output_tokens ?? 0;

  // Compute fill ratio — prefer real estimated context, fall back to step input
  const contextTokens = estimated_context_tokens ?? latestMetrics?.step_input_tokens ?? 0;
  const threshold = token_threshold ?? DEFAULT_THRESHOLD;
  const ratio = latestMetrics ? (threshold > 0 ? Math.min(contextTokens / threshold, 1) : 0) : 0;
  const pct = Math.round(ratio * 100);
  const isDefaultThreshold = token_threshold === null || token_threshold === undefined;

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
          {formatNumber(contextTokens)} / {formatNumber(threshold)}{isDefaultThreshold ? "*" : ""} ({pct}%)
        </span>
      </div>
      {isDefaultThreshold && (
        <div className="text-gray-400 text-xs">* estimated limit</div>
      )}
      <div className="flex justify-between gap-4">
        <span className="text-gray-300">Output</span>
        <span className="text-white">{formatNumber(total_output_tokens)} tokens</span>
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
              style={{ transition: "stroke-dashoffset 0.4s ease, stroke 0.4s ease" }}
            />
          )}
        </svg>
      </div>
    </Tooltip>
  );
}
