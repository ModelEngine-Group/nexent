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
import { type FC, memo, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckIcon, CopyIcon } from "lucide-react";
import remarkGfm from "remark-gfm";
import { defaultUrlTransform, type UrlTransform } from "react-markdown";

import { MermaidDiagram } from "./mermaid-diagram";

import { SyntaxHighlighter } from "./shiki-highlighter";
import { TooltipIconButton } from "./tooltip-icon-button";
import { cn } from "@/lib/utils";
import { ENABLE_CITATION_CLICK_HIGHLIGHT } from "@/const/citation";
import { remarkCite } from "./remark-cite";
import { CiteMarker } from "./cite-marker";
import { AuthenticatedImage } from "./authenticated-image";
import {
  getLocalFileDownloadUrl,
  isLocalStorageObjectUrl,
} from "@/services/storageService";
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
  retrievalHighlightTerms?: string[];
}

const markdownUrlTransform: UrlTransform = (url) => {
  // React Markdown rejects non-web protocols by default. s3:// is Nexent's
  // permanent file-reference protocol and is converted by custom renderers.
  if (url.startsWith("s3://")) {
    return url;
  }
  return defaultUrlTransform(url);
};

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
      retrievalHighlightTerms: part.retrievalHighlightTerms,
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

const extractDomain = (url: string): string => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
};

function getSourceLabel(source: PanelSourceItem | undefined): string | undefined {
  if (!source) return undefined;
  if (source.sourceType === "document" || !source.url) {
    return "来源: Nexent";
  }
  return `来源: ${extractDomain(source.url)}`;
}

function buildCitationDisplayIndexMap(
  content: readonly MessageSourcePart[]
): Map<string, number> {
  const displayIndexMap = new Map<string, number>();

  for (const part of content) {
    if (part.type !== "text" || typeof part.text !== "string") continue;

    for (const match of part.text.matchAll(/\[\[([^\]]+)\]\]/g)) {
      const citekey = match[1];
      if (!displayIndexMap.has(citekey)) {
        displayIndexMap.set(citekey, displayIndexMap.size + 1);
      }
    }
  }

  return displayIndexMap;
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
    retrievalHighlightTerms: source.retrievalHighlightTerms,
  };
}

/**
 * A reference marker belongs to the one sentence immediately before it.
 * Consecutive markers, such as [[a1]][[b2]], share that sentence.  Newlines
 * and Markdown table cell separators also stop the scope so a marker never
 * expands to a following paragraph or table.
 */
function getSentenceStartOffset(text: string, endOffset: number): number {
  for (let offset = endOffset - 1; offset >= 0; offset -= 1) {
    const character = text[offset];
    if (character === "\n" || character === "|") return offset + 1;
    if ("。！？!?".includes(character)) return offset + 1;
    if (
      character === "." &&
      (offset + 1 === text.length || /\s|\[/.test(text[offset + 1]))
    ) {
      return offset + 1;
    }
  }
  return 0;
}

function getCitationScopeText(
  content: readonly MessageSourcePart[],
  citekey: string,
  citationElement: HTMLElement | null,
): string {
  const answerText = content
    .filter(
      (part) => part.type === "text" && typeof part.text === "string",
    )
    .map((part) => part.text)
    .join("\n");
  if (!answerText) return "";

  const normalizedKey = citekey.trim().toLowerCase();
  const markers = Array.from(answerText.matchAll(/\[\[([^\]]+)\]\]/g));
  const matchingMarkers = markers.filter(
    (marker) => marker[1].trim().toLowerCase() === normalizedKey,
  );
  if (!matchingMarkers.length) return "";

  const renderedMarkers = citationElement
    ? Array.from(
        citationElement
          .closest(".aui-md")
          ?.querySelectorAll<HTMLElement>("[data-citekey]") || [],
      ).filter((marker) => marker.dataset.citekey === normalizedKey)
    : [];
  const occurrence = Math.max(0, renderedMarkers.indexOf(citationElement!));
  const selectedMarker =
    matchingMarkers[Math.min(occurrence, matchingMarkers.length - 1)];
  const selectedMarkerIndex = markers.indexOf(selectedMarker);
  if (selectedMarker.index === undefined || selectedMarkerIndex < 0) return "";

  let groupStart = selectedMarkerIndex;
  while (
    groupStart > 0 &&
    !answerText
      .slice(
        (markers[groupStart - 1].index || 0) + markers[groupStart - 1][0].length,
        markers[groupStart].index,
      )
      .trim()
  ) {
    groupStart -= 1;
  }
  let groupEnd = selectedMarkerIndex;
  while (
    groupEnd < markers.length - 1 &&
    !answerText
      .slice(
        (markers[groupEnd].index || 0) + markers[groupEnd][0].length,
        markers[groupEnd + 1].index,
      )
      .trim()
  ) {
    groupEnd += 1;
  }

  const groupStartOffset = markers[groupStart].index || 0;
  const scopeStart = getSentenceStartOffset(answerText, groupStartOffset);
  return answerText
    .slice(scopeStart, groupStartOffset)
    .replace(/\[\[[^\]]+\]\]/g, "")
    .trim();
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
  const { t } = useTranslation();

  if (!citekey) return null;

  const messageSources = resolveCiteSources(messageId, content);
  const source = findCiteSource(messageSources, citekey);
  const panelSource = source ? toPanelSource(source) : undefined;
  const citeIndex = getCiteIndex(citekey);
  const sourceIndex = source?.citeIndex ?? citeIndex ?? 0;
  const citationKey = source
    ? getCitationKey({ citeIndex: source.citeIndex, toolSign: source.toolSign })
    : citekey.trim().toLowerCase();
  const citationDisplayIndexMap = buildCitationDisplayIndexMap(content);
  const displayIndex = citationDisplayIndexMap.get(citekey) ?? sourceIndex;
  const panelItems = messageSources.map(toPanelSource);
  const sources = panelItems.filter((item) => !item.isImage);
  const images = panelItems.filter((item) => item.isImage);

  return (
    <CiteMarker
      citekey={citekey}
      displayIndex={displayIndex}
      sourceIndex={sourceIndex}
      label={source ? getCitationLabel(toPanelSource(source), {
        knowledgeBase: t("chat.sources.knowledgeBase"),
        web: t("chat.sources.web"),
        source: t("chat.sources.source"),
      }) : `${t("chat.sources.source")} ${displayIndex}`}
      title={source?.title ?? `Source ${displayIndex}`}
      text={panelSource?.text}
      filename={panelSource?.filename}
      url={panelSource?.url}
      sourceType={panelSource?.sourceType}
      sourceLabel={getSourceLabel(panelSource)}
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
                // The flag only gates sentence-level highlight terms; the
                // panel still selects and scrolls to the source card.
                citationContext: ENABLE_CITATION_CLICK_HIGHLIGHT
                  ? getCitationScopeText(content, citekey, citationElement)
                  : undefined,
              })
          : undefined
      }
    />
  );
};

