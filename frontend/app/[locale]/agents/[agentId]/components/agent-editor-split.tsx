// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Splitter } from "antd";

interface AgentEditorSplitProps {
  children: ReactNode;
  panel: ReactNode;
  visible: boolean;
  expanded?: boolean;
  side?: "start" | "end";
  defaultSize?: string;
  min?: number;
  max?: number;
  contentMin?: number;
  testId?: string;
}

/** Keep conversation/form subtrees mounted while their layout changes. */
export function AgentEditorSplit({
  children,
  panel,
  visible,
  expanded = false,
  side = "end",
  defaultSize = "48%",
  min = 25,
  max = 65,
  contentMin,
  testId,
}: AgentEditorSplitProps) {
  const [size, setSize] = useState(defaultSize);
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  useEffect(() => {
    const container = containerRef.current;
    if (!container || contentMin === undefined) return;
    const updateWidth = () => setContainerWidth(container.clientWidth);
    updateWidth();
    const observer = new ResizeObserver(updateWidth);
    observer.observe(container);
    return () => observer.disconnect();
  }, [contentMin]);
  // Reserve space for the configuration header, while fitting small viewports.
  const panelMax =
    contentMin !== undefined && containerWidth > 0
      ? Math.min(max, Math.max(min, (1 - contentMin / containerWidth) * 100))
      : max;
  const boundedSize = `${Math.min(panelMax, Math.max(min, Number.parseFloat(size)))}%`;
  const resizable = visible && !expanded;
  const sidePanel = (
    <Splitter.Panel
      key="side"
      size={!visible ? 0 : expanded ? "100%" : boundedSize}
      min={resizable ? `${min}%` : 0}
      max={resizable ? `${panelMax}%` : undefined}
      resizable={resizable}
    >
      {panel}
    </Splitter.Panel>
  );
  const contentPanel = (
    <Splitter.Panel
      key="content"
      min={resizable ? `${100 - panelMax}%` : 0}
      resizable={resizable}
    >
      {children}
    </Splitter.Panel>
  );

  return (
    <div
      ref={containerRef}
      data-testid={testId}
      className="h-full min-h-0 min-w-0 w-full"
    >
      <Splitter
        className="h-full min-h-0 min-w-0"
        styles={{
          panel: {
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          },
        }}
        onResize={(sizes) => {
          if (!resizable || sizes.length !== 2) return;
          if (sizes.some((value) => !Number.isFinite(value) || value < 0))
            return;
          const total = sizes[0] + sizes[1];
          if (total <= 0) return;
          const percentage = (sizes[side === "start" ? 0 : 1] / total) * 100;
          setSize(`${Math.min(panelMax, Math.max(min, percentage))}%`);
        }}
      >
        {side === "start"
          ? [sidePanel, contentPanel]
          : [contentPanel, sidePanel]}
      </Splitter>
    </div>
  );
}
