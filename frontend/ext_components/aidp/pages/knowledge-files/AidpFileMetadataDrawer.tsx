// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Drawer, Input } from "antd";
import { CloseOutlined } from "@ant-design/icons";

import type { AidpOntologyMetadataField } from "@/ext_components/aidp/shared/types/ontology";
import styles from "./AidpSemanticChunks.module.css";

interface AidpFileMetadataDrawerProps {
  open: boolean;
  fileName: string;
  /** Bound ontology domain; the drawer only opens while a binding exists. */
  odId: number | string | null;
  metadataFields: AidpOntologyMetadataField[];
  submitting: boolean;
  onClose: () => void;
  /** Values apply to every chunk of the file (AIDP file_uuid_list variant). */
  onSave: (metadataJson: Record<string, string>) => Promise<void>;
}

const AidpFileMetadataForm: React.FC<
  Omit<AidpFileMetadataDrawerProps, "open">
> = ({ fileName, metadataFields, submitting, onClose, onSave }) => {
  const { t } = useTranslation();
  const [values, setValues] = useState<Record<string, string>>({});
  const [touched, setTouched] = useState(false);

  const metadataJson: Record<string, string> = {};
  for (const field of metadataFields) {
    const value = (values[field.field_name] ?? "").trim();
    if (value) metadataJson[field.field_name] = value;
  }
  const canSubmit = !submitting && Object.keys(metadataJson).length > 0;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    try {
      await onSave(metadataJson);
    } catch {
      // The parent reports the failure; keep the entered values for retry.
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className={styles.drawerTitleRow}>
          <h2 className={styles.drawerTitle}>
            {t("aidpKnowledge.fileMetadataTitle")}
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
          <p className={styles.formHint}>
            {t("aidpKnowledge.fileMetadataHint", { name: fileName })}
          </p>
          {metadataFields.length === 0 ? (
            <Alert
              type="info"
              showIcon
              title={t("aidpKnowledge.fileMetadataNoFields")}
            />
          ) : (
            metadataFields.map((field) => (
              <div key={field.field_name} className={styles.metadataFieldRow}>
                <span className={styles.metadataFieldLabel}>
                  {field.field_name}
                </span>
                <Input
                  className={styles.metadataFieldControl}
                  value={values[field.field_name] ?? ""}
                  onChange={(event) => {
                    setValues((current) => ({
                      ...current,
                      [field.field_name]: event.target.value,
                    }));
                    setTouched(true);
                  }}
                  placeholder={
                    field.field_type === "number"
                      ? t("aidpKnowledge.chunkMetadataNumberPlaceholder")
                      : field.field_type === "date"
                        ? t("aidpKnowledge.chunkMetadataDatePlaceholder")
                        : t("aidpKnowledge.chunkMetadataTextPlaceholder")
                  }
                  disabled={submitting}
                />
              </div>
            ))
          )}
          {touched && Object.keys(metadataJson).length === 0 && (
            <p className={styles.errorText}>
              {t("aidpKnowledge.chunkMetadataAtLeastOne")}
            </p>
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
 * Apply user metadata to every chunk of one ingested file.
 *
 * AIDP exposes this as the batch-metadata `file_uuid_list` variant, so the
 * page only needs the field definitions of the bound domain; the file's
 * chunks are addressed upstream by UUID.
 */
const AidpFileMetadataDrawer: React.FC<AidpFileMetadataDrawerProps> = ({
  open,
  fileName,
  odId,
  metadataFields,
  submitting,
  onClose,
  onSave,
}) => (
  <Drawer
    open={open}
    onClose={onClose}
    size="min(720px, 42vw)"
    rootClassName={styles.chunkDrawer}
    closable={false}
    styles={{ body: { padding: 0, display: "flex", flexDirection: "column" } }}
    mask={{ closable: !submitting }}
    keyboard={!submitting}
  >
    {open && (
      <AidpFileMetadataForm
        key={`${fileName}-${odId ?? "none"}`}
        fileName={fileName}
        odId={odId}
        metadataFields={metadataFields}
        submitting={submitting}
        onClose={onClose}
        onSave={onSave}
      />
    )}
  </Drawer>
);

export default AidpFileMetadataDrawer;
