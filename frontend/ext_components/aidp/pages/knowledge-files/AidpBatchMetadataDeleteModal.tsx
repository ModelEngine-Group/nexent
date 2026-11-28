// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Checkbox, Modal } from "antd";

import type { AidpOntologyMetadataField } from "@/ext_components/aidp/shared/types/ontology";
import styles from "./AidpSemanticChunks.module.css";

const MAX_DELETE_FIELDS = 20;

interface AidpBatchMetadataDeleteModalProps {
  open: boolean;
  metadataFields: AidpOntologyMetadataField[];
  count: number;
  mode: "file" | "chunk";
  submitting: boolean;
  onClose: () => void;
  onSubmit: (keys: string[]) => Promise<void>;
}

/**
 * Delete selected metadata fields from every chunk in the chosen scope.
 *
 * AIDP removes a field when its value is null, so the request carries one
 * null value per selected field. The ontology field definition is untouched.
 */
const AidpBatchMetadataDeleteModal: React.FC<
  AidpBatchMetadataDeleteModalProps
> = ({ open, metadataFields, count, mode, submitting, onClose, onSubmit }) => {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const fields = useMemo(
    () => metadataFields.map((field) => field.field_name),
    [metadataFields]
  );
  const atLimit = selected.size >= MAX_DELETE_FIELDS;
  const allSelected = fields.length > 0 && selected.size === fields.length;

  const toggleAll = (checked: boolean) => {
    setSelected(
      checked ? new Set(fields.slice(0, MAX_DELETE_FIELDS)) : new Set()
    );
  };

  const toggleOne = (fieldName: string, checked: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(fieldName);
      else next.delete(fieldName);
      return next;
    });
  };

  const handleSubmit = async () => {
    if (selected.size === 0) return;
    try {
      await onSubmit(Array.from(selected));
    } catch {
      // The parent reports the failure; keep the selection for retry.
    }
  };

  return (
    <Modal
      open={open}
      centered
      width={608}
      destroyOnHidden
      closable={false}
      mask={{ closable: !submitting }}
      keyboard={!submitting}
      onCancel={() => {
        if (!submitting) onClose();
      }}
      footer={null}
      styles={{ container: { padding: 0, borderRadius: 8 } }}
    >
      <div className={styles.deleteDialog}>
        <h2 className={styles.deleteTitle}>
          {t("aidpKnowledge.batchMetadataDeleteTitle")}
        </h2>
        <p className={styles.deleteBody}>
          {mode === "file"
            ? t("aidpKnowledge.batchMetadataDeleteFileHint", { count })
            : t("aidpKnowledge.batchMetadataDeleteChunkHint", { count })}
        </p>
        {fields.length === 0 ? (
          <Alert
            type="info"
            showIcon
            title={t("aidpKnowledge.batchMetadataDeleteNoFields")}
          />
        ) : (
          <>
            <div className={styles.batchFieldSelectAll}>
              <Checkbox
                checked={allSelected}
                indeterminate={selected.size > 0 && !allSelected}
                onChange={(event) => toggleAll(event.target.checked)}
              >
                {t("aidpKnowledge.chunksSelectAll")}
              </Checkbox>
              <span className={styles.batchFieldCount}>
                {t("aidpKnowledge.batchMetadataDeleteSelected", {
                  selected: selected.size,
                  total: fields.length,
                })}
              </span>
            </div>
            {fields.length > MAX_DELETE_FIELDS && (
              <Alert
                type="info"
                showIcon
                title={t("aidpKnowledge.batchMetadataDeleteLimit", {
                  max: MAX_DELETE_FIELDS,
                })}
              />
            )}
            <div className={styles.batchFieldList}>
              {fields.map((fieldName) => (
                <div className={styles.batchFieldRow} key={fieldName}>
                  <Checkbox
                    checked={selected.has(fieldName)}
                    disabled={!selected.has(fieldName) && atLimit}
                    onChange={(event) =>
                      toggleOne(fieldName, event.target.checked)
                    }
                  >
                    {fieldName}
                  </Checkbox>
                </div>
              ))}
            </div>
            <p className={styles.deleteImpact}>
              {t("aidpKnowledge.batchMetadataDeleteImpact")}
            </p>
          </>
        )}
        <div className={styles.deleteActions}>
          <Button onClick={onClose} disabled={submitting}>
            {t("common.cancel")}
          </Button>
          <Button
            danger
            loading={submitting}
            disabled={selected.size === 0}
            onClick={() => void handleSubmit()}
          >
            {t("aidpKnowledge.batchMetadataDeleteConfirm")}
          </Button>
        </div>
      </div>
    </Modal>
  );
};

export default AidpBatchMetadataDeleteModal;
