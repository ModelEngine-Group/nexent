"use client";

import { memo, type ReactNode, useEffect, useState } from "react";
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
  url?: string;
  title: string;
  text?: string;
  onClick?: () => void;
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

  return <div className="max-h-64 overflow-y-auto text-xs leading-5 text-muted-foreground">{nodes}</div>;
}

const CiteMarkerImpl = ({
  citekey,
  citeIndex,
  url,
  title,
  text,
  onClick,
  loading = false,
  className,
}: CiteMarkerProps) => {
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={onClick}
            disabled={!onClick}
            aria-label={
              loading
                ? `Source ${citeIndex} is loading`
                : `Open source ${citeIndex}: ${title}`
            }
            className={cn(
              "mx-0.5 inline-flex items-center justify-center rounded bg-primary/10 px-1 align-baseline font-normal leading-normal text-primary transition-colors",
              onClick
                ? "cursor-pointer hover:bg-primary/20 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                : "cursor-wait opacity-70",
              className,
            )}
          >
            [{citeIndex}]
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-sm px-3 py-2">
          <div className="flex flex-col gap-1.5">
            <span className="font-medium text-popover-foreground">{title}</span>
            {text?.trim() ? <CitationPreview text={text} /> : null}
            {url ? (
              <span className="truncate text-xs text-muted-foreground">{url}</span>
            ) : null}
            {loading ? (
              <span className="text-xs text-muted-foreground">
                Source details are loading
              </span>
            ) : null}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

export const CiteMarker = memo(CiteMarkerImpl);
