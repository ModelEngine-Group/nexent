// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useState, useRef, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Form, Input, message } from "antd";
import { useGroupDetails, useGroupList } from "@/hooks/group/useGroupList";
import { buildGroupSelectOptions } from "@/hooks/group/buildGroupSelectOptions";
import { GroupPermissionSelect } from "@/components/permission/GroupPermissionSelect";
import { getGroupPermissions } from "@/lib/groupPermission";
import type { GroupPermission } from "@/types/groupPermission";
import { Can } from "@/components/permission/Can";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
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
  const { getAccessibleGroupIds, user } = useAuthorizationContext();
  const [form] = Form.useForm();

  // Name validation state
  const [nameError, setNameError] = useState<string | null>(null);

  // Store original name for comparison
  const originalNameRef = useRef<string>("");

  const [rules, setRules] = useState<GroupPermission[]>([]);
  const [sharingChanged, setSharingChanged] = useState(false);
  const canManageSharing =
    user?.role !== "USER" &&
    (knowledgeBase?.permission === "CREATOR" ||
      ["SU", "ADMIN", "SPEED", "ASSET_OWNER"].includes(user?.role ?? ""));

  // Fetch tenant groups and limit selections to accessible groups (all for admin roles).
  const { data: groupData, isLoading: groupsLoading } = useGroupList(tenantId);
  const accessibleGroupIds = getAccessibleGroupIds();
  const { groups } = useGroupDetails(
    groupData?.groups ?? [],
    accessibleGroupIds
  );

  const groupSelectOptions = useMemo(
    () =>
      buildGroupSelectOptions({
        groups,
        allGroups: groupData?.groups ?? [],
        selectedGroupIds: rules.map((rule) => rule.group_id),
        deletedGroupLabel: t("group.deleted"),
      }),
    [groups, groupData?.groups, rules, t]
  );

  // Reset form and states when knowledge base changes
  React.useEffect(() => {
    if (knowledgeBase && open) {
      form.setFieldsValue({ knowledge_name: knowledgeBase.name });
      setRules(getGroupPermissions(knowledgeBase));
      setSharingChanged(false);
      // Store original name for comparison
      originalNameRef.current = knowledgeBase.name;
      // Reset error state
      setNameError(null);
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

      await knowledgeBaseService.updateKnowledgeBase(knowledgeBase.id, {
        knowledge_name: values.knowledge_name,
        ...(sharingChanged ? { group_permissions: rules } : {}),
      });

      message.success(t("tenantResources.knowledgeBase.updated"));

      const updatedKnowledgeBase: KnowledgeBase = {
        ...knowledgeBase,
        name: values.knowledge_name,
        ...(sharingChanged
          ? {
              group_permissions: rules,
              group_ids: rules.map((rule) => rule.group_id),
              ingroup_permission: rules.length ? "READ_ONLY" : "PRIVATE",
            }
          : {}),
      };

      // Trigger knowledge base list refresh to seamlessly update UI
      knowledgeBasePollingService.triggerKnowledgeBaseListUpdate(true);

      onSuccess(updatedKnowledgeBase);
      onCancel();
    } catch (error: any) {
      if (error.errorFields) {
        return; // Form validation error
      }
      message.error(
        error.message || t("tenantResources.knowledgeBase.updateFailed")
      );
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
          validateStatus={nameError ? "error" : undefined}
          help={nameError || undefined}
          rules={[
            {
              required: true,
              message: t("tenantResources.knowledgeBase.nameRequired"),
            },
          ]}
        >
          <Input placeholder={t("tenantResources.knowledgeBase.enterName")} />
        </Form.Item>

        <Can permission="kb.groups:read">
          <Can permission="group:read">
            <Form.Item label={t("resourceGroupPermission.title")}>
              <GroupPermissionSelect
                value={rules}
                options={groupSelectOptions}
                disabled={!canManageSharing || groupsLoading}
                onChange={(nextRules) => {
                  setRules(nextRules);
                  setSharingChanged(true);
                }}
              />
            </Form.Item>
          </Can>
        </Can>
      </Form>
    </Modal>
  );
}
