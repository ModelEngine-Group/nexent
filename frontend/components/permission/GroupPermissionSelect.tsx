// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Button, Select } from "antd";
import { useTranslation } from "react-i18next";

import type { GroupPermission } from "@/types/groupPermission";

const permissions = ["READ_ONLY", "EDIT"] as const;

export function GroupPermissionSelect({
  value = [],
  onChange,
  options,
  disabled,
}: {
  value?: GroupPermission[];
  onChange?: (rules: GroupPermission[]) => void;
  options: { value: number; label: string; disabled?: boolean }[];
  disabled?: boolean;
}) {
  const { t } = useTranslation("common");

  return (
    <div className="flex flex-col gap-3">
      {permissions.map((permission) => {
        const label = t(`resourceGroupPermission.${permission}`);
        const assigned = value.filter((rule) => rule.permission === permission);
        const elsewhere = new Set(
          value
            .filter((rule) => rule.permission !== permission)
            .map((rule) => rule.group_id)
        );
        return (
          <div key={permission} className="flex flex-col gap-1">
            <span>{label}</span>
            <Select<number[]>
              aria-label={label}
              mode="multiple"
              allowClear
              disabled={disabled}
              showSearch={{ optionFilterProp: "label" }}
              placeholder={t("resourceGroupPermission.selectGroups")}
              options={options.filter((group) => !elsewhere.has(group.value))}
              value={assigned.map((rule) => rule.group_id)}
              onChange={(ids) =>
                onChange?.([
                  ...value.filter((rule) => rule.permission !== permission),
                  ...ids.map((group_id) => ({ group_id, permission })),
                ])
              }
            />
          </div>
        );
      })}
      {onChange && !disabled && (
        <Button
          type="link"
          className="self-start !px-0"
          onClick={() => onChange([])}
        >
          {t("resourceGroupPermission.makePrivate")}
        </Button>
      )}
    </div>
  );
}
