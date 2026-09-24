"use client";

import React, { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { Collapse, Modal, Form, Input, message } from "antd";
import { SettingOutlined } from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import { useAidpGroupOptions } from "../hooks/useAidpGroupOptions";
import {
  AIDP_MODAL_STYLES,
  AidpKnowledgeBaseBasicFields,
  AidpKnowledgeBaseModalFooter,
  AidpKnowledgeBaseModalHeader,
  AidpKnowledgeBasePermissionFields,
} from "./AidpKnowledgeBaseModalParts";

interface AidpUpdateKbModalProps {
  open: boolean;
  knowledgeBase: AidpKnowledgeBaseItem | null;
  onCancel: () => void;
  onSuccess: (knowledgeBase: AidpKnowledgeBaseItem) => void;
}

const AidpUpdateKbModal: React.FC<AidpUpdateKbModalProps> = ({
  open,
  knowledgeBase,
  onCancel,
  onSuccess,
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [loading, setLoading] = React.useState(false);

  const { isUser, canConfigureGroupPermissions, groupOptions } =
    useAidpGroupOptions();
  const [advancedOpen, setAdvancedOpen] = React.useState(false);

  const ingroupPermission = Form.useWatch("ingroup_permission", form);

  // Pre-fill form when opening. ``group_ids`` may be null/undefined on rows
  // that predate the column — normalize to an empty array so the Select
  // (mode="multiple") receives a value shape it accepts.
  useEffect(() => {
    if (!open) return;
    setAdvancedOpen(false);
    if (!knowledgeBase) return;
    form.setFieldsValue({
      name: knowledgeBase.kds_name,
      description: knowledgeBase.description || "",
      ingroup_permission: isUser
        ? "PRIVATE"
        : knowledgeBase.ingroup_permission || "READ_ONLY",
      group_ids: isUser
        ? []
        : Array.isArray(knowledgeBase.group_ids)
          ? knowledgeBase.group_ids
          : [],
    });
  }, [open, knowledgeBase, form, isUser]);

  const handleOk = async () => {
    if (!knowledgeBase) return;

    try {
      const values = await form.validateFields();
      setLoading(true);

      const name = values.name.trim();
      const description = values.description?.trim() || "";
      const nameChanged = name !== knowledgeBase.kds_name.trim();
      const descriptionChanged =
        description !== (knowledgeBase.description || "").trim();

      // The advanced permission fields are intentionally hidden for USER
      // accounts. Keep a form-level fallback so metadata-only edits still
      // submit a valid permission when those fields are not mounted.
      const newPermission = isUser
        ? "PRIVATE"
        : values.ingroup_permission ||
          knowledgeBase.ingroup_permission ||
          "READ_ONLY";
      const newGroupIds: number[] = isUser
        ? []
        : Array.isArray(values.group_ids)
          ? values.group_ids
          : Array.isArray(knowledgeBase.group_ids)
            ? knowledgeBase.group_ids
            : [];
      const originalPermission =
        knowledgeBase.ingroup_permission || "READ_ONLY";
      const originalGroupIds: number[] = Array.isArray(knowledgeBase.group_ids)
        ? knowledgeBase.group_ids
        : [];
      const normalizedNewGroupIds =
        newPermission === "PRIVATE" ? [] : newGroupIds;
      const permissionChanged =
        newPermission !== originalPermission ||
        normalizedNewGroupIds.length !== originalGroupIds.length ||
        [...normalizedNewGroupIds]
          .sort((a, b) => a - b)
          .some(
            (id, idx) => id !== [...originalGroupIds].sort((a, b) => a - b)[idx]
          );

      if (!nameChanged && !descriptionChanged && !permissionChanged) {
        form.resetFields();
        onSuccess(knowledgeBase);
        return;
      }

      // Omitted metadata fields must never trigger an upstream AIDP request.
      const result = await aidpKnowledgeService.setPermission(
        knowledgeBase.kds_id,
        {
          ingroup_permission: newPermission,
          group_ids: normalizedNewGroupIds,
          ...(nameChanged ? { name } : {}),
          ...(descriptionChanged ? { description } : {}),
        }
      );
      const metadataFailed = result.metadata_status === "failed";
      if (metadataFailed) {
        message.warning(t("aidpKnowledge.updateKbMetadataFailed"));
      } else {
        message.success(t("aidpKnowledge.updateKbSuccess"));
      }
      const updated = result.metadata;
      form.resetFields();
      onSuccess({
        ...knowledgeBase,
        kds_name:
          !metadataFailed && nameChanged
            ? updated?.kds_name || name
            : knowledgeBase.kds_name,
        description:
          !metadataFailed && descriptionChanged
            ? (updated?.description ?? description)
            : knowledgeBase.description,
        ingroup_permission: newPermission,
        group_ids: normalizedNewGroupIds,
        resource_status:
          result.metadata_status === "updated"
            ? "ACTIVE"
            : knowledgeBase.resource_status,
      });
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) {
        return;
      }
      message.error(t("aidpKnowledge.updateKbFailed"));
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = () => {
    form.resetFields();
    onCancel();
  };

  return (
    <Modal
      open={open}
      title={null}
      onOk={handleOk}
      onCancel={handleCancel}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      confirmLoading={loading}
      centered
      width={640}
      maskClosable={false}
      destroyOnHidden
      styles={AIDP_MODAL_STYLES}
      footer={
        <AidpKnowledgeBaseModalFooter
          onCancel={handleCancel}
          onSubmit={handleOk}
          loading={loading}
          cancelText={t("common.cancel")}
          submitText={t("common.confirm")}
        />
      }
    >
      <div>
        <AidpKnowledgeBaseModalHeader
          title={t("aidpKnowledge.updateKb")}
          subtitle={t("knowledgeBase.create.subtitle")}
        />
        <Form
          form={form}
          layout="vertical"
          style={{ padding: "20px 24px 8px" }}
        >
          <AidpKnowledgeBaseBasicFields t={t} />
          {canConfigureGroupPermissions ? (
            <Collapse
              className="!rounded-xl !border-gray-200"
              activeKey={advancedOpen ? ["advanced"] : []}
              onChange={(keys) =>
                setAdvancedOpen(
                  Array.isArray(keys)
                    ? keys.includes("advanced")
                    : keys === "advanced"
                )
              }
              items={[
                {
                  key: "advanced",
                  // Keep permission fields registered with the Form while
                  // the Collapse is closed so metadata-only edits still
                  // submit the existing group_ids value.
                  forceRender: true,
                  label: (
                    <span className="flex items-center gap-2 text-sm font-medium text-gray-800">
                      <SettingOutlined />
                      {t("aidpKnowledge.createAdvancedOptions")}
                    </span>
                  ),
                  children: (
                    <div className="pt-1">
                      <AidpKnowledgeBasePermissionFields
                        t={t}
                        groupOptions={groupOptions}
                        ingroupPermission={ingroupPermission}
                        showSearch
                      />
                    </div>
                  ),
                },
              ]}
            />
          ) : (
            <Form.Item name="ingroup_permission" hidden>
              <Input type="hidden" />
            </Form.Item>
          )}
        </Form>
      </div>
    </Modal>
  );
};

export default AidpUpdateKbModal;
