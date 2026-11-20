// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { Alert, Modal, Form, Input, Switch, message } from "antd";

import log from "@/lib/logger";

import type { AidpKnowledgeBaseItem } from "@/ext_components/aidp/shared/types/knowledge";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { useSaveAidpKnowledgeSettings } from "./hooks/useAidpKnowledgeDetail";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { useAidpGroupOptions } from "@/ext_components/aidp/shared/hooks/useAidpGroupOptions";
import {
  AIDP_MODAL_STYLES,
  AidpKnowledgeBaseBasicFields,
  AidpKnowledgeBaseModalFooter,
  AidpKnowledgeBaseModalHeader,
  AidpKnowledgeBasePermissionFields,
} from "@/ext_components/aidp/shared/components/AidpKnowledgeBaseModalParts";

interface AidpUpdateKbModalProps {
  open: boolean;
  mode: "metadata" | "permissions";
  knowledgeBase: AidpKnowledgeBaseItem | null;
  onCancel: () => void;
  onSuccess: (knowledgeBase: AidpKnowledgeBaseItem) => void;
}

const AidpUpdateKbModal: React.FC<AidpUpdateKbModalProps> = ({
  open,
  mode,
  knowledgeBase,
  onCancel,
  onSuccess,
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [validating, setValidating] = React.useState(false);
  const saveMutation = useSaveAidpKnowledgeSettings();
  const loading = validating || saveMutation.isPending;
  const submittingRef = useRef(false);

  const {
    isUser,
    canConfigureGroupPermissions,
    canReadGroups,
    groupOptions,
    groupsLoading,
    groupsError,
  } = useAidpGroupOptions();
  const ingroupPermission = Form.useWatch("ingroup_permission", form);

  // Pre-fill form when opening. ``group_ids`` may be null/undefined on rows
  // that predate the column — normalize to an empty array so the Select
  // (mode="multiple") receives a value shape it accepts.
  useEffect(() => {
    if (!open) return;
    if (!knowledgeBase) return;
    form.setFieldsValue({
      name: knowledgeBase.kds_name,
      description: knowledgeBase.description || "",
      sensitive_intercept_enable:
        knowledgeBase.sensitive_intercept_enable === 1,
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
    if (!knowledgeBase || submittingRef.current) return;
    submittingRef.current = true;
    setValidating(true);
    try {
      const values = form.getFieldsValue();

      const name =
        mode === "metadata"
          ? (values.name || "").trim()
          : knowledgeBase.kds_name.trim();
      const description =
        mode === "metadata"
          ? (values.description || "").trim()
          : (knowledgeBase.description || "").trim();
      const nameChanged =
        mode === "metadata" && name !== knowledgeBase.kds_name.trim();
      const descriptionChanged =
        mode === "metadata" &&
        description !== (knowledgeBase.description || "").trim();

      // Permission fields are hidden for USER accounts. Keep a form-level
      // fallback so metadata-only edits still submit a valid permission.
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
      // The switch is a KB field, not a permission: only an explicit change
      // is sent, so unrelated edits never overwrite the upstream value.
      const nextSensitive = values.sensitive_intercept_enable === true;
      const originalSensitive = knowledgeBase.sensitive_intercept_enable === 1;
      const sensitiveChanged =
        mode === "metadata" && nextSensitive !== originalSensitive;
      const settingsChanged =
        nameChanged || descriptionChanged || permissionChanged;

      if (!settingsChanged && !sensitiveChanged) {
        form.resetFields();
        onSuccess(knowledgeBase);
        return;
      }

      // Validate only fields the user actually changed. Historical KB names
      // may not match today's naming rule; an unrelated switch edit must not
      // be blocked by re-validating the untouched name.
      const fieldsToValidate: string[] = [];
      if (mode === "metadata") {
        if (nameChanged) fieldsToValidate.push("name");
        if (descriptionChanged) fieldsToValidate.push("description");
        if (sensitiveChanged)
          fieldsToValidate.push("sensitive_intercept_enable");
      }
      if (permissionChanged)
        fieldsToValidate.push("ingroup_permission", "group_ids");
      if (fieldsToValidate.length) {
        await form.validateFields(fieldsToValidate);
      }

      if (sensitiveChanged) {
        // Send only the switch and refresh the detail afterwards; the AIDP
        // update route treats omitted fields as unchanged.
        await aidpKnowledgeService.updateKb(knowledgeBase.kds_id, {
          sensitive_intercept_enable: nextSensitive ? 1 : 0,
        });
      }

      if (!settingsChanged) {
        message.success(t("aidpKnowledge.updateKbSuccess"));
        form.resetFields();
        onSuccess({
          ...knowledgeBase,
          sensitive_intercept_enable: nextSensitive ? 1 : 0,
        });
        return;
      }

      // Omitted metadata fields must never trigger an upstream AIDP request.
      setValidating(false);
      const result = await saveMutation.mutateAsync({
        id: knowledgeBase.kds_id,
        payload: {
          ingroup_permission: newPermission,
          group_ids: normalizedNewGroupIds,
          ...(nameChanged ? { name } : {}),
          ...(descriptionChanged ? { description } : {}),
        },
      });
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
        sensitive_intercept_enable: nextSensitive ? 1 : 0,
        resource_status:
          result.metadata_status === "updated"
            ? "ACTIVE"
            : knowledgeBase.resource_status,
      });
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) {
        return;
      }
      log.error("Failed to update AIDP knowledge base:", {
        id: knowledgeBase.kds_id,
        error,
      });
      message.error(
        getAidpErrorMessage(error, t, t("aidpKnowledge.updateKbFailed"))
      );
    } finally {
      submittingRef.current = false;
      setValidating(false);
    }
  };

  const handleCancel = () => {
    if (submittingRef.current) return;
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
      closable={!loading}
      keyboard={!loading}
      centered
      width={640}
      mask={{ closable: false }}
      destroyOnHidden
      styles={AIDP_MODAL_STYLES}
      footer={
        <AidpKnowledgeBaseModalFooter
          onCancel={handleCancel}
          onSubmit={handleOk}
          loading={loading}
          submitDisabled={
            canConfigureGroupPermissions &&
            ingroupPermission !== "PRIVATE" &&
            (groupsLoading || !!groupsError || !canReadGroups)
          }
          cancelText={t("common.cancel")}
          submitText={t("common.confirm")}
        />
      }
    >
      <div>
        <AidpKnowledgeBaseModalHeader
          title={
            mode === "metadata"
              ? t("aidpKnowledge.updateKb")
              : t("aidpKnowledge.detailPermissions")
          }
          subtitle={
            mode === "metadata" ? t("knowledgeBase.create.subtitle") : undefined
          }
        />
        <Form
          form={form}
          layout="vertical"
          style={{ padding: "20px 24px 8px" }}
        >
          {mode === "metadata" && <AidpKnowledgeBaseBasicFields t={t} />}
          {mode === "metadata" && (
            <Form.Item
              name="sensitive_intercept_enable"
              label={t("aidpKnowledge.sensitiveIntercept")}
              valuePropName="checked"
              extra={
                <span className="text-xs text-gray-500">
                  {t("aidpKnowledge.sensitiveInterceptHint")}
                </span>
              }
            >
              <Switch aria-label={t("aidpKnowledge.sensitiveIntercept")} />
            </Form.Item>
          )}
          {canConfigureGroupPermissions &&
            (groupsError || (!canReadGroups && !groupsLoading)) && (
              <Alert
                className="mb-4"
                type="error"
                showIcon
                title={
                  groupsError
                    ? getAidpErrorMessage(
                        groupsError,
                        t,
                        t("aidpKnowledge.groupsLoadFailed")
                      )
                    : t("aidpKnowledge.groupsPermissionRequired")
                }
              />
            )}
          {canConfigureGroupPermissions ? (
            <div className="grid grid-cols-1 gap-x-6 md:grid-cols-2">
              <AidpKnowledgeBasePermissionFields
                t={t}
                groupOptions={groupOptions}
                ingroupPermission={ingroupPermission}
                showSearch
                groupsLoading={groupsLoading}
                groupsUnavailable={!!groupsError || !canReadGroups}
              />
            </div>
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
