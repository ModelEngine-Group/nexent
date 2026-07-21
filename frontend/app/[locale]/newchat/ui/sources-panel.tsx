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
import {
  extractObjectNameFromUrl,
  storageService,
} from "@/services/storageService";

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
  const [activeTab, setActiveTab] = useState<PanelTab>(
    sources.length > 0 ? "sources" : "images",
  );

  useEffect(() => {
    if (!open) return;

    if (selectedCiteIndex !== undefined || sources.length > 0) {
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
      aria-label="Sources panel"
    >
      <header className="flex items-center justify-between gap-2 border-b px-4 py-2">
        <h2 className="text-sm font-semibold text-foreground">Sources</h2>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label="Close sources panel"
        >
          <XIcon className="size-4" />
        </Button>
      </header>

      <div
        role="tablist"
        aria-label="Sources panel tabs"
        className="flex items-center gap-1 border-b px-2 py-2"
      >
        <TabButton
          label="Sources"
          count={sources.length}
          icon={<FileTextIcon className="size-3.5" />}
          active={showSources}
          onClick={() => setActiveTab("sources")}
        />
        <TabButton
          label="Images"
          count={images.length}
          icon={<ImageIcon className="size-3.5" />}
          active={!showSources}
          onClick={() => setActiveTab("images")}
        />
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {currentItems.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {showSources ? "No sources available." : "No images available."}
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
      await storageService.downloadFile(objectName, filename);
    } catch {
      setDownloadError("Download failed. Please try again.");
    } finally {
      setIsDownloading(false);
    }
  };

  const selectedClassName = selected
    ? "ring-2 ring-primary/50 ring-offset-2 ring-offset-background"
    : undefined;

  if (item.sourceType === "document") {
    return (
      <li ref={itemRef} className={cn("rounded-md", selectedClassName)}>
        <button
          type="button"
          onClick={handleDocumentDownload}
          disabled={isDownloading}
          className="group flex w-full items-start gap-2 rounded-md border bg-card px-3 py-2 text-left text-sm transition-colors hover:border-primary/40 hover:bg-accent/40 disabled:cursor-wait disabled:opacity-70"
          aria-label={`Download ${item.filename || item.title || "document"}`}
        >
          <FileTextIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <div className="flex items-start gap-2">
              <span className="min-w-0 flex-1 wrap-break-word font-medium text-foreground">
                {item.title || item.filename || "Document"}
              </span>
              {isDownloading ? (
                <LoaderCircleIcon className="mt-0.5 size-4 shrink-0 animate-spin text-muted-foreground" />
              ) : (
                <DownloadIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-foreground" />
              )}
            </div>
            <span className="block truncate text-xs text-muted-foreground">
              知识库
            </span>
            <SourceSummary text={item.text} />
            {downloadError && (
              <p className="mt-1 text-xs text-destructive">{downloadError}</p>
            )}
          </div>
        </button>
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
      <span className="font-medium">{item.title || "Untitled source"}</span>
      <SourceSummary text={item.text} />
    </li>
  );
};

const ImageListItem: FC<{ item: PanelSourceItem }> = ({ item }) => {
  const imageUrl = item.url || "";
  if (!imageUrl) return null;
  return (
    <a
      href={imageUrl}
      target="_blank"
      rel="noopener noreferrer"
      className="aui-global-search-image block overflow-hidden rounded-md border bg-muted/50"
      title={imageUrl}
    >
      <img
        src={imageUrl}
        alt={item.title || imageUrl}
        loading="lazy"
        className="aspect-square w-full object-cover"
      />
    </a>
  );
};
