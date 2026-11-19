// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { Alert, Button, ConfigProvider, Form, Input, Skeleton } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { aidpKnowledgeVisualTheme } from "@/ext_components/aidp/shared/styles/aidpKnowledgeVisualTheme";
import typography from "@/ext_components/aidp/shared/styles/aidpKnowledgeTypography.module.css";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import {
  ONTOLOGY_DESCRIPTION_MAX_BYTES,
  ONTOLOGY_NAME_MAX_BYTES,
  utf8ByteLength,
  validateOntologyDescription,
  validateOntologyName,
} from "@/ext_components/aidp/shared/utils/aidpOntologyValidation";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import styles from "./AidpOntologyCreatePage.module.css";

interface CreateFormValues {
  name: string;
  description?: string;
}

const MANAGER_ROLES = new Set(["SU", "ADMIN", "SPEED", "ASSET_OWNER"]);

const AidpOntologyCreatePage: React.FC = () => {
  const { t } = useTranslation();
  const router = useRouter();
  const params = useParams();
  const locale = (params?.locale as string) || "zh";
  const { user, isAuthzReady } = useAuthorizationContext();
  const canManage = !!user && MANAGER_ROLES.has(user.role);
  const [form] = Form.useForm<CreateFormValues>();
  const [saving, setSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const nameValue = (Form.useWatch("name", form) as string | undefined) ?? "";
  const descriptionValue =
    (Form.useWatch("description", form) as string | undefined) ?? "";

  const backToList = () => router.push(`/${locale}/knowledges/ontology`);

  const handleCreate = async () => {
    let values: CreateFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    setErrorMessage(null);
    try {
      const created = await aidpOntologyService.createDomain({
        name: values.name.trim(),
        description: (values.description ?? "").trim(),
      });
      if (created.domain_id) {
        router.push(
          `/${locale}/knowledges/ontology/${encodeURIComponent(created.domain_id)}`
        );
      } else {
        backToList();
      }
    } catch (error) {
      setErrorMessage(
        getAidpErrorMessage(
          error,
          t,
          t("aidpKnowledge.ontologyDomainCreateFailed")
        )
      );
    } finally {
      setSaving(false);
    }
  };

  if (!isAuthzReady) {
    return (
      <ConfigProvider theme={aidpKnowledgeVisualTheme}>
        <div className={`${typography.page} ${styles.page}`}>
          <Skeleton active paragraph={{ rows: 4 }} />
        </div>
      </ConfigProvider>
    );
  }

  if (!canManage) {
    return (
      <ConfigProvider theme={aidpKnowledgeVisualTheme}>
        <div className={`${typography.page} ${styles.page}`}>
          <Alert
            type="error"
            showIcon
            message={t("aidpKnowledge.ontologyNoManagePermission")}
            action={
              <Button onClick={backToList}>
                {t("aidpKnowledge.ontologyBackToList")}
              </Button>
            }
          />
        </div>
      </ConfigProvider>
    );
  }

  return (
    <ConfigProvider theme={aidpKnowledgeVisualTheme}>
      <div
        className={`${typography.page} ${styles.page} flex h-full min-h-0 w-full flex-col overflow-y-auto`}
      >
        <div className={styles.breadcrumb}>
          <Link
            href={`/${locale}/knowledges/ontology`}
            className={styles.backLink}
            aria-label={t("aidpKnowledge.ontologyBackToList")}
          >
            <ArrowLeftOutlined />
          </Link>
        </div>
        <div className={styles.headerRow}>
          <div>
            <h1 className={typography.pageTitle}>
              {t("aidpKnowledge.ontologyCreatePageTitle")}
            </h1>
          </div>
        </div>
        <section className={styles.panel}>
          <Form
            form={form}
            layout="vertical"
            requiredMark
            className={drawerStyles.form}
          >
            <Form.Item
              name="name"
              label={t("aidpKnowledge.ontologyDomainName")}
              extra={`${utf8ByteLength(nameValue)}/${ONTOLOGY_NAME_MAX_BYTES} ${t("aidpKnowledge.ontologyBytesUnit")}`}
              rules={[
                {
                  validator: async (_rule, value: string) => {
                    const error = validateOntologyName(value ?? "");
                    if (error) throw new Error(error);
                  },
                },
              ]}
            >
              <Input
                maxLength={ONTOLOGY_NAME_MAX_BYTES}
                placeholder={t("aidpKnowledge.ontologyDomainNamePlaceholder")}
              />
            </Form.Item>
            <Form.Item
              name="description"
              label={t("aidpKnowledge.ontologyDomainDescription")}
              extra={`${utf8ByteLength(descriptionValue)}/${ONTOLOGY_DESCRIPTION_MAX_BYTES} ${t("aidpKnowledge.ontologyBytesUnit")}`}
              rules={[
                {
                  validator: async (_rule, value: string) => {
                    const error = validateOntologyDescription(value ?? "");
                    if (error) throw new Error(error);
                  },
                },
              ]}
            >
              <Input.TextArea
                autoSize={{ minRows: 4, maxRows: 8 }}
                placeholder={t(
                  "aidpKnowledge.ontologyDomainDescriptionPlaceholder"
                )}
              />
            </Form.Item>
          </Form>
          {errorMessage && (
            <div className={drawerStyles.error} role="alert">
              {errorMessage}
            </div>
          )}
          <div className={styles.footer}>
            <Button onClick={backToList}>{t("common.cancel")}</Button>
            <Button
              type="primary"
              loading={saving}
              onClick={() => void handleCreate()}
            >
              {t("aidpKnowledge.ontologyCreateSubmit")}
            </Button>
          </div>
        </section>
      </div>
    </ConfigProvider>
  );
};

export default AidpOntologyCreatePage;
