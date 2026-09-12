"use client";

import { useState } from "react";
import { ChevronDownIcon, LoaderIcon, TerminalIcon } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { SyntaxHighlighter } from "./shiki-highlighter";

type ExecutionCodeBlockProps = {
  code?: unknown;
  language?: string;
  isStreaming?: boolean;
};

export function ExecutionCodeBlock({
  code,
  language = "python",
  isStreaming = false,
}: ExecutionCodeBlockProps) {
  const [open, setOpen] = useState(true);
  if (!isStreaming && (typeof code !== "string" || !code.trim())) return null;

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="my-3 overflow-hidden rounded-xl border border-primary/20 bg-primary/[0.03]"
    >
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center gap-2 bg-primary/[0.06] px-3.5 py-2 text-left text-xs font-medium text-muted-foreground hover:bg-primary/[0.1]"
        >
          <TerminalIcon className="size-3.5 text-primary" />
          <span>{isStreaming ? "Generating code" : "Executed code"}</span>
          {isStreaming && <LoaderIcon className="size-3.5 animate-spin" />}
          <span className="ml-auto font-mono text-[11px] uppercase text-muted-foreground/80">
            {language}
          </span>
          <ChevronDownIcon
            className={cn(
              "size-3.5 transition-transform",
              !open && "-rotate-90"
            )}
          />
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        {typeof code === "string" && code ? (
          <SyntaxHighlighter code={code} language={language} />
        ) : (
          <div className="px-3.5 py-3 text-xs text-muted-foreground">
            Waiting for code…
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}
