"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Modal, Alert, Space, Typography } from "antd";
import { AlertTriangle } from "lucide-react";

const { Text, Paragraph } = Typography;

interface DeleteAccountModalProps {
  open: boolean;
  onOk: () => void;
  onCancel: () => void;
  loading?: boolean;
  disabled?: boolean;
}

/**
 * DeleteAccountModal - Shared component for account deletion confirmation
 *
 * Features:
 * - Warning message about permanent deletion
 * - Disabled confirm button for admin/super_admin roles
 * - Consistent styling across the application
 */
export function DeleteAccountModal({
  open,
  onOk,
  onCancel,
  loading = false,
  disabled = false,
}: DeleteAccountModalProps) {
  const { t } = useTranslation("common");

  return (
    <Modal
      title={
        <Space className="text-red-600">
          <AlertTriangle className="h-5 w-5" />
          <span>{t("auth.confirmRevoke") || "Confirm Account Deletion"}</span>
        </Space>
      }
      open={open}
      onOk={onOk}
      onCancel={onCancel}
      okText={t("auth.confirmRevokeOk") || "Delete Anyway"}
      okButtonProps={{ danger: true, loading, disabled }}
      cancelText={t("auth.cancel") || "Cancel"}
      width={500}
    >
      <Alert
        type="error"
        showIcon
        className="mb-4"
        message={t("profile.deleteWarningTitle") || "This action cannot be undone!"}
        description={
          <ul className="list-disc pl-4 mt-2 space-y-1">
            <li>{t("profile.deleteWarning1") || "Your account will be permanently deleted"}</li>
            <li>{t("profile.deleteWarning2") || "All your conversations and data will be removed"}</li>
            <li>{t("profile.deleteWarning3") || "This action cannot be reversed"}</li>
          </ul>
        }
      />
      {disabled && (
        <div className="mt-4">
          <Text strong>{t("profile.adminRestrictionTitle") || "Administrator Restriction"}</Text>
          <Paragraph type="secondary" className="mt-1">
            {t("auth.refuseRevokePrompt") || "Your role is administrator. Account deletion for admin is not yet supported."}
          </Paragraph>
        </div>
      )}
    </Modal>
  );
}

