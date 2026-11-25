// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, DatePicker, Input, Modal, Select, Tooltip } from "antd";
import { DeleteOutlined, InfoCircleOutlined } from "@ant-design/icons";
import dayjs from "dayjs";

import type { AidpOntologyMetadataField } from "@/ext_components/aidp/shared/types/ontology";
import styles from "./AidpSemanticChunks.module.css";

export const AIDP_METADATA_ROW_LIMIT = 20;

export interface AidpMetadataRow {
  fieldName: string;
  value: string;
}

interface AidpMetadataEditorProps {
  /** Metadata fields defined by the bound ontology domain. */
  fields: AidpOntologyMetadataField[];
  rows: AidpMetadataRow[];
  onChange: (rows: AidpMetadataRow[]) => void;
  submitting?: boolean;
  /** Consumer decides when the "at least one field" error should show. */
  showEmptyError?: boolean;
}

/**
 * Metadata rows editor shared by chunk editing and whole-file metadata.
 *
 * Each row picks one ontology field, shows its declared type and edits a
 * value with the matching control. The JSON dialog is generated from the
 * current rows, validates syntax plus ontology keys on confirm, and then
 * renders the parsed map back into the rows.
 */
const AidpMetadataEditor: React.FC<AidpMetadataEditorProps> = ({
  fields,
  rows,
  onChange,
  submitting = false,
  showEmptyError = false,
}) => {
  const { t } = useTranslation();
  const [jsonOpen, setJsonOpen] = useState(false);
  const [jsonDraft, setJsonDraft] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);

  const usedFields = useMemo(
    () => new Set(rows.map((row) => row.fieldName)),
    [rows]
  );
  const addableFields = fields.filter(
    (field) => !usedFields.has(field.field_name)
  );

  const handleAddRow = () => {
    const next = addableFields[0];
    if (!next || rows.length >= AIDP_METADATA_ROW_LIMIT) return;
    onChange([...rows, { fieldName: next.field_name, value: "" }]);
  };

  const handleRemoveRow = (index: number) => {
    onChange(rows.filter((_, idx) => idx !== index));
  };

  const handleRowFieldChange = (index: number, fieldName: string) => {
    onChange(
      rows.map((row, idx) =>
        idx === index ? { ...row, fieldName, value: "" } : row
      )
    );
  };

  const handleRowValueChange = (index: number, value: string) => {
    onChange(rows.map((row, idx) => (idx === index ? { ...row, value } : row)));
  };

  const handleApplyJson = () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(jsonDraft || "{}");
    } catch {
      setJsonError(t("aidpKnowledge.chunkMetadataJsonInvalid"));
      return;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      setJsonError(t("aidpKnowledge.chunkMetadataJsonInvalid"));
      return;
    }
    const entries = Object.entries(parsed as Record<string, unknown>);
    const matched: AidpMetadataRow[] = [];
    for (const [key, raw] of entries) {
      if (!fields.some((field) => field.field_name === key)) continue;
      if (raw === null || raw === undefined) {
        matched.push({ fieldName: key, value: "" });
        continue;
      }
      if (typeof raw !== "string" && typeof raw !== "number") continue;
      matched.push({ fieldName: key, value: String(raw) });
    }
    // Every key must be an ontology field with a scalar value; silently
    // dropping part of the user's JSON would hide the mistake.
    if (matched.length !== entries.length) {
      setJsonError(t("aidpKnowledge.chunkMetadataJsonUnmatched"));
      return;
    }
    // The JSON is the metadata map itself: render exactly those fields back
    // into the form, in its order.
    onChange(matched.slice(0, AIDP_METADATA_ROW_LIMIT));
    setJsonOpen(false);
    setJsonDraft("");
    setJsonError(null);
  };

  const renderValueControl = (row: AidpMetadataRow, index: number) => {
    const field = fields.find((item) => item.field_name === row.fieldName);
    if (field?.field_type === "date") {
      return (
        <DatePicker
          className={styles.metadataFieldControl}
          value={row.value ? dayjs(row.value) : null}
          onChange={(date) =>
            handleRowValueChange(index, date ? date.format("YYYY-MM-DD") : "")
          }
          placeholder={t("aidpKnowledge.chunkMetadataDatePlaceholder")}
          disabled={submitting}
        />
      );
    }
    return (
      <Input
        className={styles.metadataFieldControl}
        value={row.value}
        onChange={(event) => handleRowValueChange(index, event.target.value)}
        placeholder={
          field?.field_type === "number"
            ? t("aidpKnowledge.chunkMetadataNumberPlaceholder")
            : t("aidpKnowledge.chunkMetadataTextPlaceholder")
        }
        disabled={submitting}
      />
    );
  };

  return (
    <div>
      <div className={styles.fieldLabelRow}>
        <span className={styles.fieldLabel}>
          {t("aidpKnowledge.chunkMetadata")}
        </span>
        <Tooltip title={t("aidpKnowledge.chunkMetadataSchemaHint")}>
          <InfoCircleOutlined className={styles.fieldInfoIcon} />
        </Tooltip>
        <Button
          type="primary"
          size="small"
          className={styles.jsonButton}
          disabled={submitting}
          onClick={() => {
            const current: Record<string, string> = {};
            for (const row of rows) {
              if (!row.fieldName) continue;
              current[row.fieldName] = row.value.trim();
            }
            setJsonDraft(JSON.stringify(current, null, 2));
            setJsonError(null);
            setJsonOpen(true);
          }}
        >
          {t("aidpKnowledge.chunkMetadataInputJson")}
        </Button>
      </div>
      <div className={styles.metadataTableHead}>
        <span className={styles.headRequired}>
          {t("aidpKnowledge.chunkMetadataFieldName")}
        </span>
        <Tooltip title={t("aidpKnowledge.chunkMetadataTypeHint")}>
          <span>{t("aidpKnowledge.chunkMetadataType")}</span>
        </Tooltip>
        <span>{t("aidpKnowledge.chunkMetadataValue")}</span>
        <span>{t("aidpKnowledge.chunkMetadataOperation")}</span>
      </div>
      {rows.map((row, index) => {
        const field = fields.find((item) => item.field_name === row.fieldName);
        return (
          <div
            key={`${row.fieldName}-${index}`}
            className={styles.metadataTableRow}
          >
            <Select
              className={styles.metadataFieldControl}
              value={row.fieldName}
              showSearch
              optionFilterProp="label"
              options={fields
                .filter(
                  (item) =>
                    item.field_name === row.fieldName ||
                    !usedFields.has(item.field_name)
                )
                .map((item) => ({
                  value: item.field_name,
                  label: item.field_name,
                }))}
              onChange={(value: string) => handleRowFieldChange(index, value)}
              disabled={submitting}
            />
            <span className={styles.metadataTypeCell}>
              {field?.field_type ?? "—"}
            </span>
            {renderValueControl(row, index)}
            <Button
              type="text"
              size="small"
              aria-label={t("aidpKnowledge.chunkMetadataRemoveRow")}
              icon={<DeleteOutlined />}
              disabled={submitting}
              onClick={() => handleRemoveRow(index)}
            />
          </div>
        );
      })}
      <Button
        type="link"
        size="small"
        className={styles.metadataAddRow}
        disabled={
          submitting ||
          addableFields.length === 0 ||
          rows.length >= AIDP_METADATA_ROW_LIMIT
        }
        onClick={handleAddRow}
      >
        {t("aidpKnowledge.chunkMetadataAddRow", {
          count: rows.length,
          limit: AIDP_METADATA_ROW_LIMIT,
        })}
      </Button>
      {showEmptyError && (
        <p className={styles.errorText}>
          {t("aidpKnowledge.chunkMetadataAtLeastOne")}
        </p>
      )}

      <Modal
        open={jsonOpen}
        title={t("aidpKnowledge.chunkMetadataJsonTitle")}
        okText={t("aidpKnowledge.chunkMetadataJsonApply")}
        cancelText={t("common.cancel")}
        onOk={handleApplyJson}
        onCancel={() => setJsonOpen(false)}
        destroyOnHidden
      >
        <p className={styles.formHint}>
          {t("aidpKnowledge.chunkMetadataJsonHint")}
        </p>
        <Input.TextArea
          rows={8}
          value={jsonDraft}
          onChange={(event) => {
            setJsonDraft(event.target.value);
            setJsonError(null);
          }}
          placeholder='{"field_name": "value"}'
        />
        {jsonError && <p className={styles.errorText}>{jsonError}</p>}
      </Modal>
    </div>
  );
};

export default AidpMetadataEditor;
