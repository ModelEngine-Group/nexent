// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Drawer, Form, Input } from "antd";

import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import {
  ONTOLOGY_DESCRIPTION_MAX_CHARS,
  ONTOLOGY_NAME_MAX_CHARS,
  validateOntologyDescription,
  validateOntologyName,
} from "@/ext_components/aidp/shared/utils/aidpOntologyValidation";
import type { AidpOntologyDomain } from "@/ext_components/aidp/shared/types/ontology";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import styles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import AidpOntologyFieldLabel from "@/ext_components/aidp/shared/components/AidpOntologyFieldLabel";

interface AidpOntologyDomainDrawerProps {
  open: boolean;
  domain: AidpOntologyDomain | null;
  onClose: () => void;
  onSaved: (domain: AidpOntologyDomain) => void;
}

interface DomainFormValues {
  name: string;
  description?: string;
}

const AidpOntologyDomainDrawer: React.FC<AidpOntologyDomainDrawerProps> = ({
  open,
  domain,
  onClose,
  onSaved,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [form] = Form.useForm<DomainFormValues>();
  const [saving, setSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const nameValue = (Form.useWatch("name", form) as string | undefined) ?? "";
  const descriptionValue =
    (Form.useWatch("description", form) as string | undefined) ?? "";
  const nameLength = nameValue.length;
  const descriptionLength = descriptionValue.length;
  const editing = !!domain;

  const handleClose = () => {
    setErrorMessage(null);
    setSaving(false);
    onClose();
  };

  const handleSubmit = async () => {
    let values: DomainFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    setErrorMessage(null);
    try {
      const payload = {
        name: values.name.trim(),
        description: (values.description ?? "").trim(),
      };
      const saved = domain
        ? await aidpOntologyService.updateDomain(domain.domain_id, payload)
        : await aidpOntologyService.createDomain(payload);
      message.success(
        editing
          ? t("aidpKnowledge.ontologyDomainUpdated")
          : t("aidpKnowledge.ontologyDomainCreated")
      );
      onSaved(saved);
    } catch (error) {
      setErrorMessage(
        getAidpErrorMessage(
          error,
          t,
          editing
            ? t("aidpKnowledge.ontologyDomainUpdateFailed")
            : t("aidpKnowledge.ontologyDomainCreateFailed")
        )
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Drawer
      rootClassName={styles.drawer}
      open={open}
      width={560}
      onClose={handleClose}
      destroyOnHidden
      title={
        editing
          ? t("aidpKnowledge.ontologyDomainEditTitle")
          : t("aidpKnowledge.ontologyDomainCreateTitle")
      }
      footer={
        <div className={styles.footer}>
          <Button onClick={handleClose}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            loading={saving}
            onClick={() => void handleSubmit()}
          >
            {t("common.confirm")}
          </Button>
        </div>
      }
    >
      <Form
        key={open ? `open-${domain?.domain_id ?? "new"}` : "closed"}
        form={form}
        layout="vertical"
        className={styles.form}
        initialValues={{
          name: domain?.name ?? "",
          description: domain?.description ?? "",
        }}
      >
        <Form.Item
          name="name"
          required
          label={
            <AidpOntologyFieldLabel
              label={t("aidpKnowledge.ontologyDomainName")}
              help={t("aidpKnowledge.ontologyDomainNameHint")}
            />
          }
          extra={`${nameLength}/${ONTOLOGY_NAME_MAX_CHARS} ${t("aidpKnowledge.ontologyBytesUnit")}`}
          rules={[
            {
              validator: async (_rule, value: string) => {
                const error = validateOntologyName(value ?? "");
                if (error) throw new Error(error);
              },
            },
          ]}
        >
          <Input maxLength={ONTOLOGY_NAME_MAX_CHARS} />
        </Form.Item>
        <Form.Item
          name="description"
          label={
            <AidpOntologyFieldLabel
              label={t("aidpKnowledge.ontologyDomainDescription")}
              help={t("aidpKnowledge.ontologyDomainDescriptionHint")}
            />
          }
          extra={`${descriptionLength}/${ONTOLOGY_DESCRIPTION_MAX_CHARS} ${t("aidpKnowledge.ontologyBytesUnit")}`}
          rules={[
            {
              validator: async (_rule, value: string) => {
                const error = validateOntologyDescription(value ?? "");
                if (error) throw new Error(error);
              },
            },
          ]}
        >
          <Input.TextArea autoSize={{ minRows: 3, maxRows: 6 }} />
        </Form.Item>
        {errorMessage && (
          <div className={styles.error} role="alert">
            {errorMessage}
          </div>
        )}
      </Form>
    </Drawer>
  );
};

export default AidpOntologyDomainDrawer;
