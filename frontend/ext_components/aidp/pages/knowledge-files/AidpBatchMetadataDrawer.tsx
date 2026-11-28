// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Drawer } from "antd";

import type { AidpOntologyMetadataField } from "@/ext_components/aidp/shared/types/ontology";
import {
  AidpMetadataForm,
  type AidpMetadataTargetFile,
} from "./AidpFileMetadataDrawer";
import styles from "./AidpSemanticChunks.module.css";

interface AidpBatchMetadataDrawerProps {
  open: boolean;
  metadataFields: AidpOntologyMetadataField[];
  submitting: boolean;
  onClose: () => void;
  onSave: (metadataJson: Record<string, string>) => Promise<void>;
  /** Batch-file mode only; omit for chunk batches. */
  files?: AidpMetadataTargetFile[];
  /** Chunk mode only; shown in the hint. */
  chunkCount?: number;
  /** Reset the metadata rows when the selection changes. */
  formKey?: string;
}

/** Batch metadata editor shared by the file list and the chunk panel. */
const AidpBatchMetadataDrawer: React.FC<AidpBatchMetadataDrawerProps> = ({
  open,
  metadataFields,
  submitting,
  onClose,
  onSave,
  files,
  chunkCount = 0,
  formKey,
}) => {
  const { t } = useTranslation();
  const isFileBatch = (files?.length ?? 0) > 0;

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
          key={formKey}
          title={t("aidpKnowledge.batchMetadataTitle")}
          hint={
            isFileBatch
              ? t("aidpKnowledge.batchMetadataFileHint")
              : t("aidpKnowledge.batchMetadataChunkHint", {
                  count: chunkCount,
                })
          }
          metadataFields={metadataFields}
          submitting={submitting}
          onClose={onClose}
          onSave={onSave}
          files={isFileBatch ? files : undefined}
        />
      )}
    </Drawer>
  );
};

export default AidpBatchMetadataDrawer;
