"use client";

import { memo, type ReactNode, useEffect, useRef, useState } from "react";
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
import { CiteIndexBadge } from "@/components/common/highlightedSourceText";
import { cn } from "@/lib/utils";

export interface CiteMarkerProps {
  /** The raw citekey from the markdown, e.g. "b1", "a1", "1" */
  citekey: string;
  /** The index displayed to the user, ordered by first appearance. */
  displayIndex: number;
  /** The original index used to resolve the source data. */
  sourceIndex: number;
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

const allowedTags = new Set([
  "p",
  "br",
  "strong",
  "b",
  "em",
  "i",
  "table",
  "thead",
  "tbody",
  "tr",
  "th",
  "td",
]);

function renderSafeHtml(node: Node, key: string): ReactNode {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent;
  if (node.nodeType !== Node.ELEMENT_NODE) return null;

  const element = node as HTMLElement;
  const children = Array.from(element.childNodes).map((child, index) =>
    renderSafeHtml(child, `${key}-${index}`),
  );

  if (!allowedTags.has(element.tagName.toLowerCase())) return children;

  switch (element.tagName.toLowerCase()) {
    case "br":
      return <br key={key} />;
    case "p":
      return <p key={key} className="mb-2 last:mb-0">{children}</p>;
    case "strong":
    case "b":
      return <strong key={key}>{children}</strong>;
    case "em":
    case "i":
      return <em key={key}>{children}</em>;
    case "table":
      return (
        <div key={key} className="my-2 overflow-x-auto last:mb-0">
          <table className="w-full border-collapse text-left text-xs leading-5">{children}</table>
        </div>
      );
    case "thead":
      return <thead key={key} className="border-b border-border">{children}</thead>;
    case "tbody":
      return <tbody key={key}>{children}</tbody>;
    case "tr":
      return <tr key={key} className="border-b border-border/60 last:border-0">{children}</tr>;
    case "th":
      return <th key={key} className="px-2 py-1.5 align-top font-semibold">{children}</th>;
    case "td":
      return <td key={key} className="px-2 py-1.5 align-top">{children}</td>;
    default:
      return null;
  }
}

function CitationPreview({ text }: { text: string }) {
  const [nodes, setNodes] = useState<ReactNode>(text);

  useEffect(() => {
    const template = document.createElement("template");
    template.innerHTML = text;
    setNodes(
      Array.from(template.content.childNodes).map((node, index) =>
        renderSafeHtml(node, String(index)),
      ),
    );
  }, [text]);

  return <div className="max-h-64 overflow-y-auto text-xs leading-5 text-gray-600">{nodes}</div>;
}

const CiteMarkerImpl = ({
  citekey,
  displayIndex,
  sourceIndex,
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

  let stateClassName =
    "focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none";
  if (loading) {
    stateClassName = "cursor-wait opacity-70";
  } else if (onClick) {
    stateClassName += " cursor-pointer hover:bg-sky-200";
  } else {
    stateClassName += " cursor-default";
  }

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            ref={markerRef}
            type="button"
            data-citation-marker
            data-citekey={citekey.trim().toLowerCase()}
            data-citation-source-index={sourceIndex}
            data-citation-display-index={displayIndex}
            onClick={() => onClick?.(markerRef.current)}
            disabled={loading}
            aria-label={
              loading
                ? `${label} is loading`
                : `Open ${label}: ${title}`
            }
            className={cn(
              "mx-1 inline-flex size-[18px] items-center justify-center rounded-full bg-sky-100 p-0 align-middle text-[11px] font-medium leading-none text-sky-700 transition-colors",
              stateClassName,
              className,
            )}
          >
            {displayIndex}
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
                  <CiteIndexBadge
                    index={displayIndex}
                    className="inline-flex shrink-0 items-center justify-center"
                  />
                </div>
                {text?.trim() ? (
                  <div className="mt-1">
                    <CitationPreview text={text} />
                  </div>
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
