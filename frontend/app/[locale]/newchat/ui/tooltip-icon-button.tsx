"use client";

import { type ComponentPropsWithRef, forwardRef, type ReactNode } from "react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type TooltipIconButtonProps = ComponentPropsWithRef<typeof Button> & {
  tooltip: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  tooltipDelayDuration?: number;
};

export const TooltipIconButton = forwardRef<
  HTMLButtonElement,
  TooltipIconButtonProps
>(({ children, tooltip, side = "bottom", tooltipDelayDuration, className, ...rest }, ref) => {
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
          {typeof tooltip === "string" && <span className="sr-only">{tooltip}</span>}
        </Button>
      </TooltipTrigger>
      <TooltipContent side={side}>{tooltip}</TooltipContent>
    </Tooltip>
  );
});

TooltipIconButton.displayName = "TooltipIconButton";
