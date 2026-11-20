// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Drawer, Input } from "antd";
import { CloseOutlined } from "@ant-design/icons";

import type { AidpChunk } from "@/ext_components/aidp/shared/types/chunks";
import { normalizeAidpChunkType } from "@/ext_components/aidp/shared/utils/aidpChunkType";
import { sanitizeAidpTableHtml } from "@/ext_components/aidp/shared/utils/aidpTableHtml";
import styles from "./AidpSemanticChunks.module.css";

export const AIDP_CHUNK_TEXT_MAX_LENGTH = 10240;

export type AidpChunkDrawerMode = "create" | "edit";

interface AidpChunkDrawerProps {
  open: boolean;
  mode: AidpChunkDrawerMode;
  /** The chunk being edited; null when adding a new one. */
  chunk: AidpChunk | null;
  submitting: boolean;
  onClose: () => void;
  /** Rejecting keeps the drawer open with the entered text intact. */
  onSubmit: (text: string) => Promise<void>;
}

type AidpChunkFormProps = Omit<AidpChunkDrawerProps, "open">;

/**
 * Text form for one chunk.
 *
 * It is mounted only while the drawer is open and keyed by the target chunk,
 * so every target starts with its own text and a failed submit keeps the input.
 */
const AidpChunkForm: React.FC<AidpChunkFormProps> = ({
  mode,
  chunk,
  submitting,
  onClose,
  onSubmit,
}) => {
  const { t } = useTranslation();
  const [text, setText] = useState(
    mode === "edit" ? (chunk?.chunk_text ?? "") : ""
  );
  const [focused, setFocused] = useState(false);
  const [touched, setTouched] = useState(false);
  // TABLE chunks edit the HTML source; the preview renders it only when it
  // sanitizes cleanly, otherwise the toggle surfaces a format error.
  const isTableChunk =
    mode === "edit" && normalizeAidpChunkType(chunk?.chunk_type) === "TABLE";
  const [previewing, setPreviewing] = useState(false);
  const preview = useMemo(
    () => (isTableChunk && previewing ? sanitizeAidpTableHtml(text) : null),
    [isTableChunk, previewing, text]
  );

  const trimmed = text.trim();
  const isEmpty = trimmed.length === 0;
  const isTooLong = text.length > AIDP_CHUNK_TEXT_MAX_LENGTH;
  const canSubmit = !isEmpty && !isTooLong && !submitting;
  // UCD values: 1px border, 4px radius, #DFDFDF default and #0067D1 focus.
  // Applied inline because Ant Design's outlined input draws its border with a
  // box-shadow, which overrides a same-specificity CSS module rule.
  const textAreaBorderColor = isTooLong
    ? "#e02128"
    : focused
      ? "#0067d1"
      : "#dfdfdf";

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    try {
      await onSubmit(trimmed);
    } catch {
      // The parent reports the failure; keeping the text lets the user retry.
    }
  }, [canSubmit, onSubmit, trimmed]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className={styles.drawerTitleRow}>
          <h2 className={styles.drawerTitle}>
            {mode === "create"
              ? t("aidpKnowledge.chunkCreateTitle")
              : t("aidpKnowledge.chunkEditTitle")}
          </h2>
          <Button
            type="text"
            aria-label={t("common.close")}
            icon={<CloseOutlined />}
            onClick={onClose}
            disabled={submitting}
          />
        </div>
        <div className={styles.drawerContent}>
          {mode === "edit" && (
            <div>
              <div className={styles.fieldLabelRow}>
                <span className={styles.fieldLabel}>
                  {t("aidpKnowledge.chunkId")}
                </span>
              </div>
              <div className={styles.readonlyInput}>
                {chunk?.chunk_id ?? t("aidpKnowledge.chunkUnknown")}
              </div>
            </div>
          )}
          <div>
            <div className={styles.fieldLabelRow}>
              <span className={styles.fieldLabel}>
                {t("aidpKnowledge.chunkText")}
              </span>
              <span className={styles.requiredMark} aria-hidden="true">
                *
              </span>
              {isTableChunk && (
                <Button
                  type="link"
                  size="small"
                  className={styles.previewToggle}
                  disabled={submitting}
                  onClick={() => setPreviewing((prev) => !prev)}
                >
                  {previewing
                    ? t("aidpKnowledge.chunkTableBackToEdit")
                    : t("aidpKnowledge.chunkTablePreview")}
                </Button>
              )}
            </div>
            {previewing ? (
              preview ? (
                <div className={styles.chunkTableWrap}>
                  {preview.caption && (
                    <div className={styles.chunkTableCaption}>
                      {preview.caption}
                    </div>
                  )}
                  <div
                    className={styles.chunkTableScroll}
                    // Rebuilt from a table-only whitelist by
                    // sanitizeAidpTableHtml; no script-capable markup survives.
                    dangerouslySetInnerHTML={{ __html: preview.tableHtml }}
                  />
                </div>
              ) : (
                <Alert
                  type="error"
                  showIcon
                  title={t("aidpKnowledge.chunkTableInvalid")}
                />
              )
            ) : (
              <Input.TextArea
                className={styles.textArea}
                style={{
                  border: `1px solid ${textAreaBorderColor}`,
                  borderRadius: 4,
                  boxShadow: "none",
                  minHeight: 160,
                  padding: "8px 12px",
                  resize: "vertical",
                }}
                value={text}
                onChange={(event) => {
                  setText(event.target.value);
                  setTouched(true);
                }}
                onFocus={() => setFocused(true)}
                onBlur={() => {
                  setFocused(false);
                  setTouched(true);
                }}
                placeholder={
                  isTableChunk
                    ? t("aidpKnowledge.chunkTableHtmlPlaceholder")
                    : t("aidpKnowledge.chunkTextPlaceholder")
                }
                autoSize={{ minRows: 6, maxRows: 14 }}
                aria-label={t("aidpKnowledge.chunkText")}
                aria-invalid={isTooLong || isEmpty}
                aria-required="true"
                disabled={submitting}
              />
            )}
            <div className={styles.counterRow}>
              <span className={styles.formHint}>
                {mode === "create"
                  ? t("aidpKnowledge.chunkCreateHint")
                  : isTableChunk
                    ? t("aidpKnowledge.chunkTableEditHint")
                    : t("aidpKnowledge.chunkEditVectorHint")}
              </span>
              <span className={styles.counter}>
                {text.length}/{AIDP_CHUNK_TEXT_MAX_LENGTH}
              </span>
            </div>
            {isTooLong && (
              <p className={styles.errorText}>
                {t("aidpKnowledge.chunkTextTooLong", {
                  max: AIDP_CHUNK_TEXT_MAX_LENGTH,
                })}
              </p>
            )}
            {!isTooLong && touched && isEmpty && (
              <p className={styles.errorText}>
                {t("aidpKnowledge.chunkTextRequired")}
              </p>
            )}
          </div>
        </div>
      </div>
      <div className={styles.drawerFooter}>
        <Button onClick={onClose} disabled={submitting}>
          {t("common.cancel")}
        </Button>
        <Button
          type="primary"
          loading={submitting}
          disabled={!canSubmit}
          onClick={() => void handleSubmit()}
        >
          {t("aidpKnowledge.chunkSave")}
        </Button>
      </div>
    </div>
  );
};

/**
 * Add or edit one chunk.
 *
 * Only the text is writable: the AIDP contract accepts `chunk_text` alone for
 * an update. The prototype's metadata/entity editors have no backend write
 * capability, so this version does not render those sections.
 */
const AidpChunkDrawer: React.FC<AidpChunkDrawerProps> = ({
  open,
  mode,
  chunk,
  submitting,
  onClose,
  onSubmit,
}) => (
  <Drawer
    open={open}
    onClose={onClose}
    size="min(960px, 50vw)"
    rootClassName={styles.chunkDrawer}
    closable={false}
    styles={{ body: { padding: 0, display: "flex", flexDirection: "column" } }}
    mask={{ closable: !submitting }}
    keyboard={!submitting}
  >
    {open && (
      <AidpChunkForm
        key={`${mode}-${chunk?.chunk_id ?? "new"}`}
        mode={mode}
        chunk={chunk}
        submitting={submitting}
        onClose={onClose}
        onSubmit={onSubmit}
      />
    )}
  </Drawer>
);

export default AidpChunkDrawer;
