// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FC,
  type ReactNode,
} from "react";
import {
  DatabaseIcon,
  DownloadIcon,
  ExternalLinkIcon,
  FileTextIcon,
  ImageIcon,
  LoaderCircleIcon,
  XIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { StandardPaginator } from "@/components/common/StandardPaginator";
import { cn } from "@/lib/utils";
import { getCitationKey } from "@/lib/citationDisplay";
import {
  CiteIndexBadge,
  HighlightedChunkText,
} from "@/components/common/highlightedSourceText";
import {
  extractHighlightTerms,
  mergeHighlightTerms,
} from "@/lib/citationHighlight";
import { useTranslation } from "react-i18next";
import {
  extractObjectNameFromUrl,
  fetchImageBlob,
  isLocalStorageObjectUrl,
  getLocalFilePreviewUrl,
  storageService,
} from "@/services/storageService";
import { AuthenticatedImage } from "./authenticated-image";
import type { SourceAttributes } from "@/types/source";
import { getSourceLabel, getSourceProvider, isAidpSource } from "@/lib/source";
import { SourceMetadata } from "@/components/common/sourceMetadata";
import log from "@/lib/logger";

export { getCitationKey } from "@/lib/citationDisplay";

/**
 * Loose typing for the source items handled by the side panel. Matches the
 * shape of `SourcePartLike` used in `thread.tsx` so we can render each entry
 * consistently with the inline preview.
 */
export interface PanelSourceItem extends SourceAttributes {
  sourceType?: "url" | "document";
  url?: string;
  title?: string;
  text?: string;
  publishedDate?: string;
  filename?: string;
  downloadUrl?: string;
  objectName?: string;
  isImage?: boolean;
  imageKey?: string;
  citeIndex?: number;
  /** Message-wide number shared with inline citations, including image hits. */
  displayIndex?: number;
  toolSign?: string;
  retrievalHighlightTerms?: string[];
}

export function getCitationLabel(
  item: Pick<
    PanelSourceItem,
    "citeIndex" | "displayIndex" | "toolSign" | "sourceType"
  >,
  labels: { knowledgeBase: string; web: string; source: string }
): string {
  const index = item.displayIndex ?? item.citeIndex ?? 0;
  if (item.toolSign === "a" || item.sourceType === "document") {
    return `${labels.knowledgeBase} ${index}`;
  }
  if (["b", "c", "d", "e"].includes(item.toolSign ?? "")) {
    return `${labels.web} ${index}`;
  }
  return `${labels.source} ${index}`;
}

export interface SourcesPanelProps {
  /** Scopes card state to its owning message, independently of click tokens. */
  messageId?: string;
  /** Regular (non-image) sources rendered in the first tab. */
  sources: PanelSourceItem[];
  /** Image sources rendered in the second tab. */
  images: PanelSourceItem[];
  /** Whether the panel is currently open. Allows mount/unmount transitions. */
  open: boolean;
  selectedCitationKey?: string;
  citationContext?: string;
  /** Changes for every citation click, including repeated clicks on one marker. */
  selectionToken?: object;
  className?: string;
  onClose: () => void;
}

type PanelTab = "sources" | "images";

/**
 * Side panel displayed to the right of the conversation thread. Hosts two tabs
 * (regular sources and image sources) so users can inspect the entire list
 * behind the inline summary button without cluttering the chat stream.
 */
export const SourcesPanel: FC<SourcesPanelProps> = ({
  messageId,
  sources,
  images,
  open,
  selectedCitationKey,
  citationContext,
  selectionToken,
  className,
  onClose,
}) => {
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const requested = useMemo(() => {
    const imageIndex =
      selectedCitationKey === undefined
        ? -1
        : images.findIndex(
            (item) => getCitationKey(item) === selectedCitationKey
          );
    const tab: PanelTab =
      imageIndex >= 0 || (!sources.length && images.length)
        ? "images"
        : "sources";
    const index =
      imageIndex >= 0
        ? imageIndex
        : sources.findIndex(
            (item) => getCitationKey(item) === selectedCitationKey
          );
    return { tab, page: Math.floor(Math.max(0, index) / 20) + 1 };
  }, [sources, images, selectedCitationKey]);
  const [navigation, setNavigation] = useState<{
    messageId?: string;
    token?: object;
    key?: string;
    open: boolean;
    tab: PanelTab;
    page: number;
  } | null>(null);
  const manual =
    navigation?.messageId === messageId &&
    navigation?.token === selectionToken &&
    navigation?.key === selectedCitationKey &&
    navigation?.open === open
      ? navigation
      : null;
  const activeTab = manual?.tab ?? requested.tab;
  const total = activeTab === "sources" ? sources.length : images.length;
  const currentPage = Math.min(
    manual?.page ?? requested.page,
    Math.max(1, Math.ceil(total / 20))
  );
  const navigate = (tab: PanelTab, page: number) => {
    setNavigation({
      messageId,
      token: selectionToken,
      key: selectedCitationKey,
      open,
      tab,
      page,
    });
    scrollRef.current?.scrollTo?.({ top: 0 });
  };

  if (!open) return null;

  const showSources = activeTab === "sources";
  const currentItems = (showSources ? sources : images).slice(
    (currentPage - 1) * 20,
    currentPage * 20
  );
  const title = showSources
    ? t("chat.sources.referenceTitle", { count: sources.length })
    : t("chat.sources.imageTitle", { count: images.length });
  const itemKey = (item: PanelSourceItem, index: number) =>
    JSON.stringify([
      messageId,
      Number.isInteger(item.citeIndex) && item.citeIndex! > 0
        ? getCitationKey(item)
        : [
            item.imageKey ?? item.url ?? item.objectName ?? item.title,
            (currentPage - 1) * 20 + index,
          ],
    ]);

  return (
    <aside
      data-slot="sources-panel"
      data-source-page={currentPage}
      className={cn(
        "flex h-full w-[380px] shrink-0 flex-col border-l border-slate-200 bg-white",
        className
      )}
      aria-label={t("chat.sources.panel")}
    >
      <header className="flex items-center justify-between gap-2 border-b border-slate-200 px-4 py-2">
        <h2 className="text-base font-medium text-foreground">{title}</h2>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("chat.sources.close")}
        >
          <XIcon className="size-4" />
        </Button>
      </header>

      {images.length > 0 && (
        <div
          role="tablist"
          aria-label={t("chat.sources.tabs")}
          className="grid grid-cols-2 gap-0 border-b border-slate-200 px-3 py-2"
        >
          <TabButton
            label={t("chat.sources.sources")}
            count={sources.length}
            icon={<FileTextIcon className="size-3.5" />}
            active={showSources}
            onClick={() => navigate("sources", 1)}
          />
          <TabButton
            label={t("chat.sources.images")}
            count={images.length}
            icon={<ImageIcon className="size-3.5" />}
            active={!showSources}
            onClick={() => navigate("images", 1)}
          />
        </div>
      )}

      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto bg-slate-50/40 px-3 py-3"
      >
        {currentItems.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {showSources
              ? t("chat.sources.noSources")
              : t("chat.sources.noImages")}
          </p>
        ) : showSources ? (
          <ul className="flex flex-col gap-2">
            {currentItems.map((item, index) => (
              <SourceListItem
                key={itemKey(item, index)}
                item={item}
                selected={
                  selectedCitationKey !== undefined &&
                  getCitationKey(item) === selectedCitationKey
                }
                citationContext={
                  getCitationKey(item) === selectedCitationKey
                    ? citationContext
                    : undefined
                }
                selectionToken={
                  getCitationKey(item) === selectedCitationKey
                    ? selectionToken
                    : undefined
                }
              />
            ))}
          </ul>
        ) : (
          <ul className="grid grid-cols-2 gap-2">
            {currentItems.map((item, index) => (
              <li key={itemKey(item, index)}>
                <ImageListItem
                  item={item}
                  selected={
                    selectedCitationKey !== undefined &&
                    getCitationKey(item) === selectedCitationKey
                  }
                  selectionToken={
                    getCitationKey(item) === selectedCitationKey
                      ? selectionToken
                      : undefined
                  }
                />
              </li>
            ))}
          </ul>
        )}
      </div>
      {total > 20 && (
        <nav
          aria-label={t("chat.sources.pagination")}
          className="flex shrink-0 justify-center border-t border-slate-200 px-3 py-3"
        >
          <StandardPaginator
            size="small"
            current={currentPage}
            pageSize={20}
            total={total}
            showSizeChanger={false}
            onChange={(page) => navigate(activeTab, page)}
          />
        </nav>
      )}
    </aside>
  );
};

