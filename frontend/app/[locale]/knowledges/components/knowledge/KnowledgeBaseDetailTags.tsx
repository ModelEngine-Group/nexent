// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { Button } from "antd";
import { useTranslation } from "react-i18next";

import { Can } from "@/components/permission/Can";
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import ResourceTagChips from "@/components/tag/ResourceTagChips";
import TagDefinitionManagementModal from "@/components/tag/TagDefinitionManagementModal";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";

interface KnowledgeBaseDetailTagsProps {
  knowledgeBaseId: string;
  readOnly: boolean;
  onChange?: () => void;
}

export default function KnowledgeBaseDetailTags({
  knowledgeBaseId,
  readOnly,
  onChange,
}: KnowledgeBaseDetailTagsProps) {
  const { t } = useTranslation("common");
  const [assignmentOpen, setAssignmentOpen] = useState(false);
  const [managementOpen, setManagementOpen] = useState(false);
  const [revision, setRevision] = useState(0);
  const enabled = assignmentOpen || managementOpen;
  const { data: libraries, loading: loadingLibraries } = useTagLibraries({
    enabled,
  });
  const library = libraries?.find(
    ({ bucket_key }) => bucket_key === "default_resource"
  );
  const {
    data: definitions,
    loading: loadingDefinitions,
    refresh,
  } = useTagDefinitions(library?.bucket_id ?? null, { enabled });

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm text-[var(--color-text-secondary)]">
        {t("document.table.header.tags")}
      </span>
      <ResourceTagChips
        key={revision}
        resourceType="knowledge_base"
        resourceId={knowledgeBaseId}
      />
      <Can permission="kb:update">
        <Button
          size="small"
          type="dashed"
          onClick={() => setAssignmentOpen(true)}
        >
          {t(
            readOnly
              ? "knowledgeBase.action.viewTags"
              : "knowledgeBase.action.assignTags"
          )}
        </Button>
      </Can>
      {assignmentOpen && (
        <ResourceTagAssignmentModal
          open
          onClose={() => setAssignmentOpen(false)}
          resourceType="knowledge_base"
          resourceId={knowledgeBaseId}
          definitions={definitions ?? []}
          definitionsLoading={loadingLibraries || loadingDefinitions}
          canEdit={!readOnly}
          onManageDefinitions={
            readOnly ? undefined : () => setManagementOpen(true)
          }
          onSaved={() => {
            setRevision((value) => value + 1);
            onChange?.();
          }}
        />
      )}
      {managementOpen && library && !readOnly && (
        <TagDefinitionManagementModal
          open
          onClose={() => {
            setManagementOpen(false);
            void refresh();
          }}
          bucketId={library.bucket_id}
          bucketName={library.bucket_name}
          canManage
        />
      )}
    </div>
  );
}
