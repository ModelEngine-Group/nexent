import { App } from "antd";
import { ExclamationCircleFilled } from "@ant-design/icons";

import React from "react";
import i18next from "i18next";

interface ConfirmProps {
  title: string;
  content: React.ReactNode;
  okText?: string;
  cancelText?: string;
  danger?: boolean; // 默认为 true，使用 danger 样式
  onOk?: () => void;
  onCancel?: () => void;
}

export const useConfirmModal = () => {
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
      okText: okText || i18next.t("common.confirm"),
      cancelText: cancelText || i18next.t("common.cancel"),
      okButtonProps: { 
        danger, 
        type: "primary"
      },
      onOk: onOk,
      onCancel,
    });
  };

  return { confirm };
};