interface TabButtonProps {
  label: string;
  count: number;
  icon: React.ReactNode;
  active: boolean;
  onClick: () => void;
}

const TabButton: FC<TabButtonProps> = ({
  label,
  count,
  icon,
  active,
  onClick,
}) => {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
        active
          ? "bg-[#1677ff] text-white"
          : "text-slate-700 hover:bg-slate-100 hover:text-slate-900"
      )}
    >
      {icon}
      <span>{label}</span>
      <span
        className={cn(
          "ml-1 inline-flex min-w-5 items-center justify-center rounded-full px-1.5 text-[10px]",
          active ? "bg-white/25 text-white" : "bg-slate-100 text-slate-500"
        )}
      >
        {count}
      </span>
    </button>
  );
};

const extractDomain = (url: string): string => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
};

const SourceSummary: FC<{
  text?: string;
  highlighted?: boolean;
  highlightTerms?: string[];
}> = ({ text, highlighted = false, highlightTerms = [] }) => {
  const textRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (!highlighted || !highlightTerms.length || !textRef.current) return;
    const firstHighlight = textRef.current.querySelector("mark");
    if (firstHighlight) {
      textRef.current.scrollTop = Math.max(
        0,
        firstHighlight.offsetTop - textRef.current.offsetTop - 16
      );
    }
  }, [highlighted, highlightTerms]);

  if (!text?.trim()) return null;

  if (highlighted && highlightTerms.length > 0) {
    return (
      <div className="mt-2">
        <p
          ref={textRef}
          className="max-h-52 overflow-y-auto whitespace-pre-wrap wrap-break-word pr-1 text-sm leading-6 text-gray-700"
        >
          <HighlightedChunkText text={text} terms={highlightTerms} />
        </p>
      </div>
    );
  }

  return (
    <p className="mt-1 line-clamp-2 wrap-break-word text-sm leading-[19px] text-[#777]">
      {text}
    </p>
  );
};

