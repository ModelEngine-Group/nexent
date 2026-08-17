"use client";

import { memo, useRef } from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export interface CiteMarkerProps {
  /** The raw citekey from the markdown, e.g. "b1", "a1", "1" */
  citekey: string;
  citeIndex: number;
  label: string;
  title: string;
  onClick?: (citationElement: HTMLButtonElement | null) => void;
  loading?: boolean;
  className?: string;
}

const CiteMarkerImpl = ({
  citekey,
  citeIndex,
  label,
  title,
  onClick,
  loading = false,
  className,
}: CiteMarkerProps) => {
  const markerRef = useRef<HTMLButtonElement>(null);

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            ref={markerRef}
            type="button"
            data-citation-marker
            data-citekey={citekey.trim().toLowerCase()}
            onClick={() => onClick?.(markerRef.current)}
            disabled={!onClick}
            aria-label={
              loading
                ? `${label} is loading`
                : `Open ${label}: ${title}`
            }
            className={cn(
              "mx-1 inline-flex size-[18px] items-center justify-center rounded-full bg-sky-100 p-0 align-middle text-[11px] font-medium leading-none text-sky-700 transition-colors",
              onClick
                ? "cursor-pointer hover:bg-sky-200 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                : "cursor-wait opacity-70",
              className,
            )}
          >
            {citeIndex}
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-sm px-3 py-1.5 text-sm">
          <span className="block truncate font-medium text-popover-foreground">
            {loading
                ? "Source details are loading"
                : title}
          </span>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

export const CiteMarker = memo(CiteMarkerImpl);