// Wrapper component that safely renders MarkdownTextPrimitive
// Guards against rendering for non-text parts or when text is not a valid string
const MarkdownTextImpl = () => {
  const messageId = useAuiState((s) => s.message.id as string | undefined);
  const content = useAuiState(
    (s) => s.message.content as readonly MessageSourcePart[]
  );
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
  const citationDisplayIndexMap = useMemo(
    () => buildCitationDisplayIndexMap(content),
    [content]
  );
  const citationIndexMapAttribute = useMemo(
    () => JSON.stringify(Object.fromEntries(citationDisplayIndexMap)),
    [citationDisplayIndexMap]
  );

  useEffect(() => {
    if (citationDisplayIndexMap.size === 0) return;

    console.info("[Nexent] Citation display index mapping", {
      messageId,
      citationIndexMap: Object.fromEntries(citationDisplayIndexMap),
    });
  }, [citationDisplayIndexMap, messageId]);

  if (!isValidTextPart) {
    return null;
  }

  return (
    <div data-citation-index-map={citationIndexMapAttribute}>
      <MarkdownTextPrimitive
        remarkPlugins={[remarkGfm, remarkCite]}
        urlTransform={markdownUrlTransform}
        className="aui-md"
        components={defaultComponents}
        componentsByLanguage={{
          mermaid: {
            SyntaxHighlighter: MermaidDiagram,
          },
        }}
      />
    </div>
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
      () => {}
    );
  };

  return { isCopied, copyToClipboard };
};

const MarkdownSyntaxHighlighter: FC<Omit<SyntaxHighlighterProps, "node">> = (
  props
) => <SyntaxHighlighter {...props} />;

const VerifiedMarkdownImage: FC<React.ComponentProps<"img">> = ({
  src,
  alt,
  ...props
}) => {
  const messageId = useAuiState((s) => s.message.id as string | undefined);
  const messageContent = useAuiState(
    (s) => s.message.content as readonly MessageSourcePart[]
  );
  const trustedImages = Array.isArray(messageContent)
    ? messageContent.filter(
        (part): part is MessageSourcePart & { url: string } =>
          part.type === "source" &&
          part.isImage === true &&
          typeof part.url === "string"
      )
    : [];
  const markerMatch = src?.match(/\/__aidp_image__\/([a-z]+\d+)(?:[?#].*)?$/i);
  if (markerMatch) {
    const contentImage = trustedImages.find(
      (image) => image.imageKey === markerMatch[1]
    );
    const image =
      contentImage ??
      (messageId
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

  // Local knowledge-base and web-search images use their real URL in the
  // answer markdown instead of an AIDP marker. Public URLs must also arrive
  // through PICTURE_WEB. Local storage URLs can be resolved directly because
  // the authenticated file endpoint performs its own access check; this also
  // covers relevant S3 images that were omitted by optional image filtering.
  const trustedImage = src
    ? trustedImages.find((image) => image.url === src)
    : undefined;
  const verifiedImageUrl =
    trustedImage?.url ||
    (src && isLocalStorageObjectUrl(src) ? src : undefined);
  if (verifiedImageUrl) {
    return (
      <figure className="my-4 overflow-hidden rounded-xl border bg-muted/20">
        <AuthenticatedImage
          src={verifiedImageUrl}
          alt={alt || trustedImage?.title}
          className="max-h-[32rem] w-full cursor-zoom-in object-contain"
          preview
          proxy={Boolean(trustedImage)}
        />
      </figure>
    );
  }

  if (trustedImages.length > 0 || !src) {
    return null;
  }

  return <AuthenticatedImage src={src} alt={alt} {...props} />;
};

const PermanentFileLink: FC<React.ComponentProps<"a">> = ({
  href,
  className,
  ...props
}) => {
  const resolvedHref = getLocalFileDownloadUrl(href) || href;
  return (
    <a
      href={resolvedHref}
      className={cn(
        "aui-md-a text-primary hover:text-primary/80 underline underline-offset-2",
        className
      )}
      {...props}
    />
  );
};

const defaultComponents = memoizeMarkdownComponents({
  SyntaxHighlighter: MarkdownSyntaxHighlighter,
  img: VerifiedMarkdownImage,
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
  a: PermanentFileLink,
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
