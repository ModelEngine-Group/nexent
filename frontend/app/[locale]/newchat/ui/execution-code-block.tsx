"use client";

import { TerminalIcon } from "lucide-react";

type ExecutionCodeBlockProps = {
  code?: unknown;
  language?: string;
};

export function ExecutionCodeBlock({
  code,
  language = "python",
}: ExecutionCodeBlockProps) {
  if (typeof code !== "string" || !code.trim()) return null;

  return (
    <section className="my-3 overflow-hidden rounded-xl border border-primary/20 bg-primary/[0.03]">
      <header className="flex items-center gap-2 border-b border-primary/15 bg-primary/[0.06] px-3.5 py-2 text-xs font-medium text-muted-foreground">
        <TerminalIcon className="size-3.5 text-primary" />
        <span>Executed code</span>
        <span className="ml-auto font-mono text-[11px] uppercase text-muted-foreground/80">
          {language}
        </span>
      </header>
      <pre className="overflow-x-auto p-3.5 font-mono text-[13px] leading-relaxed whitespace-pre-wrap">
        <code>{code}</code>
      </pre>
    </section>
  );
}
