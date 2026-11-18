// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import dynamic from "next/dynamic";
import React, { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, ConfigProvider, Tooltip } from "antd";
import {
  ArrowLeftOutlined,
  DownloadOutlined,
  ExpandOutlined,
} from "@ant-design/icons";

import type { AidpDocumentItem } from "@/ext_components/aidp/shared/types/management";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { FilePreviewDrawer } from "@/components/common/filePreviewDrawer";
import { getAidpDownloadFilename } from "@/ext_components/aidp/shared/utils/aidpDownloadFilename";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import log from "@/lib/logger";
import AidpSemanticChunksPanel from "./AidpSemanticChunksPanel";
import AidpFileSummaryPanel from "./AidpFileSummaryPanel";
import styles from "./AidpFileDetail.module.css";

const AidpPdfViewer = dynamic(
  () => import("./AidpPdfViewer").then((module) => module.AidpPdfViewer),
  { ssr: false }
);

interface AidpFileDetailViewProps {
  kdsId: string;
  file: AidpDocumentItem;
  canEdit: boolean;
  /** KB summary_enable; when false the summary tab is hidden and never queried. */
  summaryEnabled?: boolean;
  /** KB summary_preview; an explicit false shows the not-previewable state. */
  summaryPreview?: boolean;
  onBack: () => void;
}

/**
 * File detail for one ingested AIDP document.
 *
 * The left pane reuses the existing preview stream; the right pane hosts the
 * file tabs. Only the summary and semantic chunk tabs are implemented in this
 * phase; OCR parsing is outside the current version's scope.
 */
const AidpFileDetailView: React.FC<AidpFileDetailViewProps> = ({
  kdsId,
  file,
  canEdit,
  summaryEnabled = false,
  summaryPreview = false,
  onBack,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [downloading, setDownloading] = useState(false);
  const [fullscreenOpen, setFullscreenOpen] = useState(false);
  // A KB with summaries enabled opens on the summary tab (UCD's first tab);
  // without summaries the chunk tab is the only implemented content tab.
  const [requestedTab, setRequestedTab] = useState<"summary" | "chunks">(
    "summary"
  );
  const activeTab = summaryEnabled ? requestedTab : "chunks";

  const loadOriginal = useCallback(
    () => aidpKnowledgeService.downloadDoc(kdsId, file.file_uuid),
    [kdsId, file.file_uuid]
  );

  const previewUrl = aidpKnowledgeService.getPreviewUrl(kdsId, file.file_uuid);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const response = await aidpKnowledgeService.downloadDoc(
        kdsId,
        file.file_uuid
      );
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      try {
        link.href = url;
        link.download = getAidpDownloadFilename(response.headers, file);
        document.body.appendChild(link);
        link.click();
      } finally {
        link.remove();
        URL.revokeObjectURL(url);
      }
    } catch (error) {
      log.error("Failed to download AIDP document", {
        kdsId,
        fileUuid: file.file_uuid,
        error,
      });
      message.error(
        getAidpErrorMessage(error, t, t("aidpKnowledge.downloadFailed"))
      );
    } finally {
      setDownloading(false);
    }
  };

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: "#0067d1",
          borderRadius: 4,
          controlHeight: 32,
          fontFamily: '"HarmonyOS Sans SC", "Microsoft YaHei", sans-serif',
        },
      }}
    >
      <div className={styles.shell}>
        <div className={styles.split}>
            <div className={styles.readerHeader}>
              <Button
                type="text"
                icon={<ArrowLeftOutlined />}
                onClick={onBack}
                aria-label={t("common.back")}
              />
              <span className={styles.fileName} title={file.file_name}>
                {file.file_name}
              </span>
              <Tooltip title={t("aidpKnowledge.download")}>
                <Button
                  type="text"
                  icon={<DownloadOutlined />}
                  loading={downloading}
                  onClick={() => void handleDownload()}
                  aria-label={t("aidpKnowledge.download")}
                />
              </Tooltip>
              <Tooltip title={t("aidpKnowledge.chunkFullscreenPreview")}>
                <Button
                  type="text"
                  icon={<ExpandOutlined />}
                  onClick={() => setFullscreenOpen(true)}
                  aria-label={t("aidpKnowledge.chunkFullscreenPreview")}
                />
              </Tooltip>
            </div>
          <div className={styles.previewPane}>
            <div className={styles.readerContent}>
              {/* The preview keeps its own loading/error/format handling; inline
              mode only removes the drawer chrome so it fills this column. */}
              <FilePreviewDrawer
                open
                source="remote"
                objectName={file.file_uuid}
                fileName={file.file_name}
                fileType={file.file_type}
                fileSize={file.file_size}
                previewUrl={previewUrl}
                loadOriginal={loadOriginal}
                pdfRenderer={AidpPdfViewer}
                rawStream
                presentation="inline"
                previewContext="knowledgeBase"
                onClose={() => undefined}
              />
            </div>
          </div>
          <div className={styles.panelPane}>
            <div className={styles.tabRow} role="tablist">
              {summaryEnabled && (
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === "summary"}
                  className={`${styles.tab} ${
                    activeTab === "summary" ? styles.tabActive : ""
                  }`}
                  onClick={() => setRequestedTab("summary")}
                >
                  {t("aidpKnowledge.chunksTabSummary")}
                </button>
              )}
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "chunks"}
                className={`${styles.tab} ${
                  activeTab === "chunks" ? styles.tabActive : ""
                }`}
                onClick={() => setRequestedTab("chunks")}
              >
                {t("aidpKnowledge.chunksTab")}
              </button>
            </div>
            {activeTab === "summary" ? (
              <AidpFileSummaryPanel
                kdsId={kdsId}
                fileUuid={file.file_uuid}
                canEdit={canEdit}
                previewEnabled={summaryPreview}
              />
            ) : (
              <AidpSemanticChunksPanel
                kdsId={kdsId}
                fileUuid={file.file_uuid}
                fileName={file.file_name}
                canEdit={canEdit}
              />
            )}
          </div>
        </div>

        {fullscreenOpen && (
          <FilePreviewDrawer
            open
            source="remote"
            objectName={file.file_uuid}
            fileName={file.file_name}
            fileType={file.file_type}
            fileSize={file.file_size}
            previewUrl={previewUrl}
            loadOriginal={loadOriginal}
            pdfRenderer={AidpPdfViewer}
            rawStream
            presentation="fullscreen"
            previewContext="knowledgeBase"
            onClose={() => setFullscreenOpen(false)}
          />
        )}
      </div>
    </ConfigProvider>
  );
};

export default AidpFileDetailView;
