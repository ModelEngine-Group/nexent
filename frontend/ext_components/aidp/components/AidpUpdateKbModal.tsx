"use client";

import React, { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Button, Collapse, Modal, Form, Input, Select, message } from "antd";
import { SettingOutlined } from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import { AIDP_KNOWLEDGE_BASE_NAME_PATTERN } from "@/const/knowledgeBase";
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
  const [advancedOpen, setAdvancedOpen] = React.useState(false);
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
      styles={{
        container: { overflow: "hidden", borderRadius: 16, padding: 0 },
        body: { padding: 0 },
        footer: {
          margin: 0,
          padding: "12px 20px 16px",
          borderTop: "1px solid #f0f0f0",
        },
      }}
      footer={
        <div className="flex justify-end gap-3">
          <Button onClick={handleCancel} disabled={loading}>
            {t("common.cancel")}
          </Button>
          <Button type="primary" onClick={handleOk} loading={loading}>
            {t("common.confirm")}
          </Button>
        </div>
      }
    >
      <div>
        <div
          className="border-b border-gray-200"
          style={{ padding: "24px 24px 20px" }}
        >
          <h2 className="text-xl font-semibold tracking-tight text-gray-900">
            {t("aidpKnowledge.updateKb")}
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            {t("knowledgeBase.create.subtitle")}
          </p>
        </div>
        <Form
          form={form}
          layout="vertical"
          style={{ padding: "20px 24px 8px" }}
        >
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
          <Form.Item
            name="description"
            label={t("aidpKnowledge.kbDescription")}
          >
            <Input.TextArea
              rows={3}
              placeholder={t("aidpKnowledge.kbDescriptionPlaceholder")}
            />
          </Form.Item>
          {canConfigureGroupPermissions && (
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
                  label: (
                    <span className="flex items-center gap-2 text-sm font-medium text-gray-800">
                      <SettingOutlined />
                      {t("aidpKnowledge.createAdvancedOptions")}
                    </span>
                  ),
                  children: (
                    <div className="pt-1">
                      <Form.Item
                        name="ingroup_permission"
                        label={t("aidpKnowledge.createIngroupPermission")}
                        rules={[
                          {
                            required: true,
                            message: t(
                              "aidpKnowledge.createIngroupPermissionRequired"
                            ),
                          },
                        ]}
                      >
                        <Select
                          options={[
                            {
                              value: "EDIT",
                              label: t(
                                "aidpKnowledge.createIngroupPermissionEdit"
                              ),
                            },
                            {
                              value: "READ_ONLY",
                              label: t(
                                "aidpKnowledge.createIngroupPermissionRead"
                              ),
                            },
                            {
                              value: "PRIVATE",
                              label: t(
                                "aidpKnowledge.createIngroupPermissionPrivate"
                              ),
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
                                getFieldValue("ingroup_permission") ||
                                "READ_ONLY";
                              if (level === "PRIVATE") return Promise.resolve();
                              if (Array.isArray(value) && value.length > 0) {
                                return Promise.resolve();
                              }
                              return Promise.reject(
                                new Error(
                                  t("aidpKnowledge.createAccessGroupsRequired")
                                )
                              );
                            },
                          }),
                        ]}
                      >
                        <Select
                          mode="multiple"
                          showSearch={{ optionFilterProp: "label" }}
                          placeholder={t(
                            "aidpKnowledge.createAccessGroupsPlaceholder"
                          )}
                          disabled={ingroupPermission === "PRIVATE"}
                          options={groupOptions}
                        />
                      </Form.Item>
                    </div>
                  ),
                },
              ]}
            />
          )}
        </Form>
      </div>
    </Modal>
  );
};

export default AidpUpdateKbModal;
