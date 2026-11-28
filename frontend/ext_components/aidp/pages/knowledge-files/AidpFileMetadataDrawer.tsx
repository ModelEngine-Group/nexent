// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Drawer } from "antd";
import { CloseOutlined } from "@ant-design/icons";

import type { AidpOntologyMetadataField } from "@/ext_components/aidp/shared/types/ontology";
import AidpMetadataEditor, { type AidpMetadataRow } from "./AidpMetadataEditor";
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

export interface AidpMetadataTargetFile {
  name: string;
  type?: string | null;
}

export interface AidpMetadataFormProps {
  title: string;
  hint: string;
  metadataFields: AidpOntologyMetadataField[];
  submitting: boolean;
  onClose: () => void;
  onSave: (metadataJson: Record<string, string>) => Promise<void>;
  /** Batch-file mode only; omit for chunk batches. */
  files?: AidpMetadataTargetFile[];
}

export const AidpMetadataForm: React.FC<AidpMetadataFormProps> = ({
  title,
  hint,
  metadataFields,
  submitting,
  onClose,
  onSave,
  files,
}) => {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AidpMetadataRow[]>([]);
  const [touched, setTouched] = useState(false);

  const metadataJson: Record<string, string> = {};
  for (const row of rows) {
    const value = row.value.trim();
    if (row.fieldName && value) metadataJson[row.fieldName] = value;
  }
  const canSubmit = !submitting && Object.keys(metadataJson).length > 0;

  const handleRowsChange = (next: AidpMetadataRow[]) => {
    setRows(next);
    setTouched(true);
  };

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
          <h2 className={styles.drawerTitle}>{title}</h2>
          <Button
            type="text"
            aria-label={t("common.close")}
            icon={<CloseOutlined />}
            onClick={onClose}
            disabled={submitting}
          />
        </div>
        <div className={styles.drawerContent}>
          <Alert type="info" showIcon title={hint} />
          {files && files.length > 0 && (
            <div className={styles.batchFileList}>
              <div className={styles.batchFileListTitle}>
                {t("aidpKnowledge.batchMetadataSelectedFiles", {
                  count: files.length,
                })}
              </div>
              {files.map((file, index) => (
                <div
                  className={styles.batchFileRow}
                  key={`${file.name}-${index}`}
                >
                  <span className={styles.batchFileName}>{file.name}</span>
                  {file.type && (
                    <span className={styles.batchFileType}>
                      /{file.type}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
          {metadataFields.length === 0 ? (
            <Alert
              type="info"
              showIcon
              title={t("aidpKnowledge.fileMetadataNoFields")}
            />
          ) : (
            <AidpMetadataEditor
              fields={metadataFields}
              rows={rows}
              onChange={handleRowsChange}
              submitting={submitting}
              showEmptyError={touched && Object.keys(metadataJson).length === 0}
            />
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
 * chunks are addressed upstream by UUID. The metadata editor is shared with
 * the chunk drawer so both entry points behave identically.
 */
const AidpFileMetadataDrawer: React.FC<AidpFileMetadataDrawerProps> = ({
  open,
  fileName,
  odId,
  metadataFields,
  submitting,
  onClose,
  onSave,
}) => {
  const { t } = useTranslation();

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
      mask={{ closable: !submitting }}
      keyboard={!submitting}
    >
      {open && (
        <AidpMetadataForm
          key={`${fileName}-${odId ?? "none"}`}
          title={t("aidpKnowledge.fileMetadataTitle")}
          hint={t("aidpKnowledge.fileMetadataHint", { name: fileName })}
          metadataFields={metadataFields}
          submitting={submitting}
          onClose={onClose}
          onSave={onSave}
        />
      )}
    </Drawer>
  );
};

export default AidpFileMetadataDrawer;
