// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useState } from "react";
import { Modal, Spin } from "antd";
import { useTranslation } from "react-i18next";

import KnowledgeBaseDeleteNotice from "@/components/knowledge-base/KnowledgeBaseDeleteNotice";
import { formatKnowledgeBaseDeleteError } from "@/lib/knowledgeBaseDeleteError";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import type {
  KnowledgeBase,
  KnowledgeBaseDeletionPreview,
} from "@/types/knowledgeBase";

interface KnowledgeBaseBatchDeleteDialogProps {
  targets: KnowledgeBase[];
  canDelete: boolean;
  onCancel: () => void;
  onComplete: (failures: Record<string, string>) => void;
}

export default function KnowledgeBaseBatchDeleteDialog({
  targets,
  canDelete,
  onCancel,
  onComplete,
}: KnowledgeBaseBatchDeleteDialogProps) {
  const { t } = useTranslation("common");
  const [previews, setPreviews] = useState<
    (KnowledgeBaseDeletionPreview | null)[] | null
  >(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void Promise.all(
      targets.map((target) =>
        knowledgeBaseService.previewBoundAgents(target.id)
      )
    ).then((results) => {
      if (!cancelled) setPreviews(results);
    });
    return () => {
      cancelled = true;
    };
  }, [targets]);

  const deleteTargets = async () => {
    if (deleting || !canDelete || !previews) return;
    setDeleting(true);
    const failures = new Map<string, string>();
    for (const target of targets) {
      try {
        await knowledgeBaseService.deleteKnowledgeBase(target.id);
      } catch (error) {
        failures.set(
          target.id,
          `${target.name} · ${formatKnowledgeBaseDeleteError(
            error,
            t,
            "knowledgeBase.message.deleteError"
          )}`
        );
      }
    }
    onComplete(Object.fromEntries(failures));
  };

  return (
    <Modal
      open
      centered
      title={t("knowledgeBase.batch.confirmTitle")}
      okText={t("knowledgeBase.batch.deleteSelected")}
      cancelText={t("common.cancel")}
      okButtonProps={{ danger: true, disabled: !previews || !canDelete }}
      cancelButtonProps={{ disabled: deleting }}
      closable={!deleting}
      keyboard={!deleting}
      mask={{ closable: false }}
      confirmLoading={deleting}
      onCancel={() => {
        if (!deleting) onCancel();
      }}
      onOk={() => void deleteTargets()}
    >
      <p>
        {t("knowledgeBase.batch.confirmContent", { count: targets.length })}
      </p>
      {previews ? (
        <ul className="mt-3 max-h-64 space-y-3 overflow-y-auto">
          {targets.map((target, index) => (
            <li key={target.id}>
              <strong className="break-all">{target.name}</strong>
              <KnowledgeBaseDeleteNotice preview={previews[index]} />
            </li>
          ))}
        </ul>
      ) : (
        <div className="flex justify-center py-3">
          <Spin />
        </div>
      )}
    </Modal>
  );
}
