"use client";

import { useEffect, useRef, useState, type FC } from "react";
import {
  DownloadIcon,
  FileTextIcon,
  ImageIcon,
  LoaderCircleIcon,
  XIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";
import {
  extractObjectNameFromUrl,
  fetchImageBlob,
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
  filename?: string;
  downloadUrl?: string;
  objectName?: string;
  isImage?: boolean;
  citeIndex?: number;
}

export interface SourcesPanelProps {
  /** Regular (non-image) sources rendered in the first tab. */
  sources: PanelSourceItem[];
  /** Image sources rendered in the second tab. */
  images: PanelSourceItem[];
  /** Whether the panel is currently open. Allows mount/unmount transitions. */
  open: boolean;
  selectedCiteIndex?: number;
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
  selectedCiteIndex,
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
      selectedCiteIndex !== undefined &&
      images.some((item) => item.citeIndex === selectedCiteIndex);
    if (selectedIsImage) {
      setActiveTab("images");
    } else if (selectedCiteIndex !== undefined || sources.length > 0) {
      setActiveTab("sources");
    } else if (images.length > 0) {
      setActiveTab("images");
    }
  }, [open, selectedCiteIndex, sources.length, images.length]);

  if (!open) return null;

  const showSources = activeTab === "sources";
  const currentItems = showSources ? sources : images;

  return (
    <aside
      data-slot="sources-panel"
      className={cn(
        "flex h-full w-80 shrink-0 flex-col border-l bg-background",
        className,
      )}
      aria-label={t("chat.sources.panel")}
    >
      <header className="flex items-center justify-between gap-2 border-b px-4 py-2">
        <h2 className="text-sm font-semibold text-foreground">{t("chat.sources.title")}</h2>
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
        className="flex items-center gap-1 border-b px-2 py-2"
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

      <div className="flex-1 overflow-y-auto px-3 py-3">
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
                selected={item.citeIndex === selectedCiteIndex}
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
          ? "bg-primary/10 text-primary"
          : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
      )}
    >
      {icon}
      <span>{label}</span>
      <span
        className={cn(
          "ml-1 inline-flex min-w-5 items-center justify-center rounded-full px-1.5 text-[10px]",
          active ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
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

const SourceSummary: FC<{ text?: string }> = ({ text }) => {
  if (!text?.trim()) return null;

  return (
    <p className="mt-1 line-clamp-4 wrap-break-word text-xs leading-5 text-muted-foreground">
      {text}
    </p>
  );
};

const SourceListItem: FC<{ item: PanelSourceItem; selected: boolean }> = ({
  item,
  selected,
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
    ? "ring-2 ring-primary/50 ring-offset-2 ring-offset-background"
    : undefined;
  const previewUrl = getLocalFilePreviewUrl(
    item.url,
    item.filename || item.title,
    item.objectName,
  );

  if (item.sourceType === "document") {
    return (
      <li ref={itemRef} className={cn("rounded-md", selectedClassName)}>
        <div className="flex items-start gap-2 rounded-md border bg-card px-3 py-2 text-left text-sm">
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
              <span className="block wrap-break-word font-medium text-foreground">
                {item.title || item.filename || t("chat.sources.document")}
              </span>
              <span className="block truncate text-xs text-muted-foreground">
                {t("chat.sources.knowledgeBase")}
              </span>
              <SourceSummary text={item.text} />
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
          <p className="px-3 pb-2 text-xs text-destructive">{downloadError}</p>
        )}
      </li>
    );
  }

  if (item.url) {
    const domain = extractDomain(item.url);
    const displayTitle = item.title || domain;
    return (
      <li ref={itemRef} className={cn("rounded-md", selectedClassName)}>
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-start gap-2 rounded-md border bg-card px-3 py-2 text-sm transition-colors hover:border-primary/40 hover:bg-accent/40"
        >
          <FileTextIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <span className="block truncate font-medium text-foreground">
              {displayTitle}
            </span>
            <span className="block truncate text-xs text-muted-foreground">
              {domain}
            </span>
            <SourceSummary text={item.text} />
          </div>
        </a>
      </li>
    );
  }

  return (
    <li
      ref={itemRef}
      className={cn(
        "rounded-md border bg-card px-3 py-2 text-sm text-foreground",
        selectedClassName,
      )}
    >
      <span className="font-medium">{item.title || t("chat.sources.untitled")}</span>
      <SourceSummary text={item.text} />
    </li>
  );
};

const isLocalStorageUrl = (url: string): boolean => {
  return url.startsWith("s3://") || !/^https?:\/\//i.test(url);
};

const ImageListItem: FC<{ item: PanelSourceItem }> = ({ item }) => {
  const imageUrl = item.url || "";
  const [resolvedUrl, setResolvedUrl] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);
  const usesBackendStream = Boolean(imageUrl) && isLocalStorageUrl(imageUrl);

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
