"use client";

import React, { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Modal, Form, Input, Select, message } from "antd";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";

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

  // Mirror the create-modal wiring: the authorization context exposes
  // ``user.tenantId``, which we feed into ``useGroupList`` to enumerate
  // the tenant's groups for the access-group picker below.
  const { user } = useAuthorizationContext();
  const isUser = user?.role === USER_ROLES.USER;
  const canConfigureGroupPermissions = !!user && !isUser;
  const tenantId = user?.tenantId ?? null;
  const { data: groupListData } = useGroupList(
    canConfigureGroupPermissions ? tenantId : null
  );
  const groupOptions = useMemo(
    () =>
      (groupListData?.groups ?? []).map((g) => ({
        value: g.group_id,
        label: g.group_name,
      })),
    [groupListData]
  );

  const ingroupPermission = Form.useWatch("ingroup_permission", form);

  // Pre-fill form when opening. ``group_ids`` may be null/undefined on rows
  // that predate the column — normalize to an empty array so the Select
  // (mode="multiple") receives a value shape it accepts.
  useEffect(() => {
    if (open && knowledgeBase) {
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
    }
  }, [open, knowledgeBase, form, isUser]);

  const handleOk = async () => {
    if (!knowledgeBase) return;

    try {
      const values = await form.validateFields();
      setLoading(true);

      // Update AIDP-side metadata (name + description).
      const updated = await aidpKnowledgeService.updateKb(
        knowledgeBase.kds_id,
        {
          name: values.name.trim(),
          description: values.description?.trim() || "",
        }
      );

      // Update Nexent-side permissions only when something actually
      // changed. Skipping the PATCH call when values match the original
      // row avoids an unnecessary DB write and sidesteps backend
      // validation for rows where the user hasn't touched permissions.
      const newPermission = isUser ? "PRIVATE" : values.ingroup_permission;
      const newGroupIds: number[] = isUser
        ? []
        : Array.isArray(values.group_ids)
          ? values.group_ids
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

      if (permissionChanged) {
        await aidpKnowledgeService.setPermission(knowledgeBase.kds_id, {
          ingroup_permission: newPermission,
          group_ids: normalizedNewGroupIds,
        });
      }

      message.success(t("aidpKnowledge.updateKbSuccess"));
      form.resetFields();
      onSuccess({
        ...knowledgeBase,
        ...updated,
        kds_id: knowledgeBase.kds_id,
        kds_name: updated.kds_name || values.name.trim(),
        description: updated.description ?? values.description?.trim() ?? "",
        ingroup_permission: newPermission,
        group_ids: normalizedNewGroupIds,
        resource_status: "ACTIVE",
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
      title={t("aidpKnowledge.updateKb")}
      onOk={handleOk}
      onCancel={handleCancel}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      confirmLoading={loading}
      centered
      destroyOnHidden
    >
      <Form form={form} layout="vertical" className="mt-4">
        <Form.Item
          name="name"
          label={t("aidpKnowledge.kbName")}
          rules={[
            { required: true, message: t("aidpKnowledge.kbNameRequired") },
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
        {canConfigureGroupPermissions && (
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
                    const level =
                      getFieldValue("ingroup_permission") || "READ_ONLY";
                    if (level === "PRIVATE") return Promise.resolve();
                    if (Array.isArray(value) && value.length > 0) {
                      return Promise.resolve();
                    }
                    return Promise.reject(
                      new Error(t("aidpKnowledge.createAccessGroupsRequired"))
                    );
                  },
                }),
              ]}
            >
              <Select
                mode="multiple"
                showSearch={{ optionFilterProp: "label" }}
                placeholder={t("aidpKnowledge.createAccessGroupsPlaceholder")}
                disabled={ingroupPermission === "PRIVATE"}
                options={groupOptions}
              />
            </Form.Item>
          </>
        )}
      </Form>
    </Modal>
  );
};

export default AidpUpdateKbModal;
