// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";
import { useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/common/Modal";
import { Button } from "@/components/common/Button";
import {
  subscribeNotices,
  getNotices,
  getServerNotices,
  dismissNotice,
} from "@/lib/uiNotices";

/** Notices survive unmounting the preview or other workflow that raised them. */
export function NoticeHost() {
  const { t } = useTranslation("common");
  const notice = useSyncExternalStore(
    subscribeNotices,
    getNotices,
    getServerNotices
  )[0];
  if (!notice) return null;
  const close = () => dismissNotice(notice.id);
  return (
    <Modal
      key={notice.id}
      open
      title={notice.title}
      closeLabel={t("common.close")}
      onClose={close}
      footer={<Button onClick={close}>{notice.confirmLabel}</Button>}
    >
      {notice.content}
    </Modal>
  );
}
