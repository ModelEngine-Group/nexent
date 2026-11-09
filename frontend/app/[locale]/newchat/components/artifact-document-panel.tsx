// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";
import { Download, FolderOutput, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FilePreviewDrawer } from "@/components/common/filePreviewDrawer";
import { API_ENDPOINTS } from "@/services/api";
import { storageService } from "@/services/storageService";
import { getFileExtension } from "@/lib/officePreview";
import { triggerUrlDownload } from "../ui/attachment";
import type {
  ArtifactAttachmentLike,
  ConversationArtifact,
} from "../utils/conversation-artifacts";
import { artifactPreviewIdentity } from "./use-auto-artifact-preview";

/** Original OOXML bytes use the existing browser renderer, never the PDF renderer. */
export function artifactDocumentSource(attachment: ArtifactAttachmentLike) {
  const name = attachment.name || "Generated file";
  const extension = getFileExtension(name);
  const rawStream = ["docx", "xlsx", "pptx"].includes(extension);
  const part = attachment.content?.[0] as { data?: string } | undefined;
  const direct =
    attachment.download_url ||
    attachment.presigned_url ||
    attachment.url ||
    part?.data ||
    attachment.preview_url ||
    "";
  const stream = attachment.object_name
    ? API_ENDPOINTS.storage.file(attachment.object_name, "stream", name)
    : direct;
  const previewUrl = rawStream
    ? stream
    : attachment.object_name
      ? storageService.getPreviewUrl(attachment.object_name, name)
      : attachment.preview_url || direct;
  return { previewUrl, downloadUrl: stream, rawStream };
}

interface ArtifactDocumentPanelProps {
  artifact: ConversationArtifact;
  onClose: () => void;
  onShowArtifacts: () => void;
}

export function ArtifactDocumentPanel({
  artifact,
  onClose,
  onShowArtifacts,
}: ArtifactDocumentPanelProps) {
  const { t } = useTranslation();
  const attachment = artifact.attachment as ArtifactAttachmentLike;
  const source = artifactDocumentSource(attachment);
  const name = attachment.name || "Generated file";
  return (
    <aside
      data-slot="artifact-document-panel"
      aria-label={name}
      className="fixed inset-0 z-50 flex min-h-0 flex-col border-l border-border bg-background lg:relative lg:inset-auto lg:z-auto lg:h-full lg:w-1/2 lg:min-w-[360px] lg:max-w-[900px] lg:shrink-0"
    >
      <header className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("chat.artifacts.title")}
          title={t("chat.artifacts.title")}
          onClick={onShowArtifacts}
        >
          <FolderOutput className="size-4" />
        </Button>
        <h2
          className="min-w-0 flex-1 truncate text-sm font-medium"
          title={name}
        >
          {name}
        </h2>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("chat.artifacts.download")}
          title={t("chat.artifacts.download")}
          disabled={!source.downloadUrl}
          onClick={() => triggerUrlDownload(source.downloadUrl, name)}
        >
          <Download className="size-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("chat.artifacts.close")}
          title={t("chat.artifacts.close")}
          onClick={onClose}
        >
          <X className="size-4" />
        </Button>
      </header>
      <div className="min-h-0 flex-1 overflow-hidden">
        <FilePreviewDrawer
          key={artifactPreviewIdentity(artifact)}
          open
          presentation="inline"
          onClose={onClose}
          objectName={attachment.object_name || ""}
          fileName={name}
          fileType={attachment.contentType}
          fileSize={attachment.size}
          {...source}
        />
      </div>
    </aside>
  );
}
