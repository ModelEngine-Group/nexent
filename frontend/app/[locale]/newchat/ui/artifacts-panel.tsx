// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState, type FC } from "react";
import {
  DownloadIcon,
  EyeIcon,
  FolderOutputIcon,
  ImageIcon,
  MessageSquarePlusIcon,
  XIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { TooltipIconButton } from "./tooltip-icon-button";
import { FilePreviewDrawer } from "@/components/common/filePreviewDrawer";
import { storageService } from "@/services/storageService";
import { cn } from "@/lib/utils";
import log from "@/lib/logger";
import { useTranslation } from "react-i18next";
import { getFileIcon, triggerUrlDownload } from "./attachment";
import { useConversationArtifactsEntry } from "./conversation-artifacts-context";
import type {
  ConversationArtifact,
  ArtifactAttachmentLike,
} from "../utils/conversation-artifacts";

export interface ConversationArtifactsPanelProps {
  /** Whether the panel is currently mounted. */
  open: boolean;
  /** All agent-generated files collected across the conversation. */
  artifacts: ConversationArtifact[];
  onClose: () => void;
  /**
   * Adds an artifact back into the composer as an attachment ("add to chat").
   * When omitted the per-entry action is hidden, e.g. in read-only or shared
   * conversations where there is no composer to add to.
   */
  onAddToComposer?: (
    attachment: ArtifactAttachmentLike
  ) => Promise<void> | void;
  className?: string;
  /** Route previews into the conversation's document surface when provided. */
  onPreview?: (artifact: ConversationArtifact) => void;
}

/** Formats an artifact creation time without importing a date library. */
const formatGeneratedAt = (value: Date | undefined): string => {
  if (!value) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(value);
};

/**
 * Side panel listing every file the agent generated during the conversation.
 * Mirrors the SourcesPanel layout (right-hand column, header + scrollable
 * list) so the two panels read as one family. Each entry supports preview
 * through the shared {@link FilePreviewDrawer}, download, and re-attaching
 * the file to the composer when {@link ConversationArtifactsPanelProps.onAddToComposer}
 * is provided.
 */
export const ConversationArtifactsPanel: FC<
  ConversationArtifactsPanelProps
> = ({ open, artifacts, onClose, onAddToComposer, className, onPreview }) => {
  const { t } = useTranslation();
  const [previewing, setPreviewing] = useState<ArtifactAttachmentLike | null>(
    null
  );
  // Key of the entry currently being added to the composer; guards against
  // double-activating the fetch-and-attach flow while it is in flight.
  const [addingKey, setAddingKey] = useState<string | null>(null);

  if (!open) return null;

  const handleAddToComposer = async (
    key: string,
    attachment: ArtifactAttachmentLike
  ) => {
    if (!onAddToComposer || addingKey === key) return;
    setAddingKey(key);
    try {
      await onAddToComposer(attachment);
    } finally {
      setAddingKey(null);
    }
  };

  const handleDownload = async (attachment: ArtifactAttachmentLike) => {
    const name = attachment.name || "Generated file";
    try {
      if (attachment.download_url) {
        triggerUrlDownload(attachment.download_url, name);
      } else if (attachment.object_name) {
        await storageService.downloadFile(attachment.object_name, name);
      } else {
        const fallbackUrl =
          attachment.preview_url ||
          attachment.presigned_url ||
          attachment.url ||
          readAttachmentDataUrl(attachment);
        if (fallbackUrl) triggerUrlDownload(fallbackUrl, name);
      }
    } catch (error) {
      log.error("Failed to download conversation artifact:", error);
    }
  };

  return (
    <aside
      data-slot="artifacts-panel"
      className={cn(
        "flex h-full w-[380px] shrink-0 flex-col border-l border-slate-200 bg-white",
        className
      )}
      aria-label={t("chat.artifacts.title")}
    >
      <header className="flex items-center justify-between gap-2 border-b border-slate-200 px-4 py-2">
        <div className="flex min-w-0 flex-col">
          <h2 className="text-base font-medium text-foreground">
            {t("chat.artifacts.title")}
          </h2>
          <span className="text-xs text-muted-foreground">
            {t("chat.artifacts.total", { count: artifacts.length })}
          </span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("chat.artifacts.close")}
        >
          <XIcon className="size-4" />
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50/40 px-3 py-3">
        {artifacts.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {t("chat.artifacts.empty")}
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {artifacts.map((artifact) => {
              const attachment = artifact.attachment as ArtifactAttachmentLike;
              const name = attachment.name || "Generated file";
              const contentType = attachment.contentType;
              const generatedAt = formatGeneratedAt(artifact.createdAt);
              return (
                <li
                  key={artifact.key}
                  className="group rounded-lg border border-slate-200 bg-white px-3 py-2 transition-colors hover:border-blue-200 hover:bg-blue-50/40"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-300">
                      {isImageAttachment(name, contentType) ? (
                        <ImageIcon className="size-5" />
                      ) : (
                        (getFileIcon(name, contentType) ?? (
                          <FolderOutputIcon className="size-5" />
                        ))
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p
                        className="truncate text-sm font-medium text-foreground"
                        title={name}
                      >
                        {name}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {[
                          attachment.size !== undefined
                            ? formatArtifactSize(attachment.size)
                            : "",
                          generatedAt
                            ? t("chat.artifacts.generatedAt", {
                                time: generatedAt,
                              })
                            : "",
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <TooltipIconButton
                        tooltip={t("chat.artifacts.preview")}
                        type="button"
                        onClick={() =>
                          onPreview
                            ? onPreview(artifact)
                            : setPreviewing(attachment)
                        }
                      >
                        <EyeIcon className="size-4" />
                      </TooltipIconButton>
                      <TooltipIconButton
                        tooltip={t("chat.artifacts.download")}
                        type="button"
                        onClick={() => void handleDownload(attachment)}
                      >
                        <DownloadIcon className="size-4" />
                      </TooltipIconButton>
                      {onAddToComposer && (
                        <TooltipIconButton
                          tooltip={t("chat.artifacts.addToChat")}
                          type="button"
                          disabled={addingKey === artifact.key}
                          onClick={() =>
                            void handleAddToComposer(artifact.key, attachment)
                          }
                        >
                          <MessageSquarePlusIcon className="size-4" />
                        </TooltipIconButton>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {previewing && (
        <FilePreviewDrawer
          open={Boolean(previewing)}
          objectName={previewing.object_name ?? ""}
          fileName={previewing.name || "Generated file"}
          fileType={previewing.contentType}
          fileSize={previewing.size}
          previewUrl={previewing.preview_url ?? ""}
          downloadUrl={previewing.download_url}
          onClose={() => setPreviewing(null)}
        />
      )}
    </aside>
  );
};

/** Local size formatter matching the chat attachment cards. */
function formatArtifactSize(size: number): string {
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = size / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const precision = value >= 10 ? 0 : 1;
  return `${value.toFixed(precision)} ${units[unitIndex]}`;
}

/** Image detection aligned with the chat attachment cards. */
function isImageAttachment(name: string, contentType?: string): boolean {
  const extension = name.split(".").pop()?.toLowerCase() || "";
  return (
    contentType?.startsWith("image/") === true ||
    ["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico"].includes(
      extension
    )
  );
}

/** Reads the raw URL stashed in a file attachment content part. */
function readAttachmentDataUrl(
  attachment: ArtifactAttachmentLike
): string | undefined {
  const part = attachment.content?.[0] as { data?: string } | undefined;
  return part?.data;
}

export interface ConversationArtifactsButtonProps {
  /** Number of artifacts accumulated in the conversation. */
  count: number;
  onClick: () => void;
  className?: string;
}

/**
 * Compact pill entry that opens the {@link ConversationArtifactsPanel}.
 * Rendered once in the thread toolbar while the conversation has generated files.
 */
export const ConversationArtifactsButton: FC<
  ConversationArtifactsButtonProps
> = ({ count, onClick, className }) => {
  const { t } = useTranslation();
  if (count <= 0) return null;
  return (
    <div className={cn("flex justify-end", className)}>
      <button
        type="button"
        onClick={onClick}
        className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-muted-foreground shadow-sm transition-colors hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-blue-800 dark:hover:bg-blue-950 dark:hover:text-blue-300"
        aria-label={t("chat.artifacts.viewAll", { count })}
      >
        <FolderOutputIcon className="size-3.5" />
        {t("chat.artifacts.viewAll", { count })}
      </button>
    </div>
  );
};

export interface ConversationArtifactsToolbarEntryProps {
  className?: string;
}

/**
 * Persistent top-right entry outside the message viewport. Its toolbar only
 * takes up space after the current conversation has generated files. Reads
 * the conversation total rather than the latest message's attachments, so
 * later text-only turns do not hide it.
 */
export const ConversationArtifactsToolbarEntry: FC<
  ConversationArtifactsToolbarEntryProps
> = ({ className }) => {
  const entry = useConversationArtifactsEntry();
  if (!entry || entry.count <= 0) return null;
  return (
    <div
      data-slot="conversation-artifacts-toolbar"
      className={cn(
        "flex h-12 shrink-0 items-center justify-end px-4",
        className
      )}
    >
      <ConversationArtifactsButton count={entry.count} onClick={entry.open} />
    </div>
  );
};
