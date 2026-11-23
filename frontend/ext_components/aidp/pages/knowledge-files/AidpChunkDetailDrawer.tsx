// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Drawer, Spin, Tooltip } from "antd";
import {
  CloseOutlined,
  DownloadOutlined,
  EditOutlined,
  LeftOutlined,
  RightOutlined,
} from "@ant-design/icons";

import type { AidpChunk } from "@/ext_components/aidp/shared/types/chunks";
import { useAidpChunkDetail } from "./hooks/useAidpFileChunks";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import {
  deriveAidpImageFileId,
  isAidpChunkEditable,
  normalizeAidpChunkType,
} from "@/ext_components/aidp/shared/utils/aidpChunkType";
import { sanitizeAidpTableHtml } from "@/ext_components/aidp/shared/utils/aidpTableHtml";
import styles from "./AidpSemanticChunks.module.css";

interface AidpChunkDetailDrawerProps {
  open: boolean;
  kdsId: string;
  chunkId: number | null;
  /** Chunks on the current page; they only drive previous/next navigation. */
  pageChunks: AidpChunk[];
  offset: number;
  canEdit: boolean;
  onClose: () => void;
  onNavigate: (chunkId: number) => void;
  onEdit: (chunk: AidpChunk) => void;
}

const formatMetadataValue = (value: unknown): string => {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

/**
 * TABLE chunks currently carry only text. When AIDP formats it as pipe-
 * separated rows, render a real table; otherwise fall back to the raw text.
 */
const parsePipeTable = (
  text: string
): { caption: string; rows: string[][] } | null => {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const tableLines = lines.filter((line) => line.includes("|"));
  if (tableLines.length < 2) return null;
  const rows = tableLines.map((line) =>
    line.split("|").map((cell) => cell.trim())
  );
  const columns = Math.max(...rows.map((row) => row.length));
  if (columns < 2) return null;
  const caption = lines.filter((line) => !line.includes("|")).join(" ");
  return {
    caption,
    rows: rows.map((row) => [
      ...row,
      ...Array.from({ length: columns - row.length }, () => ""),
    ]),
  };
};

/**
 * Read-only chunk detail in the same right-side drawer as the edit form.
 *
 * The drawer keeps the list mounted behind it. Only fields AIDP actually
 * returned are shown: `updated_at`, labels and entities have no source in the
 * chunk contract, so no placeholder is rendered for them.
 */
const AidpChunkDetailDrawer: React.FC<AidpChunkDetailDrawerProps> = ({
  open,
  kdsId,
  chunkId,
  pageChunks,
  offset,
  canEdit,
  onClose,
  onNavigate,
  onEdit,
}) => {
  const { t } = useTranslation();
  const detailQuery = useAidpChunkDetail(kdsId, open ? chunkId : null);
  const chunk = detailQuery.data;

  const position = useMemo(
    () => pageChunks.findIndex((item) => item.chunk_id === chunkId),
    [pageChunks, chunkId]
  );
  const sequence = position >= 0 ? offset + position + 1 : null;
  const previousChunk = position > 0 ? pageChunks[position - 1] : null;
  const nextChunk =
    position >= 0 && position < pageChunks.length - 1
      ? pageChunks[position + 1]
      : null;

  // Only the user-defined metadata is surfaced; AIDP's system metadata
  // (chapter/page_index/parent_chunk...) stays out of the page.
  const metadataEntries = useMemo(
    () =>
      Object.entries(chunk?.metadata_json ?? {}).filter(
        ([key, value]) =>
          key.trim().length > 0 &&
          value !== null &&
          value !== undefined &&
          formatMetadataValue(value) !== ""
      ),
    [chunk?.metadata_json]
  );
  // Ontology auto-tags arrive only on newer AIDP builds; absent means empty.
  const tags = Array.isArray(chunk?.tag)
    ? chunk.tag.filter((tag) => typeof tag === "string" && tag.trim())
    : [];
  const text = typeof chunk?.chunk_text === "string" ? chunk.chunk_text : "";
  const chunkType = normalizeAidpChunkType(chunk?.chunk_type);
  // Real AIDP formats TABLE chunks as "<title>\n\n<table>...</table>"; older
  // fixtures used pipe-separated rows. Prefer the sanitized HTML, fall back
  // to the pipe parser, then to the raw text.
  const tableHtml = chunkType === "TABLE" ? sanitizeAidpTableHtml(text) : null;
  const tableData =
    chunkType === "TABLE" && !tableHtml ? parsePipeTable(text) : null;
  const editable = isAidpChunkEditable(chunk);
  const imageFileId =
    chunkType === "IMAGE" ? deriveAidpImageFileId(chunk?.file_url) : undefined;

  const [image, setImage] = useState<{
    fileId?: string;
    url: string | null;
    failed: boolean;
  }>({ fileId: imageFileId, url: null, failed: false });
  // Reset the picture when a different chunk image is shown; adjusting state
  // during render keeps the synchronous reset out of the effect below.
  if (image.fileId !== imageFileId) {
    setImage({ fileId: imageFileId, url: null, failed: false });
  }
  const imageLoading =
    !!imageFileId &&
    image.fileId === imageFileId &&
    !image.url &&
    !image.failed;

  // Load the picture through the authenticated proxy: an <img> tag cannot
  // carry the Authorization header, so the bytes arrive as a blob object URL.
  useEffect(() => {
    if (!imageFileId) return;
    const controller = new AbortController();
    let objectUrl: string | undefined;
    aidpKnowledgeService
      .fetchChunkImage(kdsId, imageFileId, controller.signal)
      .then(async (response) => {
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setImage({ fileId: imageFileId, url: objectUrl, failed: false });
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setImage({ fileId: imageFileId, url: null, failed: true });
        }
        void error;
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [kdsId, imageFileId]);

  // Export only the detail response, without adding fields the UI does not
  // have. The file name follows the chunk id so downloads remain distinguishable.
  const handleExport = useCallback(() => {
    if (!chunk) return;
    const blob = new Blob([JSON.stringify(chunk, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    try {
      link.href = url;
      link.download = `chunk-${chunk.chunk_id}.json`;
      document.body.appendChild(link);
      link.click();
    } finally {
      link.remove();
      URL.revokeObjectURL(url);
    }
  }, [chunk]);

  return (
    <Drawer
      open={open}
      onClose={onClose}
      size="min(960px, 50vw)"
      rootClassName={styles.chunkDrawer}
      closable={false}
      styles={{
        body: { padding: 0, display: "flex", flexDirection: "column" },
      }}
      mask={{ closable: true }}
    >
      {open && (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className={styles.drawerTitleRow}>
            <h2 className={styles.drawerTitle}>
              {sequence !== null
                ? `#${sequence}`
                : t("aidpKnowledge.chunkDetailTitle")}
            </h2>
            <div className="flex items-center gap-1">
              <Tooltip title={t("aidpKnowledge.chunkExportJson")}>
                <Button
                  type="text"
                  icon={<DownloadOutlined />}
                  aria-label={t("aidpKnowledge.chunkExportJson")}
                  disabled={!chunk}
                  onClick={handleExport}
                />
              </Tooltip>
              {canEdit && chunk && editable && (
                <Button
                  type="text"
                  icon={<EditOutlined />}
                  aria-label={t("aidpKnowledge.chunkEdit")}
                  onClick={() => onEdit(chunk)}
                />
              )}
              <Button
                type="text"
                aria-label={t("common.close")}
                icon={<CloseOutlined />}
                onClick={onClose}
              />
            </div>
          </div>

          {detailQuery.isError ? (
            <div className={styles.detailDrawerBody}>
              <Alert
                type="error"
                showIcon
                title={getAidpErrorMessage(
                  detailQuery.error,
                  t,
                  t("aidpKnowledge.chunkDetailLoadFailed")
                )}
                action={
                  <Button
                    size="small"
                    onClick={() => void detailQuery.refetch()}
                  >
                    {t("aidpKnowledge.chunksRetry")}
                  </Button>
                }
              />
            </div>
          ) : detailQuery.isPending ? (
            <div className={styles.detailDrawerBody}>
              <div className="flex min-h-[160px] items-center justify-center">
                <Spin />
              </div>
            </div>
          ) : (
            <div className={styles.detailDrawerBody}>
              <div className={styles.detailMetaGrid}>
                <div className={styles.detailMetaItem}>
                  <span className={styles.detailMetaLabel}>
                    {t("aidpKnowledge.chunkId")}
                  </span>
                  <span className={styles.detailMetaValue}>
                    {chunk?.chunk_id ?? t("aidpKnowledge.chunkUnknown")}
                  </span>
                </div>
                <div className={styles.detailMetaItem}>
                  <span className={styles.detailMetaLabel}>
                    {t("aidpKnowledge.chunkChars")}
                  </span>
                  <span className={styles.detailMetaValue}>{text.length}</span>
                </div>
                <div className={styles.detailMetaItem}>
                  <span className={styles.detailMetaLabel}>
                    {t("aidpKnowledge.chunkUpdatedAt")}
                  </span>
                  <span className={styles.detailMetaValue}>
                    {chunk?.updated_at || "—"}
                  </span>
                </div>
              </div>

              {chunkType === "IMAGE" && (
                <div className={styles.detailImageWrap}>
                  {imageLoading ? (
                    <div className={styles.detailImagePlaceholder}>
                      <Spin size="small" />
                    </div>
                  ) : image.url ? (
                    // eslint-disable-next-line @next/next/no-img-element -- object URL from an authenticated fetch cannot be an optimized <Image>.
                    <img
                      className={styles.detailImage}
                      src={image.url}
                      alt={t("aidpKnowledge.chunkImageAlt")}
                    />
                  ) : image.failed ? (
                    <div className={styles.detailImageFallback}>
                      {t("aidpKnowledge.chunkImageUnavailable")}
                    </div>
                  ) : null}
                </div>
              )}

              {tableHtml ? (
                <div className={styles.chunkTableWrap}>
                  {tableHtml.caption && (
                    <div className={styles.chunkTableCaption}>
                      {tableHtml.caption}
                    </div>
                  )}
                  <div
                    className={styles.chunkTableScroll}
                    // Rebuilt from a table-only whitelist by
                    // sanitizeAidpTableHtml; no script-capable markup survives.
                    dangerouslySetInnerHTML={{ __html: tableHtml.tableHtml }}
                  />
                </div>
              ) : tableData ? (
                <div className={styles.chunkTableWrap}>
                  {tableData.caption && (
                    <div className={styles.chunkTableCaption}>
                      {tableData.caption}
                    </div>
                  )}
                  <div className={styles.chunkTableScroll}>
                    <table className={styles.chunkTable}>
                      <thead>
                        <tr>
                          {tableData.rows[0].map((cell, index) => (
                            <th key={index}>{cell}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {tableData.rows.slice(1).map((row, rowIndex) => (
                          <tr key={rowIndex}>
                            {row.map((cell, cellIndex) => (
                              <td key={cellIndex}>{cell}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div className={styles.detailTextBlock}>
                  {text || t("aidpKnowledge.chunkTextEmpty")}
                </div>
              )}

              <section className={styles.detailSection}>
                <h3 className={styles.detailSectionTitle}>
                  {metadataEntries.length > 0
                    ? t("aidpKnowledge.chunkMetadataCount", {
                        count: metadataEntries.length,
                      })
                    : t("aidpKnowledge.chunkMetadata")}
                </h3>
                {metadataEntries.length > 0 ? (
                  <div className={styles.metadataList}>
                    {metadataEntries.map(([key, value]) => (
                      <span key={key} className={styles.metadataTag}>
                        {key}: {formatMetadataValue(value)}
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className={styles.detailMetaValue}>
                    {t("aidpKnowledge.chunkNoMetadata")}
                  </div>
                )}
              </section>

              {tags.length > 0 && (
                <section className={styles.detailSection}>
                  <h3 className={styles.detailSectionTitle}>
                    {t("aidpKnowledge.chunkTagsCount", {
                      count: tags.length,
                    })}
                  </h3>
                  <div className={styles.metadataList}>
                    {tags.map((tag) => (
                      <span key={tag} className={styles.metadataTag}>
                        {tag}
                      </span>
                    ))}
                  </div>
                </section>
              )}
            </div>
          )}

          <div className={styles.detailDrawerFooter}>
            <Tooltip title={t("aidpKnowledge.chunkPrevious")}>
              <Button
                className={styles.detailNavButton}
                icon={<LeftOutlined />}
                aria-label={t("aidpKnowledge.chunkPrevious")}
                disabled={!previousChunk}
                onClick={() =>
                  previousChunk && onNavigate(previousChunk.chunk_id)
                }
              />
            </Tooltip>
            <Tooltip title={t("aidpKnowledge.chunkNext")}>
              <Button
                className={styles.detailNavButton}
                icon={<RightOutlined />}
                aria-label={t("aidpKnowledge.chunkNext")}
                disabled={!nextChunk}
                onClick={() => nextChunk && onNavigate(nextChunk.chunk_id)}
              />
            </Tooltip>
          </div>
        </div>
      )}
    </Drawer>
  );
};

export default AidpChunkDetailDrawer;
