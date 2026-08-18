"use client";

import { memo, useRef } from "react";
import {
  DatabaseIcon,
  ExternalLinkIcon,
  FileTextIcon,
  ServerIcon,
} from "lucide-react";
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
  /** Retrieval chunk text shown inside the hover card. */
  text?: string;
  filename?: string;
  url?: string;
  sourceType?: "document" | "url";
  /** Human-readable origin line, e.g. "来源: Nexent" or "来源: example.com". */
  sourceLabel?: string;
  onClick?: (citationElement: HTMLButtonElement | null) => void;
  loading?: boolean;
  className?: string;
}

const CiteMarkerImpl = ({
  citekey,
  citeIndex,
  label,
  title,
  text,
  filename,
  url,
  sourceType,
  sourceLabel,
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
            disabled={loading}
            aria-label={
              loading
                ? `${label} is loading`
                : `Open ${label}: ${title}`
            }
            className={cn(
              "mx-1 inline-flex size-[18px] items-center justify-center rounded-full bg-sky-100 p-0 align-middle text-[11px] font-medium leading-none text-sky-700 transition-colors",
              loading
                ? "cursor-wait opacity-70"
                : onClick
                  ? "cursor-pointer hover:bg-sky-200 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                  : "cursor-default focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none",
              className,
            )}
          >
            {citeIndex}
          </button>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          className="w-96 max-w-[24rem] px-3 py-2 text-left text-sm"
        >
          {loading ? (
            <span className="block truncate font-medium text-popover-foreground">
              Source details are loading
            </span>
          ) : (
            <div className="flex items-start gap-2">
              <FileTextIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="flex items-start gap-1.5">
                  <span className="block min-w-0 flex-1 wrap-break-word text-sm font-medium text-[#1677ff]">
                    {title}
                  </span>
                  <span className="inline-flex shrink-0 items-center justify-center rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-600">
                    {citeIndex}
                  </span>
                </div>
                {text?.trim() ? (
                  <p className="mt-1 line-clamp-4 wrap-break-word whitespace-pre-wrap text-xs leading-5 text-gray-600">
                    {text}
                  </p>
                ) : null}
                <div className="mt-1.5 flex min-w-0 flex-col gap-0.5 text-xs text-gray-500">
                  <div className="flex min-w-0 items-center gap-1">
                    {sourceType === "document" ? (
                      <DatabaseIcon className="size-3 shrink-0" />
                    ) : (
                      <ExternalLinkIcon className="size-3 shrink-0" />
                    )}
                    <span className="truncate text-[#1677ff]">
                      {filename || title || url || ""}
                    </span>
                  </div>
                  {sourceLabel ? (
                    <div className="flex min-w-0 items-center gap-1">
                      <ServerIcon className="size-3 shrink-0" />
                      <span className="truncate">{sourceLabel}</span>
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

export const CiteMarker = memo(CiteMarkerImpl);
