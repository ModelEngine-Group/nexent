"use client";

import {
  BranchPickerPrimitive,
  useAuiState,
} from "@assistant-ui/react";
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { type FC, type HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export interface BranchPickerProps extends HTMLAttributes<HTMLDivElement> {
  hideWhenSingleBranch?: boolean;
}

export const BranchPicker: FC<BranchPickerProps> = ({
  className,
  hideWhenSingleBranch = true,
  ...props
}) => {
  return (
    <BranchPickerPrimitive.Root
      hideWhenSingleBranch={hideWhenSingleBranch}
      className={cn(
        "aui-branch-picker-root text-muted-foreground inline-flex shrink-0 items-center gap-1 text-xs",
        className
      )}
      {...props}
    >
      <BranchPickerPrimitive.Previous
        className="hover:bg-accent flex size-6 shrink-0 items-center justify-center rounded-md disabled:opacity-30"
        aria-label="Previous branch"
      >
        <ChevronLeftIcon className="size-3.5" />
      </BranchPickerPrimitive.Previous>
      <span className="shrink-0 whitespace-nowrap tabular-nums">
        <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
      </span>
      <BranchPickerPrimitive.Next
        className="hover:bg-accent flex size-6 shrink-0 items-center justify-center rounded-md disabled:opacity-30"
        aria-label="Next branch"
      >
        <ChevronRightIcon className="size-3.5" />
      </BranchPickerPrimitive.Next>
    </BranchPickerPrimitive.Root>
  );
};

BranchPicker.displayName = "BranchPicker";

// Re-export the AUI state hook for consumers that want a lightweight count display.
export const useBranchCount = () =>
  useAuiState((s) => ({
    number: s.message.branchNumber,
    count: s.message.branchCount,
  }));
