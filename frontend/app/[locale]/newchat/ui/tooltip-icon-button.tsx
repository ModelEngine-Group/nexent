// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { type ComponentPropsWithRef, forwardRef, type ReactNode } from "react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/common/Tooltip";
import { Button } from "@/components/common/Button";
import { cn } from "@/lib/utils";

export type TooltipIconButtonProps = ComponentPropsWithRef<typeof Button> & {
  tooltip: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  tooltipDelayDuration?: number;
};

export const TooltipIconButton = forwardRef<
  HTMLButtonElement,
  TooltipIconButtonProps
>(
  (
    {
      children,
      tooltip,
      side = "bottom",
      tooltipDelayDuration,
      className,
      ...rest
    },
    ref
  ) => {
    return (
      <Tooltip delayDuration={tooltipDelayDuration}>
        <TooltipTrigger asChild>
          <Button
            ref={ref}
            variant="ghost"
            size="icon"
            className={cn("size-9", className)}
            {...rest}
          >
            {children}
            {typeof tooltip === "string" && (
              <span className="sr-only">{tooltip}</span>
            )}
          </Button>
        </TooltipTrigger>
        <TooltipContent side={side}>{tooltip}</TooltipContent>
      </Tooltip>
    );
  }
);

TooltipIconButton.displayName = "TooltipIconButton";
