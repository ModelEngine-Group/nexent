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
import { useTranslation } from "react-i18next";
import { CheckIcon, CopyIcon } from "lucide-react";
import remarkGfm from "remark-gfm";

import { MermaidDiagram } from "./mermaid-diagram";

import { SyntaxHighlighter } from "./shiki-highlighter";
import { TooltipIconButton } from "./tooltip-icon-button";
import { cn } from "@/lib/utils";
import { remarkCite } from "./remark-cite";
import { CiteMarker } from "./cite-marker";
import { AuthenticatedImage } from "./authenticated-image";
import { useSourcesPanel } from "./sources-panel-context";
import { getCitationKey, getCitationLabel, type PanelSourceItem } from "./sources-panel";
import {
  searchSourcesRegistry,
  searchImagesRegistry,
  conversationSourcesRegistry,
  type SearchSource,
} from "../adapter/remote-chat-model-adapter";

/**
 * Looks up a SearchSource from either registry by citekey (e.g. "b1" or "1").
 * Checks searchSourcesRegistry first (streaming messages), then
 * conversationSourcesRegistry (historical messages).
 */
interface MessageSourcePart {
  type?: string;
  sourceType?: string;
  publishedDate?: string;
  url?: string;
  title?: string;
  text?: string;
  filename?: string;
  downloadUrl?: string;
  objectName?: string;
  citeIndex?: number | string;
  toolSign?: string;
  isImage?: boolean;
  imageKey?: string;
}

function normalizeCiteIndex(value: unknown): number | undefined {
  const citeIndex = typeof value === "number" ? value : Number(value);
  return Number.isFinite(citeIndex) ? citeIndex : undefined;
}

