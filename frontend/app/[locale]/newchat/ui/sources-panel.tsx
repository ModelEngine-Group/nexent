"use client";

import { useEffect, useMemo, useRef, useState, type FC } from "react";
import {
  DatabaseIcon,
  DownloadIcon,
  ExternalLinkIcon,
  FileTextIcon,
  ImageIcon,
  LoaderCircleIcon,
  ServerIcon,
  XIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";
import {
  extractObjectNameFromUrl,
  fetchImageBlob,
  isLocalStorageObjectUrl,
  getLocalFilePreviewUrl,
  storageService,
} from "@/services/storageService";
import { AuthenticatedImage } from "./authenticated-image";

/**
 * Loose typing for the source items handled by the side panel. Matches the
 * shape of `SourcePartLike` used in `thread.tsx` so we can render each entry
 * consistently with the inline preview.
 */
export interface PanelSourceItem {
  sourceType?: "url" | "document";
  url?: string;
  title?: string;
  text?: string;
  publishedDate?: string;
  filename?: string;
  downloadUrl?: string;
  objectName?: string;
  isImage?: boolean;
  citeIndex?: number;
  toolSign?: string;
}

export function getCitationKey(item: Pick<PanelSourceItem, "citeIndex" | "toolSign">): string | undefined {
  if (!Number.isFinite(item.citeIndex)) return undefined;
  const index = item.citeIndex as number;
  const toolSign = item.toolSign?.trim().toLowerCase();
  return toolSign ? `${toolSign}${index}` : String(index);
}

export function getCitationLabel(
  item: Pick<PanelSourceItem, "citeIndex" | "toolSign" | "sourceType">,
  labels: { knowledgeBase: string; web: string; source: string },
): string {
  const index = item.citeIndex ?? 0;
  if (item.toolSign === "a" || item.sourceType === "document") {
    return `${labels.knowledgeBase} ${index}`;
  }
  if (["b", "c", "d", "e"].includes(item.toolSign ?? "")) {
    return `${labels.web} ${index}`;
  }
  return `${labels.source} ${index}`;
}

export interface SourcesPanelProps {
  /** Regular (non-image) sources rendered in the first tab. */
  sources: PanelSourceItem[];
  /** Image sources rendered in the second tab. */
  images: PanelSourceItem[];
  /** Whether the panel is currently open. Allows mount/unmount transitions. */
  open: boolean;
  selectedCitationKey?: string;
  citationContext?: string;
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
  sources,
  images,
  open,
  selectedCitationKey,
  citationContext,
  className,
  onClose,
}) => {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<PanelTab>(
    sources.length > 0 ? "sources" : "images",
  );

  useEffect(() => {
    if (!open) return;

    const selectedIsImage =
      selectedCitationKey !== undefined &&
      images.some((item) => getCitationKey(item) === selectedCitationKey);
    if (selectedIsImage) {
      setActiveTab("images");
    } else if (selectedCitationKey !== undefined || sources.length > 0) {
      setActiveTab("sources");
    } else if (images.length > 0) {
      setActiveTab("images");
    }
  }, [open, selectedCitationKey, sources.length, images.length]);

  if (!open) return null;

  const showSources = activeTab === "sources";
  const currentItems = showSources ? sources : images;

  return (
    <aside
      data-slot="sources-panel"
      className={cn(
        "flex h-full w-[380px] shrink-0 flex-col border-l border-slate-200 bg-white",
        className,
      )}
      aria-label={t("chat.sources.panel")}
    >
      <header className="flex items-center justify-between gap-2 border-b border-slate-200 px-4 py-2">
        <h2 className="text-sm font-semibold text-slate-800">{t("chatRightPanel.searchTitle")}</h2>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("chat.sources.close")}
        >
          <XIcon className="size-4" />
        </Button>
      </header>

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
          onClick={() => setActiveTab("sources")}
        />
        <TabButton
          label={t("chat.sources.images")}
          count={images.length}
          icon={<ImageIcon className="size-3.5" />}
          active={!showSources}
          onClick={() => setActiveTab("images")}
        />
      </div>

      <div className="flex-1 overflow-y-auto bg-slate-50/40 px-3 py-3">
        {currentItems.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {showSources ? t("chat.sources.noSources") : t("chat.sources.noImages")}
          </p>
        ) : showSources ? (
          <ul className="flex flex-col gap-2">
            {currentItems.map((item, index) => (
              <SourceListItem
                key={`${item.url ?? item.title ?? "source"}-${index}`}
                item={item}
                selected={getCitationKey(item) === selectedCitationKey}
                citationContext={citationContext}
              />
            ))}
          </ul>
        ) : (
          <ul className="grid grid-cols-2 gap-2">
            {currentItems.map((item, index) => (
              <li key={`${item.url ?? "image"}-${index}`}>
                <ImageListItem item={item} />
              </li>
            ))}
          </ul>
        )}
      </div>
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

