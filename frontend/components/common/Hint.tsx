// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { cloneElement, type ReactElement, type ReactNode } from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/common/Tooltip";

/** Shared hint timing and keyboard behavior; content remains caller-owned. */
export interface HintProps {
  children: ReactElement<{ tabIndex?: number; disabled?: boolean }>;
  content: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  align?: "start" | "center" | "end";
}

export function Hint({
  children,
  content,
  side = "top",
  align = "center",
}: HintProps) {
  if (!content) return children;
  const trigger = children.props.disabled ? (
    <span className="inline-flex" tabIndex={0}>
      {children}
    </span>
  ) : typeof children.type === "string" &&
    !["button", "a", "input"].includes(children.type) ? (
    cloneElement(children, { tabIndex: children.props.tabIndex ?? 0 })
  ) : (
    children
  );
  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>{trigger}</TooltipTrigger>
        <TooltipContent side={side} align={align}>
          {content}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
