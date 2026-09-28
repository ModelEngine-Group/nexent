import React from "react";
import { Button, Form, Input, Select } from "antd";
import type { TFunction } from "i18next";

import { AIDP_KNOWLEDGE_BASE_NAME_PATTERN } from "@/const/knowledgeBase";
import type { AidpGroupOption } from "../hooks/useAidpGroupOptions";

export const AIDP_MODAL_STYLES = {
  container: { overflow: "hidden", borderRadius: 16, padding: 0 },
  body: { padding: 0 },
  footer: {
    margin: 0,
    padding: "12px 20px 16px",
    borderTop: "1px solid #f0f0f0",
  },
};

interface AidpModalHeaderProps {
  title: string;
  subtitle: string;
}

export const AidpKnowledgeBaseModalHeader: React.FC<AidpModalHeaderProps> = ({
  title,
  subtitle,
}) => (
  <div
    className="border-b border-gray-200"
    style={{ padding: "24px 24px 20px" }}
  >
    <h2 className="text-xl font-semibold tracking-tight text-gray-900">
      {title}
    </h2>
    <p className="mt-1 text-sm text-gray-500">{subtitle}</p>
  </div>
);

interface AidpModalFooterProps {
  onCancel: () => void;
  onSubmit: () => void;
  loading: boolean;
  cancelText: string;
  submitText: string;
}

export const AidpKnowledgeBaseModalFooter: React.FC<AidpModalFooterProps> = ({
  onCancel,
  onSubmit,
  loading,
  cancelText,
  submitText,
}) => (
  <div className="flex justify-end gap-3">
    <Button onClick={onCancel} disabled={loading}>
      {cancelText}
    </Button>
    <Button type="primary" loading={loading} onClick={onSubmit}>
      {submitText}
    </Button>
  </div>
);

interface AidpKnowledgeBaseBasicFieldsProps {
  t: TFunction;
}

export const AidpKnowledgeBaseBasicFields: React.FC<
  AidpKnowledgeBaseBasicFieldsProps
> = ({ t }) => (
  <>
    <Form.Item
      name="name"
      label={t("aidpKnowledge.kbName")}
      rules={[
        { required: true, message: t("aidpKnowledge.kbNameRequired") },
        {
          pattern: AIDP_KNOWLEDGE_BASE_NAME_PATTERN,
          message: t("aidpKnowledge.kbNameInvalid"),
        },
      ]}
    >
      <Input placeholder={t("aidpKnowledge.kbNamePlaceholder")} />
    </Form.Item>
    <Form.Item name="description" label={t("aidpKnowledge.kbDescription")}>
      <Input.TextArea
        rows={3}
        placeholder={t("aidpKnowledge.kbDescriptionPlaceholder")}
      />
    </Form.Item>
  </>
);

interface AidpPermissionFieldsProps {
  t: TFunction;
  groupOptions: AidpGroupOption[];
  ingroupPermission?: string;
  showSearch?: boolean;
}

const hasRequiredGroupIds = (permission: string, value: unknown) =>
  permission === "PRIVATE" || (Array.isArray(value) && value.length > 0);

export const AidpKnowledgeBasePermissionFields: React.FC<
  AidpPermissionFieldsProps
> = ({ t, groupOptions, ingroupPermission, showSearch = false }) => (
  <>
    <Form.Item
      name="ingroup_permission"
      label={t("aidpKnowledge.createIngroupPermission")}
      rules={[
        {
          required: true,
          message: t("aidpKnowledge.createIngroupPermissionRequired"),
        },
      ]}
    >
      <Select
        options={[
          {
            value: "EDIT",
            label: t("aidpKnowledge.createIngroupPermissionEdit"),
          },
          {
            value: "READ_ONLY",
            label: t("aidpKnowledge.createIngroupPermissionRead"),
          },
          {
            value: "PRIVATE",
            label: t("aidpKnowledge.createIngroupPermissionPrivate"),
          },
        ]}
      />
    </Form.Item>
    <Form.Item
      name="group_ids"
      label={t("aidpKnowledge.createAccessGroups")}
      required={ingroupPermission !== "PRIVATE"}
      dependencies={["ingroup_permission"]}
      rules={[
        ({ getFieldValue }) => ({
          validator(_rule, value) {
            const permission =
              getFieldValue("ingroup_permission") || "READ_ONLY";
            return hasRequiredGroupIds(permission, value)
              ? Promise.resolve()
              : Promise.reject(
                  new Error(t("aidpKnowledge.createAccessGroupsRequired"))
                );
          },
        }),
      ]}
    >
      <Select
        mode="multiple"
        showSearch={showSearch ? { optionFilterProp: "label" } : undefined}
        placeholder={t("aidpKnowledge.createAccessGroupsPlaceholder")}
        disabled={ingroupPermission === "PRIVATE"}
        options={groupOptions}
      />
    </Form.Item>
  </>
);
