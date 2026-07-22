"use client";

import "@assistant-ui/react-markdown/styles/dot.css";

import {
  type CodeHeaderProps,
  MarkdownTextPrimitive,
  type SyntaxHighlighterProps,
  unstable_memoizeMarkdownComponents as memoizeMarkdownComponents,
  useIsMarkdownCodeBlock,
} from "@assistant-ui/react-markdown";
import { useAuiState } from "@assistant-ui/react";
import { type FC, memo, useState } from "react";
import { CheckIcon, CopyIcon } from "lucide-react";
import remarkGfm from "remark-gfm";

import { SyntaxHighlighter } from "./shiki-highlighter";
import { TooltipIconButton } from "./tooltip-icon-button";
import { cn } from "@/lib/utils";
import { remarkCite } from "./remark-cite";
import { CiteMarker } from "./cite-marker";
import { useSourcesPanel } from "./sources-panel-context";
import type { PanelSourceItem } from "./sources-panel";
import {
  searchSourcesRegistry,
  conversationSourcesRegistry,
  type SearchSource,
} from "../adapter/remote-chat-model-adapter";
import {
  nl2AgentComponentsByLanguage,
  preprocessNl2AgentFences,
} from "@/components/nl2agent/Nl2AgentFenceRenderer";

/**
 * Looks up a SearchSource from either registry by citekey (e.g. "b1" or "1").
 * Checks searchSourcesRegistry first (streaming messages), then
 * conversationSourcesRegistry (historical messages).
 */
interface MessageSourcePart {
  type?: string;
  sourceType?: string;
  url?: string;
  title?: string;
  text?: string;
  filename?: string;
  downloadUrl?: string;
  objectName?: string;
  citeIndex?: number | string;
  isImage?: boolean;
}

function normalizeCiteIndex(value: unknown): number | undefined {
  const citeIndex = typeof value === "number" ? value : Number(value);
  return Number.isFinite(citeIndex) ? citeIndex : undefined;
}

function resolveCiteSources(
  messageId: string | undefined,
  content: readonly MessageSourcePart[]
): SearchSource[] {
  const contentSources = content.flatMap((part) => {
    const citeIndex = normalizeCiteIndex(part.citeIndex);
    if (part.type !== "source" || part.isImage || citeIndex === undefined) {
      return [];
    }

    return [
      {
        citeIndex,
        url: part.url ?? "",
        title: part.title || part.filename || part.url || `Source ${citeIndex}`,
        text: part.text,
        sourceType: part.sourceType,
        filename: part.filename,
        downloadUrl: part.downloadUrl,
        objectName: part.objectName,
      },
    ];
  });

  if (contentSources.length > 0) return contentSources;
  if (!messageId) return [];

  return (
    searchSourcesRegistry.get(messageId) ??
    conversationSourcesRegistry.get(messageId) ??
    []
  );
}

function getCiteIndex(citekey: string): number | undefined {
  const numericPart = citekey.replace(/^[a-z]+/i, "");
  const citeIndex = Number.parseInt(numericPart, 10);
  return Number.isNaN(citeIndex) ? undefined : citeIndex;
}

function toPanelSource(source: SearchSource): PanelSourceItem {
  return {
    sourceType:
      source.sourceType === "file" || source.sourceType === "document"
        ? "document"
        : "url",
    url: source.url,
    title: source.title,
    text: source.text,
    filename: source.filename,
    downloadUrl: source.downloadUrl,
    objectName: source.objectName,
    citeIndex: source.citeIndex,
  };
}

/**
 * Custom cite component rendered for [[citekey]] markers in markdown.
 * Looks up the source from the registry and renders a CiteMarker with hover.
 */
const CiteComponent: FC<
  React.ComponentProps<"cite"> & { citekey?: string }
> = ({ citekey }) => {
  const messageId = useAuiState((s) => s.message.id as string | undefined);
  const content = useAuiState(
    (s) => s.message.content as readonly MessageSourcePart[]
  );
  const { open } = useSourcesPanel();

  if (!citekey) return null;

  const citeIndex = getCiteIndex(citekey);
  const messageSources = resolveCiteSources(messageId, content);
  const source = messageSources.find((item) => item.citeIndex === citeIndex);
  const resolvedCiteIndex = source?.citeIndex ?? citeIndex ?? 0;
  const sources = messageSources.map(toPanelSource);

  return (
    <CiteMarker
      citekey={citekey}
      citeIndex={resolvedCiteIndex}
      url={source?.url}
      title={source?.title ?? `Source ${resolvedCiteIndex}`}
      text={source?.text}
      loading={!source}
      onClick={
        source && messageId
          ? () =>
              open({
                messageId,
                groupId: "citations",
                sources,
                images: [],
                selectedCiteIndex: source.citeIndex,
              })
          : undefined
      }
    />
  );
};

