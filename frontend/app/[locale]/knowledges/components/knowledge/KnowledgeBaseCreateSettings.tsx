// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Button, Checkbox, InputNumber, Radio, Segmented, Select } from "antd";
import { Lock, Users } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Can } from "@/components/permission/Can";
import type { Group } from "@/services/groupService";

const permissions = [
  { value: "PRIVATE", icon: Lock },
  { value: "READ_ONLY", icon: Users },
  { value: "EDIT", icon: Users },
] as const;

const quotaUnits = { GB: 1024 ** 3, MB: 1024 ** 2 };

interface KnowledgeBaseCreateSettingsProps {
  preserveSourceFile: boolean;
  onPreserveSourceFileChange?: (preserve: boolean) => void;
  quotaLimitBytes?: number | null;
  onQuotaLimitBytesChange?: (bytes: number | null) => void;
  permission?: string;
  onPermissionChange?: (permission: string) => void;
  groups: Group[];
  selectedGroupIds: number[];
  onGroupsChange: (ids: number[]) => void;
}

export default function KnowledgeBaseCreateSettings({
  preserveSourceFile,
  onPreserveSourceFileChange,
  quotaLimitBytes,
  onQuotaLimitBytesChange,
  permission,
  onPermissionChange,
  groups,
  selectedGroupIds,
  onGroupsChange,
}: KnowledgeBaseCreateSettingsProps) {
  const { t } = useTranslation();
  const [quotaUnit, setQuotaUnit] = useState<keyof typeof quotaUnits>("GB");
  const selectedGroups = groups.filter((group) =>
    selectedGroupIds.includes(group.group_id)
  );
  const allSelected =
    groups.length > 0 && selectedGroups.length === groups.length;
  const copyLabel = t("knowledgeBase.create.field.preserve");
  const quotaLabel = t("knowledgeBase.create.field.quota");
  const groupLabel = t("knowledgeBase.create.field.groups");

  return (
    <>
      <section className="space-y-4 border-t border-[var(--color-border-separator)] px-6 py-5">
        <div>
          <h3 className="text-base font-semibold">
            {t("knowledgeBase.create.advancedSettings")}
          </h3>
          <p className="text-sm text-[var(--color-text-secondary)]">
            {t("knowledgeBase.create.storageHint")}
          </p>
        </div>
        {onPreserveSourceFileChange && (
          <div className="space-y-2">
            <label htmlFor="kb-create-copy">
              {copyLabel} <span className="text-[var(--color-error)]">*</span>
            </label>
            <Select
              id="kb-create-copy"
              className="w-full"
              size="large"
              value={preserveSourceFile ? "original" : "chunks"}
              onChange={(value) =>
                onPreserveSourceFileChange(value === "original")
              }
              aria-describedby="kb-create-copy-hint"
              options={[
                {
                  value: "original",
                  label: t("knowledgeBase.create.preserveSourceFile"),
                },
                {
                  value: "chunks",
                  label: t("knowledgeBase.create.chunksOnly"),
                },
              ]}
            />
            <p
              id="kb-create-copy-hint"
              className="text-sm text-[var(--color-text-secondary)]"
            >
              {t("knowledgeBase.create.copyHint")}
            </p>
          </div>
        )}
        {onQuotaLimitBytesChange && (
          <div className="space-y-2">
            <label htmlFor="kb-create-quota">
              {quotaLabel}{" "}
              <span className="text-[var(--color-text-secondary)]">
                {t("knowledgeBase.create.optional")}
              </span>
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <InputNumber
                id="kb-create-quota"
                size="large"
                className="w-40"
                min={0}
                value={
                  quotaLimitBytes == null
                    ? null
                    : quotaLimitBytes / quotaUnits[quotaUnit]
                }
                onChange={(value) =>
                  onQuotaLimitBytesChange(
                    value == null
                      ? null
                      : Math.round(value * quotaUnits[quotaUnit])
                  )
                }
                placeholder={t("quota.unlimited")}
                aria-describedby="kb-create-quota-hint"
              />
              <Segmented
                aria-label={t("knowledgeBase.create.quotaUnit")}
                options={["GB", "MB"]}
                value={quotaUnit}
                onChange={setQuotaUnit}
              />
            </div>
            <p
              id="kb-create-quota-hint"
              className="text-sm text-[var(--color-text-secondary)]"
            >
              {t("knowledgeBase.create.quotaHint")}
            </p>
          </div>
        )}
      </section>

      <Can permission="kb.groups:update">
        <section className="space-y-4 border-t border-[var(--color-border-separator)] px-6 py-5">
          <div>
            <h3 id="kb-create-access" className="text-base font-semibold">
              {t("knowledgeBase.detail.access")}
            </h3>
            <p className="text-sm text-[var(--color-text-secondary)]">
              {t("knowledgeBase.create.accessHint")}
            </p>
          </div>
          <Radio.Group
            aria-labelledby="kb-create-access"
            value={permission}
            onChange={(event) => onPermissionChange?.(event.target.value)}
            className="w-full divide-y divide-[var(--color-border-separator)] overflow-hidden rounded-lg border border-[var(--color-border-separator)]"
          >
            {permissions.map(({ value, icon: Icon }) => (
              <Radio
                key={value}
                value={value}
                className={`!m-0 w-full items-center !gap-2 px-3 py-2.5 ${permission === value ? "bg-[var(--color-select)]" : ""}`}
              >
                <span className="flex items-center gap-3">
                  <Icon
                    size={17}
                    aria-hidden
                    className="shrink-0 text-[var(--color-text-secondary)]"
                  />
                  <span>
                    <span className="block">
                      {t(`knowledgeBase.create.access.${value}`)}
                    </span>
                    <span className="block text-sm text-[var(--color-text-secondary)]">
                      {t(`knowledgeBase.create.access.${value}.hint`)}
                    </span>
                  </span>
                </span>
              </Radio>
            ))}
          </Radio.Group>
          {permission !== "PRIVATE" && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span id="kb-create-groups">{groupLabel}</span>{" "}
                  <span className="text-sm text-[var(--color-text-secondary)]">
                    {t("knowledgeBase.create.groupsSelected", {
                      selected: selectedGroups.length,
                      total: groups.length,
                    })}
                  </span>
                </div>
                <Button
                  type="link"
                  size="small"
                  disabled={groups.length === 0}
                  onClick={() =>
                    onGroupsChange(
                      allSelected ? [] : groups.map((group) => group.group_id)
                    )
                  }
                >
                  {t(allSelected ? "common.deselectAll" : "common.selectAll")}
                </Button>
              </div>
              {groups.length > 0 && (
                <Checkbox.Group
                  aria-labelledby="kb-create-groups"
                  value={selectedGroups.map((group) => group.group_id)}
                  onChange={onGroupsChange}
                  className="!flex flex-col !gap-0 divide-y divide-[var(--color-border-separator)] overflow-hidden rounded-lg border border-[var(--color-border-separator)]"
                >
                  {groups.map((group) => (
                    <Checkbox
                      key={group.group_id}
                      value={group.group_id}
                      className={`!m-0 w-full items-center !gap-2 px-3 py-2.5 [&>span:last-child]:min-w-0 [&>span:last-child]:flex-1 ${selectedGroupIds.includes(group.group_id) ? "bg-[var(--color-select)]" : ""}`}
                    >
                      <span className="flex items-center justify-between gap-3">
                        <span className="min-w-0 break-words">
                          <span className="block">{group.group_name}</span>
                          {group.group_description && (
                            <span className="block text-sm text-[var(--color-text-secondary)]">
                              {group.group_description}
                            </span>
                          )}
                        </span>
                        {group.user_count != null && (
                          <span className="shrink-0 text-sm text-[var(--color-text-secondary)]">
                            {t("knowledgeBase.create.groupMembers", {
                              count: group.user_count,
                            })}
                          </span>
                        )}
                      </span>
                    </Checkbox>
                  ))}
                </Checkbox.Group>
              )}
            </div>
          )}
        </section>
      </Can>
    </>
  );
}
