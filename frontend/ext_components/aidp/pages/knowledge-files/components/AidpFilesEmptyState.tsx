// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  collectDroppedFiles,
  type AidpDroppedFile,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpDropFiles";

import styles from "./AidpFilesEmptyState.module.css";

interface AidpFilesEmptyStateProps {
  /** Non-empty when the table is empty because a search matched nothing. */
  keyword?: string;
  folderLabel: string;
  isRoot: boolean;
  canUpload: boolean;
  onDropFiles: (files: AidpDroppedFile[]) => void;
  onBrowse: () => void;
}

/**
 * Centered empty state from the UCD: open-box illustration, a short hint and
 * a drop target that uploads into the current folder. Search-empty reuses the
 * same layout with a different message instead of Ant Design's default Empty.
 */
const AidpFilesEmptyState: React.FC<AidpFilesEmptyStateProps> = ({
  keyword,
  folderLabel,
  isRoot,
  canUpload,
  onDropFiles,
  onBrowse,
}) => {
  const { t } = useTranslation();
  const [dragOver, setDragOver] = useState(false);
  const isSearchEmpty = Boolean(keyword?.trim());

  if (isSearchEmpty) {
    return (
      <div className={styles.empty}>
        <div className={styles.searchIcon} aria-hidden="true">
          <svg viewBox="0 0 64 64" width="64" height="64" fill="none">
            <circle cx="28" cy="28" r="16" stroke="#c7d2e4" strokeWidth="2" />
            <path
              d="M40 40l10 10"
              stroke="#c7d2e4"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
        </div>
        <div className={styles.title}>
          {t("aidpKnowledge.filesSearchEmpty")}
        </div>
        <div className={styles.description}>
          {t("aidpKnowledge.filesSearchEmptyHint")}
        </div>
      </div>
    );
  }

  return (
    <div
      className={`${styles.empty} ${dragOver ? styles.dropActive : ""}`}
      onDragOver={(event) => {
        if (!canUpload) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
        setDragOver(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setDragOver(false);
        }
      }}
      onDrop={(event) => {
        if (!canUpload) return;
        event.preventDefault();
        setDragOver(false);
        void collectDroppedFiles(event.dataTransfer).then((files) => {
          if (files.length > 0) onDropFiles(files);
        });
      }}
    >
      <div className={styles.illustration} aria-hidden="true">
        <svg viewBox="0 0 160 132" width="160" height="132" fill="none">
          <path
            d="M44 44l10-22 30 4-8 18"
            stroke="#cfd8e6"
            strokeWidth="2"
            strokeLinejoin="round"
          />
          <path
            d="M118 44l-8-22-30 4 6 18"
            stroke="#cfd8e6"
            strokeWidth="2"
            strokeLinejoin="round"
          />
          <path
            d="M32 52h96v56a6 6 0 0 1-6 6H38a6 6 0 0 1-6-6V52z"
            fill="#f8fafc"
            stroke="#c3cede"
            strokeWidth="2"
          />
          <path
            d="M32 52l18-14h60l18 14"
            stroke="#c3cede"
            strokeWidth="2"
            strokeLinejoin="round"
          />
          <rect
            x="58"
            y="18"
            width="44"
            height="58"
            rx="3"
            fill="#fff"
            stroke="#d6deea"
            strokeWidth="2"
          />
          <path
            d="M67 32h26M67 42h26M67 52h18"
            stroke="#9fb3cc"
            strokeWidth="2"
            strokeLinecap="round"
          />
          <rect
            x="68"
            y="60"
            width="24"
            height="6"
            rx="1"
            fill="#dbeafe"
            stroke="#93b4f5"
            strokeWidth="1"
          />
          <path
            d="M66 34l-4-6M94 34l4-6M80 30V20"
            stroke="#d3dce9"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </svg>
      </div>
      <div className={styles.title}>
        {isRoot
          ? t("aidpKnowledge.filesEmptyRoot")
          : t("aidpKnowledge.filesEmptyFolder", { folder: folderLabel })}
      </div>
      {canUpload && (
        <>
          <button type="button" className={styles.browse} onClick={onBrowse}>
            {t("aidpKnowledge.filesEmptyAction")}
          </button>
          <div className={styles.description}>
            {t("aidpKnowledge.filesEmptyFormats")}
          </div>
        </>
      )}
      {!canUpload && (
        <div className={styles.description}>
          {t("aidpKnowledge.filesEmptyReadOnly")}
        </div>
      )}
    </div>
  );
};

export default AidpFilesEmptyState;