const TabButton: FC<TabButtonProps> = ({ label, count, icon, active, onClick }) => {
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
          : "text-slate-700 hover:bg-slate-100 hover:text-slate-900",
      )}
    >
      {icon}
      <span>{label}</span>
      <span
        className={cn(
          "ml-1 inline-flex min-w-5 items-center justify-center rounded-full px-1.5 text-[10px]",
          active ? "bg-white/25 text-white" : "bg-slate-100 text-slate-500",
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

const escapeRegExp = (value: string) =>
  value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const extractHighlightTerms = (
  answerContext: string,
  sourceText: string,
): string[] => {
  if (!answerContext || !sourceText) return [];

  const sourceLower = sourceText.toLowerCase();
  const candidates = new Set<string>();
  const addIfPresent = (value: string) => {
    const term = value.trim();
    if (term.length >= 2 && sourceLower.includes(term.toLowerCase())) {
      candidates.add(term);
    }
  };

  for (const value of answerContext.match(
    /\b(?:\d{1,3}(?:\.\d{1,3}){3}|\d{2,}(?:[-:.]\d{1,4})*)\b/g,
  ) || []) {
    addIfPresent(value);
  }
  for (const value of answerContext.match(/[A-Za-z_][A-Za-z0-9_.\/-]{2,}/g) || []) {
    addIfPresent(value);
  }
  for (const phrase of answerContext.match(/[\u4e00-\u9fff]{3,}/g) || []) {
    for (let start = 0; start <= phrase.length - 3;) {
      let matched = "";
      for (let length = Math.min(12, phrase.length - start); length >= 3; length -= 1) {
        const candidate = phrase.slice(start, start + length);
        if (sourceText.includes(candidate)) {
          matched = candidate;
          break;
        }
      }
      if (matched) {
        candidates.add(matched);
        start += matched.length;
      } else {
        start += 1;
      }
    }
  }

  return Array.from(candidates)
    .sort((left, right) => right.length - left.length)
    .filter(
      (term, index, terms) =>
        !terms.slice(0, index).some((kept) => kept.includes(term)),
    )
    .slice(0, 8);
};

const HighlightedChunkText: FC<{ text: string; terms: string[] }> = ({ text, terms }) => {
  if (!terms.length) return <>{text}</>;

  const matcher = new RegExp(`(${terms.map(escapeRegExp).join("|")})`, "gi");
  return (
    <>
      {text.split(matcher).map((part, index) => {
        const isMatch = terms.some(
          (term) => part.toLowerCase() === term.toLowerCase(),
        );
        return isMatch ? (
          <mark key={`${part}-${index}`} className="rounded-sm bg-yellow-200 px-0.5 text-inherit">
            {part}
          </mark>
        ) : (
          <span key={`${part}-${index}`}>{part}</span>
        );
      })}
    </>
  );
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
        firstHighlight.offsetTop - textRef.current.offsetTop - 16,
      );
    }
  }, [highlighted, highlightTerms]);

  if (!text?.trim()) return null;

  if (highlighted) {
    return (
      <div className="mt-2">
        <p ref={textRef} className="max-h-52 overflow-y-auto whitespace-pre-wrap wrap-break-word pr-1 text-sm leading-6 text-gray-700">
          <HighlightedChunkText text={text} terms={highlightTerms} />
        </p>
      </div>
    );
  }

  return (
    <p className="mt-1 line-clamp-3 wrap-break-word text-sm leading-6 text-gray-700">
      {text}
    </p>
  );
};

const SourceFooter: FC<{ item: PanelSourceItem; sourceLabel: string }> = ({
  item,
  sourceLabel,
}) => {
  const fileLabel = item.filename || item.title || item.url || "";
  if (!fileLabel) return null;

  return (
    <div className="mt-2 flex min-w-0 flex-col gap-0.5 text-xs text-gray-500">
      <div className="flex min-w-0 items-center gap-1">
        {item.sourceType === "document" ? (
          <DatabaseIcon className="size-3 shrink-0" />
        ) : (
          <ExternalLinkIcon className="size-3 shrink-0" />
        )}
        <span className="truncate text-[#1677ff]">{fileLabel}</span>
      </div>
      <div className="flex min-w-0 items-center gap-1">
        <ServerIcon className="size-3 shrink-0" />
        <span className="truncate">{sourceLabel}</span>
      </div>
    </div>
  );
};

