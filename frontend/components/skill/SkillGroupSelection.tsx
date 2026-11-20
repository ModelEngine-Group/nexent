// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Table } from "antd";

import { useState } from "react";
import { Alert, Button } from "antd";
import { useTranslation } from "react-i18next";
import type { Group } from "@/services/groupService";

interface SkillGroupSelectionProps {
  id?: string;
  groups: Group[];
  value?: number[];
  onChange?: (value: number[]) => void;
  loading?: boolean;
  disabled?: boolean;
  isError?: boolean;
  onRetry?: () => void;
}

/** Form-controlled group IDs retain selections across the table's local pages. */
export default function SkillGroupSelection({
  id,
  groups,
  value = [],
  onChange,
  loading = false,
  disabled = false,
  isError = false,
  onRetry,
}: SkillGroupSelectionProps) {
  const { t } = useTranslation("common");
  const [page, setPage] = useState(1);
  const pageSize = 10;
  const ids = new Set(groups.map((group) => group.group_id));
  if (isError) {
    return (
      <Alert
        id={id}
        type="error"
        showIcon
        title={t("skillCreation.groupsLoadFailed")}
        action={
          <Button disabled={disabled} onClick={onRetry}>
            {t("repository.common.retry")}
          </Button>
        }
      />
    );
  }
  return (
    <div id={id} role="group" aria-label={t("skillCreation.selectGroups")}>
      <Table<Group>
        rowKey="group_id"
        size="small"
        loading={loading}
        tableLayout="fixed"
        dataSource={groups}
        scroll={{ x: 560 }}
        locale={{ emptyText: t("skillCreation.noGroups") }}
        rowSelection={{
          selectedRowKeys: value.filter((id) => ids.has(id)),
          preserveSelectedRowKeys: true,
          columnWidth: 40,
          onChange: (keys) =>
            onChange?.(keys.map(Number).filter((id) => ids.has(id))),
          getCheckboxProps: (group) => ({
            disabled: disabled || loading,
            "aria-label": group.group_name,
          }),
        }}
        columns={[
          {
            title: t("skillCreation.groupName"),
            dataIndex: "group_name",
            width: 180,
            ellipsis: true,
            render: (name: string) => (
              <span className="text-[#0067D1]" title={name}>
                {name}
              </span>
            ),
          },
          {
            title: t("skillCreation.groupDescription"),
            dataIndex: "group_description",
            ellipsis: true,
            render: (description?: string) => (
              <span title={description}>{description || "—"}</span>
            ),
          },
          {
            title: t("skillCreation.groupMembers"),
            dataIndex: "user_count",
            width: 80,
            render: (count?: number) => count ?? "—",
          },
        ]}
        pagination={{
          current: Math.min(
            page,
            Math.max(1, Math.ceil(groups.length / pageSize))
          ),
          pageSize,
          total: groups.length,
          simple: true,
          showSizeChanger: false,
          hideOnSinglePage: false,
          onChange: setPage,
          disabled: disabled || loading,
          size: "small",
        }}
      />
    </div>
  );
}
