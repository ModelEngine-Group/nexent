// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useTranslation } from "react-i18next";
import { StandardTable } from "@/components/common/StandardTable";
import type { Group } from "@/services/groupService";

interface McpGroupSelectionTableProps {
  groups: Group[];
  loading: boolean;
  selectedGroupIds: number[];
  disabled: boolean;
  onChange: (groupIds: number[]) => void;
}

export default function McpGroupSelectionTable({
  groups,
  loading,
  selectedGroupIds,
  disabled,
  onChange,
}: McpGroupSelectionTableProps) {
  const { t } = useTranslation("common");

  return (
    <StandardTable<Group>
      rowKey="group_id"
      dataSource={groups}
      loading={loading}
      tableLayout="fixed"
      size="small"
      pagination={{
        pageSize: 10,
        simple: { readOnly: true },
        hideOnSinglePage: true,
        showSizeChanger: false,
      }}
      rowSelection={{
        columnWidth: 48,
        selectedRowKeys: selectedGroupIds,
        preserveSelectedRowKeys: true,
        hideSelectAll: disabled,
        getCheckboxProps: (group) => ({
          disabled: disabled,
          "aria-label": group.group_name,
        }),
        onChange: (keys) => onChange(keys.map(Number)),
      }}
      columns={[
        {
          title: t("tenantResources.knowledgeBase.groupNames"),
          dataIndex: "group_name",
          width: 120,
          ellipsis: true,
          render: (name: string) => (
            <span className="text-[#0067D1]">{name}</span>
          ),
        },
        {
          title: t("common.description"),
          dataIndex: "group_description",
          ellipsis: true,
          render: (description?: string) => description || "—",
        },
        {
          title: t("mcpTools.addModal.groupMemberCount"),
          dataIndex: "user_count",
          width: 120,
          render: (count?: number) => count ?? "—",
        },
      ]}
    />
  );
}
