// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback } from "react";
import { App } from "antd";
import type { ModalFuncProps } from "antd";

/**
 * Shared AIDP confirmation dialog: centered, danger by default, caller can
 * still override individual props (for non-destructive confirmations).
 */
export const useConfirmModal = () => {
  const { modal } = App.useApp();
  return useCallback(
    (options: ModalFuncProps) =>
      modal.confirm({
        centered: true,
        ...options,
        okButtonProps: {
          danger: true,
          ...(options.okButtonProps ?? {}),
        },
      }),
    [modal]
  );
};
