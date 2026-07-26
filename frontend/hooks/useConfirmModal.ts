import { App } from "antd";
import { ExclamationCircleFilled } from "@ant-design/icons";
import React from "react";
import { useTranslation } from "react-i18next";

interface ConfirmProps {
  title: string;
  content: React.ReactNode;
  okText?: string;
  cancelText?: string;
  danger?: boolean;
  onOk?: () => void;
  onCancel?: () => void;
}

export const useConfirmModal = () => {
  const { t } = useTranslation("common");
  const { modal } = App.useApp();

  const confirm = ({
    title,
    content,
    okText,
    cancelText,
    danger = true,
    onOk,
    onCancel,
  }: ConfirmProps) => {
    return modal.confirm({
      title,
      content,
      centered: true,
      icon: React.createElement(ExclamationCircleFilled),
      okText: okText || t("common.confirm"),
      cancelText: cancelText || t("common.cancel"),
      okButtonProps: {
        danger,
        type: "primary",
      },
      onOk: onOk,
      onCancel,
    });
  };

  return { confirm };
};
