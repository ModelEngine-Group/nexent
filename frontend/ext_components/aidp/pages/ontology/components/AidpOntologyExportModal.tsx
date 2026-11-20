// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Modal, Select, Switch } from "antd";

import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type { AidpOntologyKind } from "@/ext_components/aidp/shared/types/ontology";
import styles from "./AidpOntologyExportModal.module.css";

interface AidpOntologyExportModalProps {
  open: boolean;
  domainId: string;
  domainName: string;
  onClose: () => void;
}

const AidpOntologyExportModal: React.FC<AidpOntologyExportModalProps> = ({
  open,
  domainId,
  domainName,
  onClose,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [includeProperties, setIncludeProperties] = useState(true);
  const [includeRelations, setIncludeRelations] = useState(true);
  const [kind, setKind] = useState<AidpOntologyKind | "all">("all");
  const [exporting, setExporting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const resetAndClose = () => {
    setIncludeProperties(true);
    setIncludeRelations(true);
    setKind("all");
    setErrorMessage(null);
    setExporting(false);
    onClose();
  };

  const handleExport = async () => {
    setExporting(true);
    setErrorMessage(null);
    try {
      const result = await aidpOntologyService.exportDomain(domainId, {
        include_properties: includeProperties,
        include_relations: includeRelations,
        kind: kind === "all" ? null : kind,
      });
      if (result.accepted) {
        message.info(
          t("aidpKnowledge.ontologyExportAccepted", {
            taskId: result.task_id ?? "",
          }),
          8
        );
        resetAndClose();
        return;
      }
      aidpOntologyService.downloadExport(result);
      message.success(t("aidpKnowledge.ontologyExportSuccess"));
      resetAndClose();
    } catch (error) {
      setErrorMessage(
        getAidpErrorMessage(error, t, t("aidpKnowledge.ontologyExportFailed"))
      );
    } finally {
      setExporting(false);
    }
  };

  return (
    <Modal
      open={open}
      width={480}
      centered
      destroyOnHidden
      title={t("aidpKnowledge.ontologyExportTitle")}
      onCancel={resetAndClose}
      footer={
        <div className={styles.footer}>
          <Button onClick={resetAndClose}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            loading={exporting}
            onClick={() => void handleExport()}
          >
            {t("aidpKnowledge.ontologyExportSubmit")}
          </Button>
        </div>
      }
    >
      <div className={styles.body}>
        <div className={styles.target}>
          {t("aidpKnowledge.ontologyExportTarget", { name: domainName })}
        </div>
        <label className={styles.row}>
          <span>{t("aidpKnowledge.ontologyExportIncludeProperties")}</span>
          <Switch
            checked={includeProperties}
            onChange={setIncludeProperties}
            aria-label={t("aidpKnowledge.ontologyExportIncludeProperties")}
          />
        </label>
        <label className={styles.row}>
          <span>{t("aidpKnowledge.ontologyExportIncludeRelations")}</span>
          <Switch
            checked={includeRelations}
            onChange={setIncludeRelations}
            aria-label={t("aidpKnowledge.ontologyExportIncludeRelations")}
          />
        </label>
        <label className={styles.row}>
          <span>{t("aidpKnowledge.ontologyExportKind")}</span>
          <Select
            className={styles.kindSelect}
            value={kind}
            onChange={setKind}
            options={[
              { value: "all", label: t("aidpKnowledge.ontologyExportKindAll") },
              {
                value: "type",
                label: t("aidpKnowledge.ontologyEntityKindType"),
              },
              {
                value: "entity",
                label: t("aidpKnowledge.ontologyEntityKindEntity"),
              },
            ]}
          />
        </label>
        {errorMessage && (
          <div className={styles.error} role="alert">
            {errorMessage}
          </div>
        )}
      </div>
    </Modal>
  );
};

export default AidpOntologyExportModal;