const SourceFooter: FC<{ item: PanelSourceItem; sourceLabel: string }> = ({
  item,
  sourceLabel,
}) => {
  return (
    <div className="mt-2 flex min-w-0 text-xs text-gray-500">
      <div className="flex min-w-0 items-center gap-1">
        {getSourceProvider(item.searchType, item.toolSign) ||
        item.sourceType === "document" ? (
          <DatabaseIcon className="size-3 shrink-0" />
        ) : (
          <ExternalLinkIcon className="size-3 shrink-0" />
        )}
        <span className="truncate">{sourceLabel}</span>
      </div>
    </div>
  );
};

/**
 * Card content shared by all three source card variants (document, url,
 * fallback): title row with index badge, date line, summary, and footer.
 */
const SourceCardBody: FC<{
  title: ReactNode;
  dateFallback?: ReactNode;
  item: PanelSourceItem;
  selected: boolean;
  highlightTerms: string[];
}> = ({ title, dateFallback, item, selected, highlightTerms }) => (
  <>
    <div className="flex items-start gap-1.5">
      {title}
      <CiteIndexBadge
        index={item.displayIndex ?? item.citeIndex}
        className="inline-flex shrink-0 items-center justify-center"
      />
    </div>
    {item.publishedDate ? (
      <span className="mt-1 block text-sm text-gray-500">
        {item.publishedDate}
      </span>
    ) : (
      dateFallback
    )}
    <SourceSummary
      text={item.text}
      highlighted={selected}
      highlightTerms={highlightTerms}
    />
  </>
);

