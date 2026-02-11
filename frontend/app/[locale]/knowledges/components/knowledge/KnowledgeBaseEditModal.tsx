"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Modal, Form, Input, Select, message } from "antd";
import { useGroupList } from "@/hooks/group/useGroupList";
import { Can } from "@/components/permission/Can";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import knowledgeBasePollingService from "@/services/knowledgeBasePollingService";
import { KnowledgeBase } from "@/types/knowledgeBase";

interface KnowledgeBaseEditModalProps {
  open: boolean;
  knowledgeBase: KnowledgeBase | null;
  tenantId: string | null;
  onCancel: () => void;
  onSuccess: () => void;
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

  // Fetch groups for group selection
  const { data: groupData } = useGroupList(tenantId, 1, 100);
  const groups = groupData?.groups || [];

  // Reset form when knowledge base changes
  React.useEffect(() => {
    if (knowledgeBase && open) {
      form.setFieldsValue({
        knowledge_name: knowledgeBase.name,
        ingroup_permission: knowledgeBase.ingroup_permission || "READ_ONLY",
        group_ids: knowledgeBase.group_ids || [],
      });
    }
  }, [knowledgeBase, open, form]);

  // Handle form submission
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();

      if (!knowledgeBase) return;

      await knowledgeBaseService.updateKnowledgeBase(knowledgeBase.id, {
        knowledge_name: values.knowledge_name,
        ingroup_permission: values.ingroup_permission,
        group_ids: values.group_ids,
      });

      message.success(t("tenantResources.knowledgeBase.updated"));

      // Trigger knowledge base list refresh to seamlessly update UI
      knowledgeBasePollingService.triggerKnowledgeBaseListUpdate(true);

      onSuccess();
      onCancel();
    } catch (error: any) {
      if (error.errorFields) {
        return; // Form validation error
      }
      message.error(error.message || t("tenantResources.knowledgeBase.updateFailed"));
    }
  };

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
              placeholder={t("tenantResources.knowledgeBase.groupNames")}
              options={groups.map((group) => ({
                label: group.group_name,
                value: group.group_id,
              }))}
            />
          </Form.Item>
        </Can>
      </Form>
    </Modal>
  );
}