// Wrapper component that safely renders MarkdownTextPrimitive
// Guards against rendering for non-text parts or when text is not a valid string
const MarkdownTextImpl = () => {
  // Check if we have a valid text part context using useAuiState
  const isValidTextPart = useAuiState((s) => {
    const part = s.part;
    return (
      part &&
      part.type === "text" &&
      typeof part.text === "string" &&
      part.text.length > 0
    );
  });

  if (!isValidTextPart) {
    return null;
  }

  return (
    <MarkdownTextPrimitive
      remarkPlugins={[remarkGfm, remarkCite]}
      className="aui-md"
      components={defaultComponents}
      componentsByLanguage={nl2AgentComponentsByLanguage}
      preprocess={preprocessNl2AgentFences}
    />
  );
};

export const MarkdownText = memo(MarkdownTextImpl);

const CodeHeader: FC<CodeHeaderProps> = ({ language, code }) => {
  const { isCopied, copyToClipboard } = useCopyToClipboard();
  const onCopy = () => {
    if (!code || isCopied) return;
    copyToClipboard(code);
  };

  return (
    <div className="aui-code-header-root border-border/50 bg-muted/50 mt-3 flex items-center justify-between rounded-t-xl border border-b-0 px-3.5 py-1.5 text-xs">
      <span className="aui-code-header-language text-muted-foreground font-medium lowercase">
        {language}
      </span>
      <TooltipIconButton
        tooltip="Copy"
        tooltipDelayDuration={0}
        className="size-6 p-1"
        onClick={onCopy}
      >
        {!isCopied && (
          <CopyIcon className="animate-in zoom-in-75 fade-in duration-150" />
        )}
        {isCopied && (
          <CheckIcon className="animate-in zoom-in-50 fade-in duration-200 ease-out" />
        )}
      </TooltipIconButton>
    </div>
  );
};

const useCopyToClipboard = ({
  copiedDuration = 3000,
}: {
  copiedDuration?: number;
} = {}) => {
  const [isCopied, setIsCopied] = useState<boolean>(false);

  const copyToClipboard = (value: string) => {
    if (!value || typeof navigator === "undefined" || !navigator.clipboard) {
      return;
    }

    navigator.clipboard.writeText(value).then(
      () => {
        setIsCopied(true);
        setTimeout(() => setIsCopied(false), copiedDuration);
      },
      () => {}
    );
  };

  return { isCopied, copyToClipboard };
};

const MarkdownSyntaxHighlighter: FC<Omit<SyntaxHighlighterProps, "node">> = (
  props
) => <SyntaxHighlighter {...props} />;

