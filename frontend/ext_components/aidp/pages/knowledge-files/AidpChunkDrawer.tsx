// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Drawer, Input, Select } from "antd";
import {
  CloseOutlined,
  DeleteOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";

import type { AidpChunk } from "@/ext_components/aidp/shared/types/chunks";
import type { AidpOntologyMetadataField } from "@/ext_components/aidp/shared/types/ontology";
import { normalizeAidpChunkType } from "@/ext_components/aidp/shared/utils/aidpChunkType";
import { sanitizeAidpTableHtml } from "@/ext_components/aidp/shared/utils/aidpTableHtml";
import AidpMetadataEditor, { type AidpMetadataRow } from "./AidpMetadataEditor";
import styles from "./AidpSemanticChunks.module.css";

export const AIDP_CHUNK_TEXT_MAX_LENGTH = 10240;
const AIDP_TAG_LIMIT = 100;

export type AidpChunkDrawerMode = "create" | "edit";

/** Payload assembled by the drawer; the parent decides how to persist it. */
export interface AidpChunkFormPayload {
  text: string;
  /** True when a metadata value was added, changed or cleared. */
  metadataChanged: boolean;
  /** True when the tag set changed. */
  tagChanged: boolean;
  tag: string[];
  metadata_json: Record<string, string | null>;
}

interface AidpChunkDrawerProps {
  open: boolean;
  mode: AidpChunkDrawerMode;
  /** The chunk being edited; null when adding a new one. */
  chunk: AidpChunk | null;
  submitting: boolean;
  /** Bound ontology domain; without it the tag/metadata editors are hidden. */
  odId?: number | string | null;
  metadataFields: AidpOntologyMetadataField[];
  /** Entity display names of the bound domain, offered as tag choices. */
  tagOptions: string[];
  onClose: () => void;
  /** Rejecting keeps the drawer open with the entered values intact. */
  onSubmit: (payload: AidpChunkFormPayload) => Promise<void>;
}

type AidpChunkFormProps = Omit<AidpChunkDrawerProps, "open">;

const buildInitialRows = (
  chunk: AidpChunk | null,
  fields: AidpOntologyMetadataField[]
): AidpMetadataRow[] => {
  const raw = chunk?.metadata_json ?? {};
  return fields
    .filter((field) => {
      const value = raw[field.field_name];
      return value !== null && value !== undefined && value !== "";
    })
    .map((field) => ({
      fieldName: field.field_name,
      value: String(raw[field.field_name]),
    }));
};

/**
 * Text, metadata and tags form for one chunk, laid out per the edit-chunk UCD:
 * metadata rows (field name, type, value) followed by tag rows, each with its
 * own select and delete action.
 *
 * Tags and metadata are only offered while the knowledge base is bound to an
 * ontology domain: metadata keys must exist in that domain, and tag values
 * must be entities of it. Saving calls AIDP only when the user actually
 * changed one of them, so a plain text edit never rewrites metadata.
 */
const AidpChunkForm: React.FC<AidpChunkFormProps> = ({
  mode,
  chunk,
  submitting,
  odId,
  metadataFields,
  tagOptions,
  onClose,
  onSubmit,
}) => {
  const { t } = useTranslation();
  const [text, setText] = useState(
    mode === "edit" ? (chunk?.chunk_text ?? "") : ""
  );
  const [focused, setFocused] = useState(false);
  const [touched, setTouched] = useState(false);
  const hasOntology = odId !== null && odId !== undefined;
  const [rows, setRows] = useState<AidpMetadataRow[]>(() =>
    buildInitialRows(chunk, metadataFields)
  );
  const [tagRows, setTagRows] = useState<string[]>(() => chunk?.tag ?? []);
  const initialRows = useMemo(
    () => buildInitialRows(chunk, metadataFields),
    [chunk, metadataFields]
  );
  const initialTags = useMemo(() => chunk?.tag ?? [], [chunk]);

  // TABLE chunks edit the HTML source; the preview renders it only when it
  // sanitizes cleanly, otherwise the toggle surfaces a format error.
  const isTableChunk =
    mode === "edit" && normalizeAidpChunkType(chunk?.chunk_type) === "TABLE";
  const [previewing, setPreviewing] = useState(false);
  const preview = useMemo(
    () => (isTableChunk && previewing ? sanitizeAidpTableHtml(text) : null),
    [isTableChunk, previewing, text]
  );
  const tablePreviewRef = useRef<HTMLDivElement | null>(null);
  const previewDirtyRef = useRef(false);
  const [previewLength, setPreviewLength] = useState<number | null>(null);

  // Keep the preview table structural, but allow plain-text cell edits. The
  // DOM is only committed back to the HTML textarea when leaving preview or
  // submitting, so React does not re-render the table on every keystroke.
  // Cells are plaintext-only, so the table structure is always intact.
  const serializePreview = useCallback((): string => {
    // Only reachable while the preview is mounted; cells accept plaintext only.
    const root = tablePreviewRef.current!;
    const clone = root.cloneNode(true) as HTMLElement;
    clone.querySelectorAll("[contenteditable]").forEach((cell) => {
      cell.removeAttribute("contenteditable");
      cell.removeAttribute("spellcheck");
    });
    const tableHtml = clone.innerHTML;
    return preview?.caption ? `${preview.caption}\n\n${tableHtml}` : tableHtml;
  }, [preview]);

  const refreshPreviewLength = useCallback(() => {
    setPreviewLength(serializePreview().length);
  }, [serializePreview]);

  // Mount the sanitized DOM directly instead of injecting an HTML string.
  // The table is rebuilt from text nodes, so document text never becomes HTML.
  const mountTablePreview = useCallback(
    (node: HTMLDivElement | null) => {
      tablePreviewRef.current = node;
      if (!node || !preview) return;
      node.replaceChildren(preview.table.cloneNode(true));
      for (const cell of node.querySelectorAll<HTMLElement>("td,th")) {
        // plaintext-only keeps every edit to text, so cells cannot inject markup.
        cell.setAttribute("contenteditable", "plaintext-only");
        cell.setAttribute("spellcheck", "false");
      }
    },
    [preview]
  );

  const togglePreview = useCallback(() => {
    if (!previewing) {
      previewDirtyRef.current = false;
      setPreviewLength(null);
      setPreviewing(true);
      return;
    }
    if (previewDirtyRef.current) {
      setText(serializePreview());
      setTouched(true);
      previewDirtyRef.current = false;
    }
    setPreviewLength(null);
    setPreviewing(false);
  }, [previewing, serializePreview]);

  const handlePreviewInput = useCallback(() => {
    previewDirtyRef.current = true;
    refreshPreviewLength();
  }, [refreshPreviewLength]);

  const handlePreviewPaste = useCallback(
    (event: React.ClipboardEvent<HTMLDivElement>) => {
      event.preventDefault();
      const plainText = event.clipboardData.getData("text/plain");
      const root = tablePreviewRef.current;
      const selection = window.getSelection();
      if (!root || !plainText || !selection || selection.rangeCount === 0) {
        return;
      }
      const range = selection.getRangeAt(0);
      const anchor =
        range.startContainer.nodeType === Node.ELEMENT_NODE
          ? (range.startContainer as Element)
          : range.startContainer.parentElement;
      // Only insert while the caret is inside a table cell.
      if (!anchor || !root.contains(anchor) || !anchor.closest("td,th")) {
        return;
      }
      range.deleteContents();
      const textNode = document.createTextNode(plainText);
      range.insertNode(textNode);
      range.setStartAfter(textNode);
      range.collapse(true);
      selection.removeAllRanges();
      selection.addRange(range);
      previewDirtyRef.current = true;
      refreshPreviewLength();
    },
    [refreshPreviewLength]
  );

  const handlePreviewDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      // A drop could insert rich markup; the preview only accepts typed text.
      event.preventDefault();
    },
    []
  );

  const handlePreviewKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      // Enter would let contentEditable insert block elements into the table.
      if (event.key === "Enter") event.preventDefault();
    },
    []
  );

  const trimmed = text.trim();
  const isEmpty = trimmed.length === 0;
  // While previewing, the textarea is hidden and its state intentionally stays
  // untouched; the serialized preview length keeps the counter live.
  const effectiveLength =
    previewing && previewLength !== null ? previewLength : text.length;
  const isTooLong = effectiveLength > AIDP_CHUNK_TEXT_MAX_LENGTH;

  const metadataJson = useMemo(() => {
    const current: Record<string, string> = {};
    for (const row of rows) {
      const value = row.value.trim();
      if (row.fieldName && value) current[row.fieldName] = value;
    }
    const result: Record<string, string | null> = {};
    // A field that existed before and is now empty is an explicit deletion.
    for (const row of initialRows) {
      result[row.fieldName] = current[row.fieldName] ?? null;
    }
    for (const [fieldName, value] of Object.entries(current)) {
      if (!(fieldName in result)) result[fieldName] = value;
    }
    return result;
  }, [initialRows, rows]);

  const cleanedTags = useMemo(
    () => Array.from(new Set(tagRows.map((tag) => tag.trim()).filter(Boolean))),
    [tagRows]
  );

  const metadataChanged = useMemo(() => {
    if (!hasOntology) return false;
    const initialJson: Record<string, string> = {};
    for (const row of initialRows) {
      if (row.value.trim()) initialJson[row.fieldName] = row.value.trim();
    }
    const keys = new Set([
      ...Object.keys(metadataJson),
      ...Object.keys(initialJson),
    ]);
    return Array.from(keys).some(
      (key) => (metadataJson[key] ?? null) !== (initialJson[key] ?? null)
    );
  }, [hasOntology, initialRows, metadataJson]);

  const tagChanged = useMemo(() => {
    if (!hasOntology) return false;
    return (
      cleanedTags.length !== initialTags.length ||
      cleanedTags.some((tag) => !initialTags.includes(tag))
    );
  }, [cleanedTags, hasOntology, initialTags]);

  const canSubmit = !isEmpty && !isTooLong && !submitting;
  // UCD values: 1px border, 4px radius, #DFDFDF default and #0067D1 focus.
  const textAreaBorderColor = isTooLong
    ? "#e02128"
    : focused
      ? "#0067d1"
      : "#dfdfdf";

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    const nextText =
      previewing && previewDirtyRef.current ? serializePreview() : text;
    const nextTrimmed = nextText.trim();
    if (!nextTrimmed || nextText.length > AIDP_CHUNK_TEXT_MAX_LENGTH) {
      setText(nextText);
      setPreviewing(false);
      setPreviewLength(null);
      previewDirtyRef.current = false;
      return;
    }
    try {
      await onSubmit({
        text: nextTrimmed,
        metadataChanged,
        tagChanged,
        tag: cleanedTags,
        metadata_json: metadataJson,
      });
    } catch {
      // The parent reports the failure; keeping the values lets the user retry.
    }
  }, [
    canSubmit,
    cleanedTags,
    metadataChanged,
    metadataJson,
    onSubmit,
    previewing,
    serializePreview,
    tagChanged,
    text,
  ]);

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
                  onClick={togglePreview}
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
                    ref={mountTablePreview}
                    className={styles.chunkTableScroll}
                    onInput={handlePreviewInput}
                    onPaste={handlePreviewPaste}
                    onDrop={handlePreviewDrop}
                    onDragOver={handlePreviewDrop}
                    onKeyDown={handlePreviewKeyDown}
                    // Built from a table-only whitelist and mounted as DOM
                    // nodes; cells are contenteditable but only their text is
                    // committed back, never the table structure.
                  />
                  <div className={styles.formHint}>
                    <InfoCircleOutlined className={styles.hintIcon} />
                    {t("aidpKnowledge.chunkTablePreviewEditHint")}
                  </div>
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
                  background: submitting ? "#f5f5f5" : "#ffffff",
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
                <InfoCircleOutlined className={styles.hintIcon} />
                {mode === "create"
                  ? t("aidpKnowledge.chunkCreateHint")
                  : isTableChunk
                    ? t("aidpKnowledge.chunkTableEditHint")
                    : t("aidpKnowledge.chunkEditVectorHint")}
              </span>
              <span className={styles.counter}>
                {effectiveLength}/{AIDP_CHUNK_TEXT_MAX_LENGTH}
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

          {hasOntology && metadataFields.length > 0 && (
            <AidpMetadataEditor
              fields={metadataFields}
              rows={rows}
              onChange={setRows}
              submitting={submitting}
            />
          )}

          {hasOntology && (
            <div>
              <div className={styles.fieldLabelRow}>
                <span className={styles.fieldLabel}>
                  {t("aidpKnowledge.chunkTags")}
                </span>
              </div>
              <div className={styles.tagTableHead}>
                <span>{t("aidpKnowledge.chunkMetadataValue")}</span>
                <span>{t("aidpKnowledge.chunkMetadataOperation")}</span>
              </div>
              {tagRows.map((tag, index) => (
                <div key={`tag-${index}`} className={styles.tagTableRow}>
                  <Select
                    className={styles.metadataFieldControl}
                    value={tag || undefined}
                    showSearch
                    allowClear
                    optionFilterProp="label"
                    options={tagOptions.map((name) => ({
                      value: name,
                      label: name,
                    }))}
                    placeholder={t("aidpKnowledge.chunkTagsSelectPlaceholder")}
                    onChange={(value?: string) =>
                      setTagRows((current) =>
                        current.map((item, idx) =>
                          idx === index ? (value ?? "") : item
                        )
                      )
                    }
                    disabled={submitting}
                  />
                  <Button
                    type="text"
                    size="small"
                    aria-label={t("aidpKnowledge.chunkTagsRemoveRow")}
                    icon={<DeleteOutlined />}
                    disabled={submitting}
                    onClick={() =>
                      setTagRows((current) =>
                        current.filter((_, idx) => idx !== index)
                      )
                    }
                  />
                </div>
              ))}
              <Button
                type="link"
                size="small"
                className={styles.metadataAddRow}
                disabled={submitting || tagRows.length >= AIDP_TAG_LIMIT}
                onClick={() => setTagRows((current) => [...current, ""])}
              >
                {t("aidpKnowledge.chunkTagsAddRow", {
                  count: tagRows.length,
                  limit: AIDP_TAG_LIMIT,
                })}
              </Button>
            </div>
          )}
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
 * Only the text, metadata and tags are writable: AIDP takes `chunk_text` on
 * the chunk endpoints and applies tags/metadata through the batch-metadata
 * call. Tag choices and metadata keys come from the bound ontology domain.
 */
const AidpChunkDrawer: React.FC<AidpChunkDrawerProps> = ({
  open,
  mode,
  chunk,
  submitting,
  odId,
  metadataFields,
  tagOptions,
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
        odId={odId}
        metadataFields={metadataFields}
        tagOptions={tagOptions}
        onClose={onClose}
        onSubmit={onSubmit}
      />
    )}
  </Drawer>
);

export default AidpChunkDrawer;