const SourceListItem: FC<{
  item: PanelSourceItem;
  selected: boolean;
  citationContext?: string;
}> = ({
  item,
  selected,
  citationContext,
}) => {
  const { t } = useTranslation();
  const itemRef = useRef<HTMLLIElement>(null);
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  useEffect(() => {
    if (selected) {
      itemRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [selected]);

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
    } catch {
      setDownloadError(t("chat.sources.downloadError"));
    } finally {
      setIsDownloading(false);
    }
  };

  const selectedClassName = selected
    ? "border-[#1677ff] bg-white shadow-none"
    : "border-slate-200 bg-white hover:border-slate-300";
  const highlightTerms = useMemo(
    () => selected ? extractHighlightTerms(citationContext || "", item.text || "") : [],
    [citationContext, item.text, selected],
  );
  const previewUrl = getLocalFilePreviewUrl(
    item.url,
    item.filename || item.title,
    item.objectName,
  );

  if (item.sourceType === "document") {
    return (
      <li ref={itemRef} className={cn("rounded-lg border p-3", selectedClassName)}>
        <div className="flex items-start gap-2 text-left text-sm">
          <button
            type="button"
            onClick={() => previewUrl && window.open(previewUrl, "_blank", "noopener,noreferrer")}
            disabled={!previewUrl}
            className="group flex min-w-0 flex-1 items-start gap-2 text-left transition-colors hover:text-primary disabled:cursor-default disabled:hover:text-foreground"
            aria-label={t("chat.sources.preview", {
              name: item.filename || item.title || t("chat.sources.document"),
            })}
          >
            <FileTextIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <div className="flex items-start gap-1.5">
                <span className="block min-w-0 flex-1 wrap-break-word text-base font-medium text-[#1677ff] group-hover:underline">{item.title || item.filename || t("chat.sources.document")}</span>
                {Number.isFinite(item.citeIndex) && (
                  <span className="inline-flex shrink-0 items-center justify-center rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-600">{item.citeIndex}</span>
                )}
              </div>
              {item.publishedDate && <span className="mt-1 block text-sm text-gray-500">{item.publishedDate}</span>}
              <SourceSummary text={item.text} highlighted={selected} highlightTerms={highlightTerms} />
              <SourceFooter item={item} sourceLabel="来源: Nexent" />
            </div>
          </button>
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
        </div>
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
      <li ref={itemRef} className={cn("rounded-lg border p-3", selectedClassName)}>
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-start gap-2 text-sm"
        >
          <FileTextIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <div className="flex items-start gap-1.5">
              <span className="block min-w-0 flex-1 truncate text-base font-medium text-[#1677ff] hover:underline">{displayTitle}</span>
              {Number.isFinite(item.citeIndex) && (
                <span className="inline-flex shrink-0 items-center justify-center rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-600">{item.citeIndex}</span>
              )}
            </div>
            {item.publishedDate ? (
              <span className="mt-1 block text-sm text-gray-500">{item.publishedDate}</span>
            ) : <span className="block truncate text-xs text-muted-foreground">{domain}</span>}
            <SourceSummary text={item.text} highlighted={selected} highlightTerms={highlightTerms} />
            <SourceFooter item={item} sourceLabel={`来源: ${domain}`} />
          </div>
        </a>
      </li>
    );
  }

  return (
    <li
      ref={itemRef}
      className={cn("rounded-lg border p-3 text-sm text-foreground", selectedClassName)}
    >
      <div className="flex items-start gap-1.5">
        <span className="min-w-0 flex-1 text-base font-medium text-[#1677ff]">{item.title || t("chat.sources.untitled")}</span>
        {Number.isFinite(item.citeIndex) && (
          <span className="inline-flex shrink-0 items-center justify-center rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-600">{item.citeIndex}</span>
        )}
      </div>
      {item.publishedDate && <span className="mt-1 block text-sm text-gray-500">{item.publishedDate}</span>}
      <SourceSummary text={item.text} highlighted={selected} highlightTerms={highlightTerms} />
      <SourceFooter item={item} sourceLabel="来源: Nexent" />
    </li>
  );
};

const ImageListItem: FC<{ item: PanelSourceItem }> = ({ item }) => {
  const imageUrl = item.url || "";
  const [resolvedUrl, setResolvedUrl] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);
  const usesBackendStream = isLocalStorageObjectUrl(imageUrl);

  useEffect(() => {
    if (!imageUrl || !usesBackendStream) {
      setResolvedUrl(null);
      setLoadError(false);
      return;
    }

    let cancelled = false;
    let objectUrl: string | null = null;
    setResolvedUrl(null);
    setLoadError(false);

    fetchImageBlob(imageUrl)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setResolvedUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [imageUrl, usesBackendStream]);

  if (!imageUrl) return null;
  if (usesBackendStream && !resolvedUrl && !loadError) {
    return (
      <div className="flex aspect-square items-center justify-center rounded-md border bg-muted/50">
        <LoaderCircleIcon className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="flex aspect-square items-center justify-center rounded-md border bg-muted/50 px-2 text-center text-xs text-muted-foreground">
        {item.title || imageUrl}
      </div>
    );
  }

  return (
    <div className="aui-global-search-image overflow-hidden rounded-md border bg-muted/50">
      <AuthenticatedImage
        src={resolvedUrl || imageUrl}
        alt={item.title || imageUrl}
        loading="lazy"
        preview
        className="aspect-square w-full object-cover"
      />
    </div>
  );
};
