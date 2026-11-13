// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Checkbox, Tooltip } from "antd";
import { DeleteOutlined, EditOutlined } from "@ant-design/icons";

import type { AidpChunk } from "@/ext_components/aidp/shared/types/chunks";
import {
  isAidpChunkEditable,
  normalizeAidpChunkType,
} from "@/ext_components/aidp/shared/utils/aidpChunkType";
import styles from "./AidpSemanticChunks.module.css";

interface AidpChunkCardProps {
  chunk: AidpChunk;
  /** One-based position across the whole file, shown with a human-readable label. */
  index: number;
  selected: boolean;
  canEdit: boolean;
  onSelectChange: (selected: boolean) => void;
  onOpen: () => void;
  onEdit: () => void;
  onDelete: () => void;
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
 * One semantic chunk summary. Every displayed value comes from AIDP; a field
 * the response omitted is simply not rendered.
 */
const AidpChunkCard: React.FC<AidpChunkCardProps> = ({
  chunk,
  index,
  selected,
  canEdit,
  onSelectChange,
  onOpen,
  onEdit,
  onDelete,
}) => {
  const { t } = useTranslation();
  const text = typeof chunk.chunk_text === "string" ? chunk.chunk_text : "";
  const textRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [textOverflowing, setTextOverflowing] = useState(false);
  const editable = isAidpChunkEditable(chunk);
  const chunkType = normalizeAidpChunkType(chunk.chunk_type);
  const metadataEntries = Object.entries(chunk.metadata ?? {}).filter(
    ([key, value]) =>
      key.trim().length > 0 &&
      value !== null &&
      value !== undefined &&
      formatMetadataValue(value) !== ""
  );

  // Show the expand control only while the clamped preview actually hides
  // text. The length fallback covers browsers that do not expose a useful
  // scrollHeight for line-clamped boxes.
  useLayoutEffect(() => {
    if (expanded) return;
    const element = textRef.current;
    if (!element) return;
    const check = () => {
      setTextOverflowing(
        element.scrollHeight > element.clientHeight + 1 || text.length > 180
      );
    };
    check();
    const observer = new ResizeObserver(check);
    observer.observe(element);
    return () => observer.disconnect();
  }, [expanded, text]);

  return (
    <div className={`${styles.card} ${selected ? styles.cardSelected : ""}`}>
      {canEdit && (
        <span className="pt-0.5">
          <Checkbox
            checked={selected}
            onChange={(event) => onSelectChange(event.target.checked)}
            aria-label={t("aidpKnowledge.chunkSelectOne", {
              index,
            })}
          />
        </span>
      )}
      <div className={styles.cardBody}>
        <div
          className={styles.cardOpenButton}
          role="button"
          tabIndex={0}
          aria-label={t("aidpKnowledge.chunkView")}
          onClick={onOpen}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              onOpen();
            }
          }}
        >
          <span className={styles.cardMetaRow}>
            <span className={styles.cardIndex}>
              {t("aidpKnowledge.chunkSequence", { index })}
            </span>
            <span className={styles.cardMeta}>
              {t("aidpKnowledge.chunkId")}: {chunk.chunk_id}
            </span>
            <span className={styles.cardMeta}>
              {t("aidpKnowledge.chunkChars")}: {text.length}
            </span>
            {chunkType && (
              <span className={styles.cardTypeBadge}>{chunkType}</span>
            )}
          </span>
          <div
            ref={textRef}
            className={`${styles.cardText} ${
              expanded ? styles.cardTextExpanded : ""
            }`}
          >
            {text || t("aidpKnowledge.chunkTextEmpty")}
          </div>
        </div>
        {textOverflowing && (
          <button
            type="button"
            className={styles.cardExpandButton}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded
              ? t("aidpKnowledge.chunkCollapse")
              : t("aidpKnowledge.chunkExpand")}
          </button>
        )}
        {metadataEntries.length > 0 && (
          <div className={styles.cardMetadataRow}>
            <span className={styles.cardMetadataLabel}>
              {t("aidpKnowledge.chunkMetadata")}
            </span>
            {metadataEntries.map(([key, value]) => (
              <Tooltip
                key={key}
                color="#ffffff"
                rootClassName={styles.whiteTooltip}
                mouseEnterDelay={0.25}
                title={
                  <div className={styles.cardTooltipContent}>
                    {key}: {formatMetadataValue(value)}
                  </div>
                }
              >
                <span className={styles.cardMetadataTag}>
                  {key}: {formatMetadataValue(value)}
                </span>
              </Tooltip>
            ))}
          </div>
        )}
      </div>
      {canEdit && (
        <div className={styles.cardActions}>
          {editable && (
            <Tooltip title={t("aidpKnowledge.chunkEdit")}>
              <Button
                type="text"
                size="small"
                aria-label={t("aidpKnowledge.chunkEdit")}
                icon={<EditOutlined />}
                onClick={onEdit}
              />
            </Tooltip>
          )}
          <Tooltip title={t("aidpKnowledge.chunkDelete")}>
            <Button
              type="text"
              size="small"
              danger
              aria-label={t("aidpKnowledge.chunkDelete")}
              icon={<DeleteOutlined />}
              onClick={onDelete}
            />
          </Tooltip>
        </div>
      )}
    </div>
  );
};

export default AidpChunkCard;
