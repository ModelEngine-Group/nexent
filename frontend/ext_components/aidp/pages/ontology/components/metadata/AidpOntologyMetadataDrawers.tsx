// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import {
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  Segmented,
  Select,
  Tooltip,
} from "antd";
import type { DescriptionsProps, FormInstance } from "antd";
import { DeleteOutlined, EditOutlined } from "@ant-design/icons";

import AidpOntologyFieldLabel from "@/ext_components/aidp/shared/components/AidpOntologyFieldLabel";
import type {
  AidpMetadataFieldType,
  AidpOntologyMetadataField,
} from "@/ext_components/aidp/shared/types/ontology";
import { validateFieldName } from "@/ext_components/aidp/shared/utils/aidpOntologyValidation";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import { AIDP_METADATA_TYPE_LABEL_KEYS } from "@/ext_components/aidp/pages/ontology/utils/aidpOntologyMetadata";
import styles from "./AidpOntologyMetadataFields.module.css";

export interface MetadataFieldFormValues {
  field_name: string;
  field_type: AidpMetadataFieldType;
}

const typeOptions = (t: TFunction) =>
  (["string", "number", "date"] as const).map((value) => ({
    value,
    label: t(AIDP_METADATA_TYPE_LABEL_KEYS[value]),
  }));

const nameRules = (t: TFunction) => [
  {
    validator: async (_rule: unknown, value: string) => {
      if (!(value ?? "").trim()) {
        throw new Error(t("aidpKnowledge.ontologyMetadataNameRequired"));
      }
      const error = validateFieldName(value ?? "", t);
      if (error) throw new Error(error);
    },
  },
];

export const AidpMetadataCreateDrawer: React.FC<{
  open: boolean;
  form: FormInstance<MetadataFieldFormValues>;
  saving: boolean;
  errorMessage: string | null;
  onClose: () => void;
  onCreate: () => void;
}> = ({ open, form, saving, errorMessage, onClose, onCreate }) => {
  const { t } = useTranslation();
  return (
    <Drawer
      rootClassName={drawerStyles.drawer}
      open={open}
      width={560}
      title={t("aidpKnowledge.ontologyMetadataCreateModalTitle")}
      onClose={onClose}
      destroyOnHidden
      footer={
        <div className={drawerStyles.footer}>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button type="primary" loading={saving} onClick={onCreate}>
            {t("common.confirm")}
          </Button>
        </div>
      }
    >
      <Form
        form={form}
        layout="vertical"
        className={drawerStyles.form}
        initialValues={{ field_type: "string" }}
      >
        <Form.Item
          name="field_name"
          label={
            <AidpOntologyFieldLabel
              label={t("aidpKnowledge.ontologyMetadataFieldName")}
              help={t("aidpKnowledge.ontologyMetadataFieldNameHelp")}
            />
          }
          required
          rules={nameRules(t)}
        >
          <Input maxLength={63} showCount />
        </Form.Item>
        <Form.Item
          name="field_type"
          label={
            <AidpOntologyFieldLabel
              label={t("aidpKnowledge.ontologyMetadataValueType")}
              help={t("aidpKnowledge.ontologyMetadataFieldTypeHelp")}
            />
          }
          required
          rules={[{ required: true }]}
        >
          <Segmented<AidpMetadataFieldType>
            block
            className={styles.typeSegmented}
            options={typeOptions(t)}
          />
        </Form.Item>
        {errorMessage && (
          <div className={drawerStyles.error} role="alert">
            {errorMessage}
          </div>
        )}
      </Form>
    </Drawer>
  );
};

export const AidpMetadataEditDrawer: React.FC<{
  field: AidpOntologyMetadataField | null;
  form: FormInstance<MetadataFieldFormValues>;
  saving: boolean;
  errorMessage: string | null;
  onClose: () => void;
  onSave: () => void;
}> = ({ field, form, saving, errorMessage, onClose, onSave }) => {
  const { t } = useTranslation();
  return (
    <Drawer
      rootClassName={drawerStyles.drawer}
      open={!!field}
      width={560}
      onClose={onClose}
      destroyOnHidden
      title={t("aidpKnowledge.ontologyMetadataEditTitle")}
      footer={
        <div className={drawerStyles.footer}>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button type="primary" loading={saving} onClick={onSave}>
            {t("aidpKnowledge.ontologyMetadataSave")}
          </Button>
        </div>
      }
    >
      <Form
        key={field ? `edit-${field.id ?? field.field_name}` : "closed"}
        form={form}
        layout="vertical"
        className={drawerStyles.form}
        initialValues={{
          field_name: field?.field_name ?? "",
          field_type: field?.field_type ?? "string",
        }}
      >
        <Form.Item
          name="field_name"
          label={
            <AidpOntologyFieldLabel
              label={t("aidpKnowledge.ontologyMetadataFieldName")}
              help={t("aidpKnowledge.ontologyMetadataFieldNameHelp")}
            />
          }
          rules={nameRules(t)}
        >
          <Input maxLength={63} />
        </Form.Item>
        <Form.Item
          name="field_type"
          label={
            <AidpOntologyFieldLabel
              label={t("aidpKnowledge.ontologyMetadataFieldType")}
              help={t("aidpKnowledge.ontologyMetadataFieldTypeHelp")}
            />
          }
          rules={[{ required: true }]}
        >
          <Select disabled options={typeOptions(t)} />
        </Form.Item>
        {errorMessage && (
          <div className={drawerStyles.error} role="alert">
            {errorMessage}
          </div>
        )}
      </Form>
    </Drawer>
  );
};

export const AidpMetadataDetailDrawer: React.FC<{
  field: AidpOntologyMetadataField | null;
  items: DescriptionsProps["items"];
  onClose: () => void;
  onEdit: (field: AidpOntologyMetadataField) => void;
  onDelete: (field: AidpOntologyMetadataField) => void;
}> = ({ field, items, onClose, onEdit, onDelete }) => {
  const { t } = useTranslation();
  return (
    <Drawer
      rootClassName={drawerStyles.drawer}
      open={!!field}
      width={560}
      mask={false}
      onClose={onClose}
      destroyOnHidden
      title={field?.field_name ?? t("aidpKnowledge.ontologyMetadataDetailTitle")}
      extra={
        field ? (
          <div className={styles.headerActions}>
            <Tooltip title={t("aidpKnowledge.ontologyMetadataEdit")}>
              <Button
                type="text"
                size="small"
                aria-label={t("aidpKnowledge.ontologyMetadataEdit")}
                icon={<EditOutlined />}
                onClick={() => {
                  onClose();
                  onEdit(field);
                }}
              />
            </Tooltip>
            <Tooltip title={t("aidpKnowledge.ontologyMetadataDelete")}>
              <Button
                type="text"
                size="small"
                aria-label={t("aidpKnowledge.ontologyMetadataDelete")}
                icon={<DeleteOutlined />}
                onClick={() => {
                  onClose();
                  onDelete(field);
                }}
              />
            </Tooltip>
          </div>
        ) : null
      }
    >
      {field && (
        <div className={styles.detailBody}>
          <Descriptions size="small" column={1} bordered items={items} />
        </div>
      )}
    </Drawer>
  );
};
