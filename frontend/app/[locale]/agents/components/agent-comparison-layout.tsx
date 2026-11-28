// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";

interface AgentComparisonLayoutProps {
  left: ReactNode;
  right: ReactNode;
  footer: ReactNode;
}

export function AgentComparisonLayout({
  left,
  right,
  footer,
}: AgentComparisonLayoutProps) {
  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div
        className="flex min-h-0 flex-1 overflow-hidden"
        data-testid="compare-results"
      >
        <div
          className="flex min-h-0 min-w-0 flex-1 flex-col border-r border-[var(--color-border-separator)]"
          data-testid="compare-result-left"
        >
          {left}
        </div>
        <div
          className="flex min-h-0 min-w-0 flex-1 flex-col"
          data-testid="compare-result-right"
        >
          {right}
        </div>
      </div>
      <div className="shrink-0 pt-3">{footer}</div>
    </div>
  );
}