const SourceListItem = memo(function SourceListItem({
  item,
  selected,
  citationContext,
  selectionToken,
}: {
  item: PanelSourceItem;
  selected: boolean;
  citationContext?: string;
  selectionToken?: object;
}) {
  const { t } = useTranslation();
  const itemRef = useRef<HTMLLIElement>(null);
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const isAidp = isAidpSource(item);
  const sourceLabel = getSourceLabel(item, {
    knowledgeBase: t("chat.sources.knowledgeBase"),
    web: t("chat.sources.web"),
    document: t("chat.sources.document"),
    source: t("chat.sources.source"),
  });

  useEffect(() => {
    if (selected) {
      itemRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [selected, selectionToken]);

  const handleDocumentDownload = async () => {
    if (isDownloading) return;

    setIsDownloading(true);
    setDownloadError(null);
    try {
      const filename = item.filename || item.title || "download";
      if (item.downloadUrl) {
        const link = document.createElement("a");
        link.href = item.downloadUrl;
        link.download = filename;
        link.style.display = "none";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        return;
      }

      const objectName =
        item.objectName ||
        (item.url ? extractObjectNameFromUrl(item.url) : null) ||
        (item.filename
          ? item.filename.includes("/")
            ? item.filename
            : `attachments/${item.filename}`
          : null);
      if (!objectName) {
        throw new Error("Cannot determine the file location.");
      }
      await storageService.downloadFileWithAuth(objectName, filename);
    } catch (error) {
      log.error("Failed to download citation file", {
        searchType: item.searchType,
        error,
      });
      setDownloadError(t("chat.sources.downloadError"));
    } finally {
      setIsDownloading(false);
    }
  };

  const selectedClassName = selected
    ? "border-[#1677ff] bg-white shadow-none"
    : "border-slate-200 bg-white hover:border-slate-300";
  const retrievalHighlightTerms = useMemo(() => {
    if (!selected) return [];

    const sourceText = item.text || "";
    return (item.retrievalHighlightTerms || [])
      .map((term) => term.trim())
      .filter(
        (term, index, terms) =>
          term.length >= 2 &&
          sourceText.toLowerCase().includes(term.toLowerCase()) &&
          terms.indexOf(term) === index
      );
  }, [item.retrievalHighlightTerms, item.text, selected]);
  const highlightTerms = useMemo(
    () =>
      selected
        ? mergeHighlightTerms(
            retrievalHighlightTerms,
            extractHighlightTerms(citationContext || "", item.text || "")
          )
        : [],
    [citationContext, retrievalHighlightTerms, item.text, selected]
  );
  const previewUrl = isAidp
    ? undefined
    : getLocalFilePreviewUrl(
        item.url,
        item.filename || item.title,
        item.objectName
      );

  if (item.sourceType === "document") {
    return (
      <li
        ref={itemRef}
        data-citation-key={getCitationKey(item)}
        data-citation-selected={selected ? "true" : undefined}
        className={cn("rounded-lg border p-3", selectedClassName)}
      >
        <div className="flex items-start gap-2 text-left text-sm">
          <button
            type="button"
            onClick={() =>
              previewUrl &&
              window.open(previewUrl, "_blank", "noopener,noreferrer")
            }
            disabled={!previewUrl}
            className="group flex min-w-0 flex-1 items-start gap-2 text-left transition-colors hover:text-primary disabled:cursor-default disabled:hover:text-foreground"
            aria-label={t("chat.sources.preview", {
              name: item.filename || item.title || t("chat.sources.document"),
            })}
          >
            <FileTextIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <SourceCardBody
                title={
                  <span className="block min-w-0 flex-1 wrap-break-word text-sm font-medium text-foreground group-hover:underline">
                    {item.title || item.filename || t("chat.sources.document")}
                  </span>
                }
                item={item}
                selected={selected}
                highlightTerms={highlightTerms}
              />
            </div>
          </button>
          {!isAidp && (
            <button
              type="button"
              onClick={() => void handleDocumentDownload()}
              disabled={isDownloading}
              className="shrink-0 rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground disabled:cursor-wait disabled:opacity-70"
              aria-label={t("chat.sources.download", {
                name: item.filename || item.title || t("chat.sources.document"),
              })}
            >
              {isDownloading ? (
                <LoaderCircleIcon className="size-4 animate-spin" />
              ) : (
                <DownloadIcon className="size-4" />
              )}
            </button>
          )}
        </div>
        <SourceMetadata metadata={item.sourceMetadata} />
        <SourceFooter item={item} sourceLabel={sourceLabel} />
        {downloadError && (
          <p className="pt-2 text-xs text-destructive">{downloadError}</p>
        )}
      </li>
    );
  }

  if (item.url) {
    const domain = extractDomain(item.url);
    const displayTitle = item.title || domain;
    return (
      <li
        ref={itemRef}
        data-citation-key={getCitationKey(item)}
        data-citation-selected={selected ? "true" : undefined}
        className={cn("rounded-lg border p-3", selectedClassName)}
      >
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-start gap-2 text-sm"
        >
          <FileTextIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <SourceCardBody
              title={
                <span className="block min-w-0 flex-1 truncate text-sm font-medium text-foreground hover:underline">
                  {displayTitle}
                </span>
              }
              dateFallback={
                <span className="block truncate text-xs text-muted-foreground">
                  {domain}
                </span>
              }
              item={item}
              selected={selected}
              highlightTerms={highlightTerms}
            />
          </div>
        </a>
        <SourceMetadata metadata={item.sourceMetadata} />
        <SourceFooter item={item} sourceLabel={sourceLabel} />
      </li>
    );
  }

  return (
    <li
      ref={itemRef}
      data-citation-key={getCitationKey(item)}
      data-citation-selected={selected ? "true" : undefined}
      className={cn(
        "rounded-lg border p-3 text-sm text-foreground",
        selectedClassName
      )}
    >
      <SourceCardBody
        title={
          <span className="min-w-0 flex-1 text-sm font-medium text-foreground">
            {item.title || t("chat.sources.untitled")}
          </span>
        }
        item={item}
        selected={selected}
        highlightTerms={highlightTerms}
      />
      <SourceMetadata metadata={item.sourceMetadata} />
      <SourceFooter item={item} sourceLabel={sourceLabel} />
    </li>
  );
});

const ImageListItem = memo(function ImageListItem({
  item,
  selected,
  selectionToken,
}: {
  item: PanelSourceItem;
  selected: boolean;
  selectionToken?: object;
}) {
  const { t } = useTranslation();
  const imageUrl = item.url || "";
  const itemRef = useRef<HTMLDivElement>(null);
  const [imageState, setImageState] = useState<{
    url: string;
    resolved?: string;
    error?: boolean;
  }>({ url: "" });
  const resolvedUrl =
    imageState.url === imageUrl ? imageState.resolved : undefined;
  const loadError = imageState.url === imageUrl && imageState.error;
  const usesBackendStream = isLocalStorageObjectUrl(imageUrl);

  useEffect(() => {
    if (!imageUrl || !usesBackendStream) return;

    let cancelled = false;
    let objectUrl: string | null = null;

    fetchImageBlob(imageUrl)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setImageState({ url: imageUrl, resolved: objectUrl });
      })
      .catch(() => {
        if (!cancelled) setImageState({ url: imageUrl, error: true });
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [imageUrl, usesBackendStream]);

  useEffect(() => {
    if (selected) {
      itemRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [selected, selectionToken]);

  if (!imageUrl) return null;
  const cardClassName = cn(
    "aui-global-search-image relative overflow-hidden rounded-md border bg-muted/50",
    selected && "border-[#1677ff] ring-1 ring-[#1677ff]"
  );
  if (usesBackendStream && !resolvedUrl && !loadError) {
    return (
      <div
        ref={itemRef}
        className={cn(
          cardClassName,
          "flex aspect-square items-center justify-center"
        )}
        data-citation-selected={selected ? "true" : undefined}
      >
        <LoaderCircleIcon className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (loadError) {
    return (
      <div
        ref={itemRef}
        className={cn(
          cardClassName,
          "flex aspect-square items-center justify-center px-2 text-center text-xs text-muted-foreground"
        )}
        data-citation-selected={selected ? "true" : undefined}
      >
        {item.title || imageUrl}
      </div>
    );
  }

  return (
    <div
      ref={itemRef}
      className={cardClassName}
      data-citation-selected={selected ? "true" : undefined}
    >
      <CiteIndexBadge
        index={item.displayIndex ?? item.citeIndex}
        className="absolute top-2 right-2 z-10"
      />
      <AuthenticatedImage
        src={resolvedUrl || imageUrl}
        alt={item.title || imageUrl}
        loading="lazy"
        preview
        proxy={!resolvedUrl}
        className="aspect-square w-full object-contain"
      />
      <div className="px-2 pb-2">
        {(item.filename || (item.title && item.title !== item.url)) && (
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {item.filename || item.title}
          </p>
        )}
        <SourceMetadata metadata={item.sourceMetadata} />
        <SourceFooter
          item={item}
          sourceLabel={getSourceLabel(item, {
            knowledgeBase: t("chat.sources.knowledgeBase"),
            web: t("chat.sources.web"),
            document: t("chat.sources.document"),
            source: t("chat.sources.source"),
          })}
        />
      </div>
    </div>
  );
});
