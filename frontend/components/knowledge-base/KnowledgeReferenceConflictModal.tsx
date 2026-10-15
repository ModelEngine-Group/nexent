// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";
import { Modal, Tag } from "antd";
import { AlertCircle } from "lucide-react";

import type { KnowledgeReferenceConflictDetails } from "@/types/knowledgeResource";

/**
 * Conflict dialog shown when a knowledge base deletion is blocked because
 * non-deleted agent configurations still reference it.
 *
 * Only agents the caller can view are rendered from the response; the hidden
 * references are represented by an aggregate count without names, ids,
 * versions, or links.
 */
export default function KnowledgeReferenceConflictModal({
  open,
  details,
  onClose,
}: {
  open: boolean;
  details: KnowledgeReferenceConflictDetails | null;
  onClose: () => void;
}) {
  const { t } = useTranslation("common");
  const visibleAgents = details?.visible_agents ?? [];
  const hiddenCount = details?.hidden_agent_count ?? 0;

  const versionLabel = (
    version: KnowledgeReferenceConflictDetails["visible_agents"][number]["versions"][number]
  ) => {
    if (version.is_draft) {
      return t("knowledgeResource.conflict.draftVersion");
    }
    return (
      version.version_name ||
      t("knowledgeResource.conflict.versionNo", { no: version.version_no })
    );
  };

  return (
    <Modal
      open={open}
      title={
        <span className="flex items-center gap-2">
          <AlertCircle className="size-4 text-red-500" />
          {t("knowledgeResource.conflict.title")}
        </span>
      }
      onCancel={onClose}
      footer={null}
      destroyOnClose
    >
      <div className="space-y-3 text-sm text-gray-600">
        <p>{t("knowledgeResource.conflict.description")}</p>
        {visibleAgents.length > 0 && (
          <div className="max-h-64 space-y-2 overflow-y-auto">
            {visibleAgents.map((agent) => (
              <div
                key={agent.agent_id}
                className="rounded-md border border-gray-200 bg-gray-50 px-3 py-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-foreground">
                    {agent.display_name}
                  </span>
                  {!agent.can_edit_draft && (
                    <span className="text-xs text-gray-400">
                      {t("knowledgeResource.conflict.noEditPermission")}
                    </span>
                  )}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {agent.versions.map((version) => (
                    <Tag
                      key={`${agent.agent_id}-${version.version_no}-${version.reference_origin}`}
                      className="!m-0 !text-xs"
                    >
                      {versionLabel(version)}
                    </Tag>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
        {hiddenCount > 0 && (
          <p className="rounded-md bg-amber-50 px-3 py-2 text-amber-700">
            {t("knowledgeResource.conflict.hiddenReferences", {
              count: hiddenCount,
            })}
          </p>
        )}
        <p className="text-xs text-gray-400">
          {t("knowledgeResource.conflict.hint")}
        </p>
      </div>
    </Modal>
  );
}
