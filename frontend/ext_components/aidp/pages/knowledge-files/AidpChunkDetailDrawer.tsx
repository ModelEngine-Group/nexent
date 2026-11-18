// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useMemo } from "react";
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
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import {
  isAidpChunkEditable,
  normalizeAidpChunkType,
} from "@/ext_components/aidp/shared/utils/aidpChunkType";
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

  const metadataEntries = useMemo(
    () =>
      Object.entries(chunk?.metadata ?? {}).filter(
        ([key, value]) =>
          key.trim().length > 0 &&
          value !== null &&
          value !== undefined &&
          formatMetadataValue(value) !== ""
      ),
    [chunk?.metadata]
  );
  const text = typeof chunk?.chunk_text === "string" ? chunk.chunk_text : "";
  const chunkType = normalizeAidpChunkType(chunk?.chunk_type);
  const tableData = chunkType === "TABLE" ? parsePipeTable(text) : null;
  const editable = isAidpChunkEditable(chunk);

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

              {tableData ? (
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
