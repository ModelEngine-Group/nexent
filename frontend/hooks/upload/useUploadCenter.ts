// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { createContext, useContext } from "react";

import type { UploadCenterStore } from "@/lib/uploadCenter/uploadCenterStore";
import type { UploadEnqueueInput } from "@/types/uploadCenter";

export interface UploadCenterContextValue {
  store: UploadCenterStore;
  enqueue: (input: UploadEnqueueInput) => void;
  retryFailed: () => void;
  close: () => boolean;
}

export const UploadCenterContext =
  createContext<UploadCenterContextValue | null>(null);

export const useUploadCenter = (): UploadCenterContextValue => {
  const value = useContext(UploadCenterContext);
  if (!value) {
    throw new Error("useUploadCenter must be used inside UploadCenterProvider");
  }
  return value;
};
