// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useEffect, useMemo, useState } from "react";

import { UploadCenterContext } from "@/hooks/upload/useUploadCenter";
import {
  createUploadCenterStore,
  type UploadCenterStore,
} from "@/lib/uploadCenter/uploadCenterStore";
import UploadCenterFloatingPanel from "@/components/upload-center/UploadCenterFloatingPanel";

interface UploadCenterProviderProps {
  children: React.ReactNode;
}

/**
 * Session-scoped upload center. It lives in the application layout, so
 * client-side navigation never unmounts the queue or the XHR requests.
 */
export const UploadCenterProvider: React.FC<UploadCenterProviderProps> = ({
  children,
}) => {
  const [store] = useState<UploadCenterStore>(() => createUploadCenterStore());

  const value = useMemo(
    () => ({
      store,
      enqueue: store.enqueue.bind(store),
      retryFailed: store.retryFailed.bind(store),
      close: store.close.bind(store),
    }),
    [store]
  );

  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (!store.isActive()) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [store]);

  return (
    <UploadCenterContext.Provider value={value}>
      {children}
      <UploadCenterFloatingPanel store={store} />
    </UploadCenterContext.Provider>
  );
};

export default UploadCenterProvider;