function resolveCiteSources(
  messageId: string | undefined,
  content: readonly MessageSourcePart[],
): SearchSource[] {
  const contentSources = content.flatMap((part) => {
    const citeIndex = normalizeCiteIndex(part.citeIndex);
    if (part.type !== "source" || citeIndex === undefined) {
      return [];
    }

    return [{
      citeIndex,
      url: part.url ?? "",
      title: part.title || part.filename || part.url || `Source ${citeIndex}`,
      text: part.text,
      sourceType: part.sourceType,
      publishedDate: part.publishedDate,
      filename: part.filename,
      downloadUrl: part.downloadUrl,
      objectName: part.objectName,
      toolSign: part.toolSign,
      isImage: part.isImage,
      imageKey: part.imageKey,
    }];
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

function findCiteSource(sources: SearchSource[], citekey: string): SearchSource | undefined {
  const normalizedKey = citekey.trim().toLowerCase();
  const exactMatch = sources.find((source) =>
    getCitationKey({ citeIndex: source.citeIndex, toolSign: source.toolSign }) === normalizedKey,
  );
  if (exactMatch) return exactMatch;

  // Older persisted messages can contain numeric-only markers without a
  // tool sign. Keep those conversations readable without weakening new
  // `a1` / `b1` matching.
  return /^\d+$/.test(normalizedKey)
    ? sources.find((source) => source.citeIndex === getCiteIndex(normalizedKey))
    : undefined;
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
    publishedDate: source.publishedDate,
    filename: source.filename,
    downloadUrl: source.downloadUrl,
    objectName: source.objectName,
    citeIndex: source.citeIndex,
    toolSign: source.toolSign,
    isImage: source.isImage,
  };
}

/**
 * A citation belongs to the Markdown section immediately before it, rather
 * than to the entire assistant response. A section can include a paragraph
 * followed by a table. A preceding citation or heading starts a new section,
 * so separately cited answer sections cannot affect each other.
 */
function getCitationScopeText(citationElement: HTMLElement | null): string {
  if (!citationElement) return "";

  const markdownRoot = citationElement.closest(".aui-md");
  if (!markdownRoot) {
    return citationElement.closest("p, li, td")?.textContent || "";
  }

  let currentBlock: HTMLElement = citationElement;
  while (
    currentBlock.parentElement &&
    currentBlock.parentElement !== markdownRoot
  ) {
    currentBlock = currentBlock.parentElement;
  }

  if (currentBlock.parentElement !== markdownRoot) {
    return citationElement.closest("p, li, td")?.textContent || "";
  }

  const blocks = Array.from(markdownRoot.children) as HTMLElement[];
  const currentBlockIndex = blocks.indexOf(currentBlock);
  if (currentBlockIndex < 0) {
    return citationElement.closest("p, li, td")?.textContent || "";
  }

  const citationsInCurrentBlock = Array.from(
    currentBlock.querySelectorAll<HTMLElement>("[data-citation-marker]"),
  );
  const citationIndex = citationsInCurrentBlock.indexOf(citationElement);
  const currentBlockRange = document.createRange();
  currentBlockRange.selectNodeContents(currentBlock);
  if (citationIndex > 0) {
    currentBlockRange.setStartAfter(citationsInCurrentBlock[citationIndex - 1]);
  }
  if (citationIndex >= 0) {
    currentBlockRange.setEndBefore(citationElement);
  }
  const currentBlockText = currentBlockRange.toString().trim();

  if (citationIndex > 0) return currentBlockText;

  let sectionStartIndex = 0;
  for (let index = currentBlockIndex - 1; index >= 0; index -= 1) {
    const block = blocks[index];
    const startsNewSection = /^H[1-6]$/.test(block.tagName);
    const hasEarlierCitation = Boolean(
      block.querySelector("[data-citation-marker]"),
    );
    if (startsNewSection || hasEarlierCitation) {
      sectionStartIndex = index + 1;
      break;
    }
  }

  return blocks
    .slice(sectionStartIndex, currentBlockIndex)
    .map((block) => block.textContent?.trim() || "")
    .filter(Boolean)
    .concat(currentBlockText ? [currentBlockText] : [])
    .join("\n");
}

/**
 * Custom cite component rendered for [[citekey]] markers in markdown.
 * Looks up the source from the registry and renders a CiteMarker with hover.
 */
const CiteComponent: FC<React.ComponentProps<"cite"> & { citekey?: string }> = ({
  citekey,
}) => {
  const messageId = useAuiState((s) => s.message.id as string | undefined);
  const content = useAuiState(
    (s) => s.message.content as readonly MessageSourcePart[],
  );
  const { open } = useSourcesPanel();
  const { t } = useTranslation();

  if (!citekey) return null;

  const messageSources = resolveCiteSources(messageId, content);
  const source = findCiteSource(messageSources, citekey);
  const citeIndex = getCiteIndex(citekey);
  const resolvedCiteIndex = source?.citeIndex ?? citeIndex ?? 0;
  const citationKey = source
    ? getCitationKey({ citeIndex: source.citeIndex, toolSign: source.toolSign })
    : citekey.trim().toLowerCase();
  const panelItems = messageSources.map(toPanelSource);
  const sources = panelItems.filter((item) => !item.isImage);
  const images = panelItems.filter((item) => item.isImage);

  return (
    <CiteMarker
      citekey={citekey}
      citeIndex={resolvedCiteIndex}
      label={source ? getCitationLabel(toPanelSource(source), {
        knowledgeBase: t("chat.sources.knowledgeBase"),
        web: t("chat.sources.web"),
        source: t("chat.sources.source"),
      }) : `${t("chat.sources.source")} ${resolvedCiteIndex}`}
      url={source?.url}
      title={source?.title ?? `Source ${resolvedCiteIndex}`}
      text={source?.text}
      loading={!source}
      onClick={
        source && messageId
          ? (citationElement) =>
              open({
                messageId,
                groupId: "citations",
                sources,
                images,
                selectedCitationKey: citationKey,
                citationContext: getCitationScopeText(citationElement),
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
      componentsByLanguage={{
        mermaid: {
          SyntaxHighlighter: MermaidDiagram,
        },
      }}
    />
  );
};

export const MarkdownText = memo(MarkdownTextImpl);

const CodeHeader: FC<CodeHeaderProps> = ({ language, code }) => {
  const { t } = useTranslation();
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
        tooltip={t("chat.thread.copy")}
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
      () => {},
    );
  };

  return { isCopied, copyToClipboard };
};

const MarkdownSyntaxHighlighter: FC<
  Omit<SyntaxHighlighterProps, "node">
> = (props) => <SyntaxHighlighter {...props} />;

const VerifiedMarkdownImage: FC<React.ComponentProps<"img">> = ({
  src,
  alt,
  ...props
}) => {
  const messageId = useAuiState((s) => s.message.id as string | undefined);
  const messageContent = useAuiState(
    (s) => s.message.content as readonly MessageSourcePart[],
  );
  const trustedImages = Array.isArray(messageContent)
    ? messageContent.filter(
        (part): part is MessageSourcePart & { url: string } =>
          part.type === "source" &&
          part.isImage === true &&
          typeof part.url === "string",
      )
    : [];
  const markerMatch = src?.match(
    /\/__aidp_image__\/([a-z]+\d+)(?:[?#].*)?$/i,
  );
  if (markerMatch) {
    const contentImage = trustedImages.find(
      (image) => image.imageKey === markerMatch[1],
    );
    const image = contentImage ?? (messageId
      ? searchImagesRegistry.get(messageId)?.get(markerMatch[1])
      : undefined);
    if (!image) return null;
    return (
      <figure className="my-4 overflow-hidden rounded-xl border bg-muted/20">
        <AuthenticatedImage
          src={image.url}
          alt={alt || image.title}
          className="max-h-[32rem] w-full cursor-zoom-in object-contain"
          preview
        />
      </figure>
    );
  }

  if (trustedImages.length > 0 || !src) {
    return null;
  }

  return <AuthenticatedImage src={src} alt={alt} {...props} />;
};

const defaultComponents = memoizeMarkdownComponents({
  SyntaxHighlighter: MarkdownSyntaxHighlighter,
  img: VerifiedMarkdownImage,
  h1: ({ className, ...props }) => (
    <h1
      className={cn(
        "aui-md-h1 mt-5 mb-2 scroll-m-20 text-xl font-semibold first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h2: ({ className, ...props }) => (
    <h2
      className={cn(
        "aui-md-h2 mt-5 mb-2 scroll-m-20 text-lg font-semibold first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h3: ({ className, ...props }) => (
    <h3
      className={cn(
        "aui-md-h3 mt-4 mb-1.5 scroll-m-20 text-base font-semibold first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h4: ({ className, ...props }) => (
    <h4
      className={cn(
        "aui-md-h4 mt-3.5 mb-1 scroll-m-20 text-base font-medium first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h5: ({ className, ...props }) => (
    <h5
      className={cn(
        "aui-md-h5 mt-3 mb-1 text-sm font-semibold first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h6: ({ className, ...props }) => (
    <h6
      className={cn(
        "aui-md-h6 mt-3 mb-1 text-sm font-medium first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  p: ({ className, ...props }) => (
    <p
      className={cn(
        "aui-md-p my-3 leading-relaxed first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  a: ({ className, ...props }) => (
    <a
      className={cn(
        "aui-md-a text-primary hover:text-primary/80 underline underline-offset-2",
        className,
      )}
      {...props}
    />
  ),
  blockquote: ({ className, ...props }) => (
    <blockquote
      className={cn(
        "aui-md-blockquote border-muted-foreground/30 text-muted-foreground my-3 border-s-2 ps-4",
        className,
      )}
      {...props}
    />
  ),
  ul: ({ className, ...props }) => (
    <ul
      className={cn(
        "aui-md-ul marker:text-muted-foreground my-3 ms-5 list-disc [&>li]:mt-1",
        className,
      )}
      {...props}
    />
  ),
  ol: ({ className, ...props }) => (
    <ol
      className={cn(
        "aui-md-ol marker:text-muted-foreground my-3 ms-5 list-decimal [&>li]:mt-1",
        className,
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
        className,
      )}
      {...props}
    />
  ),
  th: ({ className, ...props }) => (
    <th
      className={cn(
        "aui-md-th bg-muted px-3 py-1.5 text-start font-medium first:rounded-ss-lg last:rounded-se-lg [[align=center]]:text-center [[align=right]]:text-right",
        className,
      )}
      {...props}
    />
  ),
  td: ({ className, ...props }) => (
    <td
      className={cn(
        "aui-md-td border-muted-foreground/20 border-s border-b px-3 py-1.5 text-start last:border-e [[align=center]]:text-center [[align=right]]:text-right",
        className,
      )}
      {...props}
    />
  ),
  tr: ({ className, ...props }) => (
    <tr
      className={cn(
        "aui-md-tr m-0 border-b p-0 first:border-t [&:last-child>td:first-child]:rounded-es-lg [&:last-child>td:last-child]:rounded-ee-lg",
        className,
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
        className,
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
        (match) => match[1],
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
          className,
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