const defaultComponents = memoizeMarkdownComponents({
  SyntaxHighlighter: MarkdownSyntaxHighlighter,
  h1: ({ className, ...props }) => (
    <h1
      className={cn(
        "aui-md-h1 mt-5 mb-2 scroll-m-20 text-xl font-semibold first:mt-0 last:mb-0",
        className
      )}
      {...props}
    />
  ),
  h2: ({ className, ...props }) => (
    <h2
      className={cn(
        "aui-md-h2 mt-5 mb-2 scroll-m-20 text-lg font-semibold first:mt-0 last:mb-0",
        className
      )}
      {...props}
    />
  ),
  h3: ({ className, ...props }) => (
    <h3
      className={cn(
        "aui-md-h3 mt-4 mb-1.5 scroll-m-20 text-base font-semibold first:mt-0 last:mb-0",
        className
      )}
      {...props}
    />
  ),
  h4: ({ className, ...props }) => (
    <h4
      className={cn(
        "aui-md-h4 mt-3.5 mb-1 scroll-m-20 text-base font-medium first:mt-0 last:mb-0",
        className
      )}
      {...props}
    />
  ),
  h5: ({ className, ...props }) => (
    <h5
      className={cn(
        "aui-md-h5 mt-3 mb-1 text-sm font-semibold first:mt-0 last:mb-0",
        className
      )}
      {...props}
    />
  ),
  h6: ({ className, ...props }) => (
    <h6
      className={cn(
        "aui-md-h6 mt-3 mb-1 text-sm font-medium first:mt-0 last:mb-0",
        className
      )}
      {...props}
    />
  ),
  p: ({ className, ...props }) => (
    <p
      className={cn(
        "aui-md-p my-3 leading-relaxed first:mt-0 last:mb-0",
        className
      )}
      {...props}
    />
  ),
  a: ({ className, ...props }) => (
    <a
      className={cn(
        "aui-md-a text-primary hover:text-primary/80 underline underline-offset-2",
        className
      )}
      {...props}
    />
  ),
  blockquote: ({ className, ...props }) => (
    <blockquote
      className={cn(
        "aui-md-blockquote border-muted-foreground/30 text-muted-foreground my-3 border-s-2 ps-4",
        className
      )}
      {...props}
    />
  ),
  ul: ({ className, ...props }) => (
    <ul
      className={cn(
        "aui-md-ul marker:text-muted-foreground my-3 ms-5 list-disc [&>li]:mt-1",
        className
      )}
      {...props}
    />
  ),
  ol: ({ className, ...props }) => (
    <ol
      className={cn(
        "aui-md-ol marker:text-muted-foreground my-3 ms-5 list-decimal [&>li]:mt-1",
        className
      )}
      {...props}
    />
  ),
  hr: ({ className, ...props }) => (
    <hr
      className={cn("aui-md-hr border-muted-foreground/20 my-3", className)}
      {...props}
    />
  ),
  table: ({ className, ...props }) => (
    <table
      className={cn(
        "aui-md-table my-3 w-full border-separate border-spacing-0 overflow-y-auto",
        className
      )}
      {...props}
    />
  ),
  th: ({ className, ...props }) => (
    <th
      className={cn(
        "aui-md-th bg-muted px-3 py-1.5 text-start font-medium first:rounded-ss-lg last:rounded-se-lg [[align=center]]:text-center [[align=right]]:text-right",
        className
      )}
      {...props}
    />
  ),
  td: ({ className, ...props }) => (
    <td
      className={cn(
        "aui-md-td border-muted-foreground/20 border-s border-b px-3 py-1.5 text-start last:border-e [[align=center]]:text-center [[align=right]]:text-right",
        className
      )}
      {...props}
    />
  ),
  tr: ({ className, ...props }) => (
    <tr
      className={cn(
        "aui-md-tr m-0 border-b p-0 first:border-t [&:last-child>td:first-child]:rounded-es-lg [&:last-child>td:last-child]:rounded-ee-lg",
        className
      )}
      {...props}
    />
  ),
  li: ({ className, ...props }) => (
    <li className={cn("aui-md-li leading-relaxed", className)} {...props} />
  ),
  strong: ({ className, ...props }) => (
    <strong
      className={cn("aui-md-strong font-semibold", className)}
      {...props}
    />
  ),
  sup: ({ className, ...props }) => (
    <sup
      className={cn("aui-md-sup [&>a]:text-xs [&>a]:no-underline", className)}
      {...props}
    />
  ),
  pre: ({ className, ...props }) => (
    <pre
      className={cn(
        "aui-md-pre border-border/50 bg-muted/30 overflow-x-auto rounded-t-none rounded-b-xl border border-t-0 p-3.5 text-[13px] leading-relaxed",
        className
      )}
      {...props}
    />
  ),
  code: function Code({ className, children, ...props }) {
    const isCodeBlock = useIsMarkdownCodeBlock();
    const inlineValue = typeof children === "string" ? children.trim() : "";
    const isCiteSequence =
      !isCodeBlock && /^(?:\[\[[^\]]+\]\])+$/.test(inlineValue);

    if (isCiteSequence) {
      const citekeys = Array.from(
        inlineValue.matchAll(/\[\[([^\]]+)\]\]/g),
        (match) => match[1]
      );
      return (
        <>
          {citekeys.map((citekey, index) => (
            <CiteComponent key={`${citekey}-${index}`} citekey={citekey} />
          ))}
        </>
      );
    }

    return (
      <code
        className={cn(
          !isCodeBlock &&
            "aui-md-inline-code bg-muted rounded-md px-1.5 py-0.5 font-mono text-[0.85em]",
          className
        )}
        {...props}
      >
        {children}
      </code>
    );
  },
  CodeHeader,
  cite: CiteComponent,
});
export { defaultComponents };
