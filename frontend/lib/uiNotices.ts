// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";

export interface UiNotice {
  id: number;
  title: ReactNode;
  content: ReactNode;
  confirmLabel: string;
}
const empty: readonly UiNotice[] = [];
let notices: readonly UiNotice[] = empty;
let serial = 0;
const listeners = new Set<() => void>();
export const subscribeNotices = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};
export const getNotices = () => notices;
export const getServerNotices = () => empty;
export function showInfoNotice(notice: Omit<UiNotice, "id">) {
  notices = [...notices, { ...notice, id: ++serial }];
  listeners.forEach((listener) => listener());
}
export function dismissNotice(id: number) {
  notices = notices.filter((notice) => notice.id !== id);
  listeners.forEach((listener) => listener());
}
