// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { Button, Modal, Table } from "antd";
import { useTranslation } from "react-i18next";
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import ResourceTagChips from "@/components/tag/ResourceTagChips";
import type { TagDefinition, TagResourceType } from "@/types/tagManagement";

export interface ResourceTagTarget {
  id: string;
  name: string;
  canEdit: boolean;
}

/** Reuses unified assignment editing; changing tags never changes resource selection. */
export function ResourceTagManagementModal({
  resourceType,
  resources,
  definitions,
  onClose,
  onSaved,
}: {
  resourceType: TagResourceType;
  resources: ResourceTagTarget[];
  definitions: TagDefinition[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation("common");
  const [target, setTarget] = useState<ResourceTagTarget | null>(null);
  const [revision, setRevision] = useState(0);
  return (
    <>
      <Modal
        open
        title={t("resourcePicker.manageTags", "管理标签")}
        onCancel={onClose}
        footer={null}
        width={800}
        zIndex={1100}
      >
        <Table
          rowKey="id"
          dataSource={resources}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: t("common.name", "名称"), dataIndex: "name" },
            {
              title: t("resourcePicker.tags", "标签"),
              render: (_, resource) => (
                <ResourceTagChips
                  resourceType={resourceType}
                  resourceId={resource.id}
                  refreshKey={revision}
                />
              ),
            },
            {
              title: t("common.actions", "操作"),
              render: (_, resource) => (
                <Button
                  disabled={!resource.canEdit}
                  onClick={() => setTarget(resource)}
                >
                  {t("resourcePicker.manageTags", "管理标签")}
                </Button>
              ),
            },
          ]}
        />
      </Modal>
      {target && (
        <ResourceTagAssignmentModal
          open
          onClose={() => setTarget(null)}
          resourceType={resourceType}
          resourceId={target.id}
          definitions={definitions}
          canEdit={target.canEdit}
          onSaved={() => {
            setRevision((value) => value + 1);
            onSaved();
          }}
        />
      )}
    </>
  );
}
