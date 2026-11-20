// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Input, Modal } from "antd";

import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import type { AidpOntologyDomain } from "@/ext_components/aidp/shared/types/ontology";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import styles from "./AidpOntologyDeleteModal.module.css";

interface AidpOntologyDeleteModalProps {
  open: boolean;
  domain: AidpOntologyDomain | null;
  onClose: () => void;
  onDeleted: (domain: AidpOntologyDomain) => void;
}

const CONFIRM_TEXT = "删除";

const AidpOntologyDeleteModal: React.FC<AidpOntologyDeleteModalProps> = ({
  open,
  domain,
  onClose,
  onDeleted,
}) => {
  const { t } = useTranslation();
  const [confirmText, setConfirmText] = React.useState("");
  const [deleting, setDeleting] = React.useState(false);
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);

  const reset = () => {
    setConfirmText("");
    setDeleting(false);
    setErrorMessage(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const handleDelete = async () => {
    if (!domain || confirmText.trim() !== CONFIRM_TEXT) return;
    setDeleting(true);
    setErrorMessage(null);
    try {
      await aidpOntologyService.deleteDomain(domain.domain_id);
      reset();
      onDeleted(domain);
    } catch (error) {
      setErrorMessage(
        getAidpErrorMessage(
          error,
          t,
          t("aidpKnowledge.ontologyDomainDeleteFailed")
        )
      );
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Modal
      open={open}
      width={480}
      centered
      destroyOnHidden
      title={t("aidpKnowledge.ontologyDomainDeleteTitleFixed")}
      onCancel={handleClose}
      okText={t("aidpKnowledge.ontologyDomainDeleteSubmit")}
      cancelText={t("common.cancel")}
      okButtonProps={{
        disabled: confirmText.trim() !== CONFIRM_TEXT,
        loading: deleting,
      }}
      onOk={() => void handleDelete()}
    >
      <div className={styles.body}>
        <p className={styles.description}>
          {t("aidpKnowledge.ontologyDomainDeleteContent", {
            name: domain?.name ?? "",
          })}
        </p>
        <AidpOntologyGapNote>
          {t("aidpKnowledge.ontologyDomainDeleteCascadeGap")}
        </AidpOntologyGapNote>
        <div className={styles.confirmBlock}>
          <div className={styles.confirmLabel}>
            {t("aidpKnowledge.ontologyDomainDeleteInputLabel")}
          </div>
          <Input
            value={confirmText}
            placeholder={t(
              "aidpKnowledge.ontologyDomainDeleteInputPlaceholder"
            )}
            onChange={(event) => setConfirmText(event.target.value)}
            onPressEnter={() => void handleDelete()}
            autoFocus
          />
        </div>
        {errorMessage && (
          <div className={drawerStyles.error} role="alert">
            {errorMessage}
          </div>
        )}
      </div>
    </Modal>
  );
};

export default AidpOntologyDeleteModal;
