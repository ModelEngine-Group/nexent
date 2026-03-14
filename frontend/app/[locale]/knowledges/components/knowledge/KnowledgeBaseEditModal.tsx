"use client";

import React, { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Form, Input, Select, message } from "antd";
import { useGroupList } from "@/hooks/group/useGroupList";
import { Can } from "@/components/permission/Can";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import knowledgeBasePollingService from "@/services/knowledgeBasePollingService";
import { checkKnowledgeBaseName } from "@/services/uploadService";
import { NAME_CHECK_STATUS } from "@/const/agentConfig";
import { KnowledgeBase } from "@/types/knowledgeBase";

interface KnowledgeBaseEditModalProps {
  open: boolean;
  knowledgeBase: KnowledgeBase | null;
  tenantId: string | null;
  onCancel: () => void;
  onSuccess: (updatedKnowledgeBase: KnowledgeBase) => void;
}

export function KnowledgeBaseEditModal({
  open,
  knowledgeBase,
  tenantId,
  onCancel,
  onSuccess,
}: KnowledgeBaseEditModalProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm();

  // Name validation state
  const [nameError, setNameError] = useState<string | null>(null);

  // Store original name for comparison
  const originalNameRef = useRef<string>("");

  // Track current permission value for conditional logic
  const [currentPermission, setCurrentPermission] = useState<string>("READ_ONLY");

  // Fetch groups for group selection
  const { data: groupData } = useGroupList(tenantId);
  const groups = groupData?.groups || [];

  // Reset form and states when knowledge base changes
  React.useEffect(() => {
    if (knowledgeBase && open) {
      const permission = knowledgeBase.ingroup_permission || "READ_ONLY";
      form.setFieldsValue({
        knowledge_name: knowledgeBase.name,
        ingroup_permission: permission,
        group_ids: permission === "PRIVATE" ? [] : (knowledgeBase.group_ids || []),
      });
      // Store original name for comparison
      originalNameRef.current = knowledgeBase.name;
      // Reset error state
      setNameError(null);
      // Set current permission
      setCurrentPermission(permission);
    }
  }, [knowledgeBase, open, form]);

  // Check if name is valid (only when submitting)
  const checkNameValidation = async (name: string): Promise<boolean> => {
    // Allow if name is same as original
    if (name === originalNameRef.current) {
      setNameError(null);
      return true;
    }

    try {
      const result = await checkKnowledgeBaseName(name, t);
      if (result.status === NAME_CHECK_STATUS.AVAILABLE) {
        setNameError(null);
        return true;
      } else {
        setNameError(t("tenantResources.knowledgeBase.nameExists"));
        return false;
      }
    } catch (error) {
      setNameError(t("tenantResources.knowledgeBase.nameCheckFailed"));
      return false;
    }
  };

  // Handle form submission
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();

      if (!knowledgeBase) return;

      // Check name duplication on submit
      const isNameValid = await checkNameValidation(values.knowledge_name);
      if (!isNameValid) {
        return; // Error message is displayed via Form.Item help
      }

      // Ensure group_ids is empty when permission is PRIVATE
      const groupIds = values.ingroup_permission === "PRIVATE" ? [] : values.group_ids;

      await knowledgeBaseService.updateKnowledgeBase(knowledgeBase.id, {
        knowledge_name: values.knowledge_name,
        ingroup_permission: values.ingroup_permission,
        group_ids: groupIds,
      });

      message.success(t("tenantResources.knowledgeBase.updated"));

      // Construct updated knowledge base object with new values
      const updatedKnowledgeBase: KnowledgeBase = {
        ...knowledgeBase,
        name: values.knowledge_name,
        ingroup_permission: values.ingroup_permission,
        group_ids: groupIds,
      };

      // Trigger knowledge base list refresh to seamlessly update UI
      knowledgeBasePollingService.triggerKnowledgeBaseListUpdate(true);

      onSuccess(updatedKnowledgeBase);
      onCancel();
    } catch (error: any) {
      if (error.errorFields) {
        return; // Form validation error
      }
      message.error(error.message || t("tenantResources.knowledgeBase.updateFailed"));
    }
  };

  // Handle permission change - clear group_ids when PRIVATE is selected
  const handlePermissionChange = (value: string) => {
    setCurrentPermission(value);
    if (value === "PRIVATE") {
      form.setFieldsValue({ group_ids: [] });
    }
  };

  // Check if group select should be disabled
  const isGroupSelectDisabled = currentPermission === "PRIVATE";

  return (
    <Modal
      title={t("tenantResources.knowledgeBase.edit")}
      open={open}
      onOk={handleSubmit}
      onCancel={onCancel}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      width={500}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="knowledge_name"
          label={t("common.name")}
          validateStatus={nameError ? "error" : undefined}
          help={nameError || undefined}
          rules={[
            { required: true, message: t("tenantResources.knowledgeBase.nameRequired") },
          ]}
        >
          <Input placeholder={t("tenantResources.knowledgeBase.enterName")} />
        </Form.Item>

        <Can permission="kb.groups:read">
          <Form.Item
            name="ingroup_permission"
            label={t("tenantResources.knowledgeBase.permission")}
            rules={[
              { required: true, message: t("tenantResources.knowledgeBase.permissionRequired") },
            ]}
          >
            <Select
              placeholder={t("tenantResources.knowledgeBase.permission")}
              onChange={handlePermissionChange}
              options={[
                { value: "EDIT", label: t("tenantResources.knowledgeBase.permission.EDIT") },
                { value: "READ_ONLY", label: t("tenantResources.knowledgeBase.permission.READ_ONLY") },
                { value: "PRIVATE", label: t("tenantResources.knowledgeBase.permission.PRIVATE") },
              ]}
            />
          </Form.Item>
        </Can>

        <Can permission="group:read">
          <Form.Item name="group_ids" label={t("tenantResources.knowledgeBase.groupNames")}>
            <Select
              mode="multiple"
              placeholder={isGroupSelectDisabled ? t("knowledgeBase.create.permission.groupPlaceholder") : t("tenantResources.knowledgeBase.groupNames")}
              value={isGroupSelectDisabled ? [] : form.getFieldValue("group_ids")}
              options={groups.map((group) => ({
                label: group.group_name,
                value: group.group_id,
              }))}
              disabled={isGroupSelectDisabled}
            />
          </Form.Item>
        </Can>
      </Form>
    </Modal>
  );
}
