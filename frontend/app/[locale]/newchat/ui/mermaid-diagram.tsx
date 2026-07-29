"use client";

import { useAuiState } from "@assistant-ui/react";
import type { SyntaxHighlighterProps } from "@assistant-ui/react-markdown";
import mermaid from "mermaid";
import { type FC, memo, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

export type MermaidDiagramProps = SyntaxHighlighterProps & {
  className?: string;
};

let diagramId = 0;

const MermaidDiagramImpl: FC<MermaidDiagramProps> = ({
  code,
  className,
  node: _node,
  components: _components,
  language: _language,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const idRef = useRef(`mermaid-diagram-${diagramId++}`);
  const [error, setError] = useState<Error | null>(null);
  const isComplete = useAuiState(
    (state) => state.optional.part?.status.type !== "running",
  );

  useEffect(() => {
    if (!isComplete || !containerRef.current) return;

    let isCurrent = true;
    setError(null);
    containerRef.current.replaceChildren();

    mermaid
      .render(idRef.current, code.trim())
      .then(({ svg, bindFunctions }) => {
        if (!isCurrent || !containerRef.current) return;
        containerRef.current.innerHTML = svg;
        bindFunctions?.(containerRef.current);
      })
      .catch((renderError: unknown) => {
        if (!isCurrent) return;
        setError(
          renderError instanceof Error
            ? renderError
            : new Error("Mermaid diagram could not be rendered"),
        );
      });

    return () => {
      isCurrent = false;
    };
  }, [code, isComplete]);

  if (!isComplete) {
    return (
      <div
        aria-label="Rendering diagram"
        className={cn(
          "aui-mermaid-skeleton bg-muted h-32 animate-pulse rounded-b-lg",
          className,
        )}
      />
    );
  }

  if (error) {
    return (
      <div className={cn("aui-mermaid-fallback bg-muted/75 rounded-b-lg", className)}>
        <pre className="overflow-x-auto p-3.5 text-[13px] leading-relaxed">
          <code>{code.trim()}</code>
        </pre>
        <p className="border-border/50 border-t px-3.5 py-2 text-xs text-muted-foreground">
          Mermaid diagram could not be rendered.
        </p>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={cn(
        "aui-mermaid-diagram bg-muted overflow-x-auto rounded-b-lg p-2 [&_svg]:mx-auto",
        className,
      )}
    />
  );
};

const MermaidDiagram = memo(MermaidDiagramImpl);

MermaidDiagram.displayName = "MermaidDiagram";

export { MermaidDiagram };
