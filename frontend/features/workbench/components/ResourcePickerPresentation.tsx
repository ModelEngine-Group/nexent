"use client";

import type { ReactNode } from "react";
import { Modal, type ModalProps } from "antd";
import { WorkbenchResourceDrawer } from "./WorkbenchResourceDrawer";

/** Retain the ordinary-chat modal contract while opting Workbench into a drawer. */
export function ResourcePickerPresentation({
  presentation = "modal",
  disabled,
  onOk,
  onCancel,
  drawerListContent,
  drawerPagination,
  ...props
}: Omit<ModalProps, "onOk" | "onCancel"> & {
  presentation?: "modal" | "drawer";
  drawerListContent?: ReactNode;
  drawerPagination?: ReactNode;
  disabled?: boolean;
  onOk: () => void;
  onCancel: () => void;
}) {
  if (presentation === "modal")
    return <Modal {...props} onOk={onOk} onCancel={onCancel} />;
  return (
    <WorkbenchResourceDrawer
      listContent={drawerListContent}
      pagination={drawerPagination}
      open={Boolean(props.open)}
      title={props.title}
      onCancel={onCancel}
      onConfirm={onOk}
      saving={Boolean(props.confirmLoading)}
      disabled={disabled}
      confirmDisabled={props.okButtonProps?.disabled}
      footerLeading={
        typeof props.footer === "function"
          ? props.footer(null, { OkBtn: () => null, CancelBtn: () => null })
          : undefined
      }
    >
      {props.children}
    </WorkbenchResourceDrawer>
  );
}
