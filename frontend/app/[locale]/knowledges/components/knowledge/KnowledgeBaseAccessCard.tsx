// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { App, Button, Card, Select, Tag } from "antd";
import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import { buildGroupSelectOptions } from "@/hooks/group/buildGroupSelectOptions";
import { usePermission } from "@/hooks/permission/usePermission";
import type { Group } from "@/services/groupService";
import knowledgeBasePollingService from "@/services/knowledgeBasePollingService";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import type { KnowledgeBase } from "@/types/knowledgeBase";

interface KnowledgeBaseAccessCardProps {
  knowledgeBase: KnowledgeBase;
  groups: Group[];
  allGroups: Group[];
  onChange?: (knowledgeBase: KnowledgeBase) => void;
}

interface AccessSettings {
  permission: string;
  groupIds: number[];
}

const groupPermissions = ["EDIT", "READ_ONLY", "PRIVATE"];

export default function KnowledgeBaseAccessCard({
  knowledgeBase,
  groups,
  allGroups,
  onChange,
}: KnowledgeBaseAccessCardProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { can } = usePermission();
  const [draft, setDraft] = useState<AccessSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const canEdit =
    Boolean(onChange) &&
    knowledgeBase.permission !== "READ_ONLY" &&
    can("kb:update") &&
    can("kb.groups:update");
  const canViewGroups = can("group:read");
  const savedPermission = knowledgeBase.ingroup_permission || "READ_ONLY";
  const savedGroups = knowledgeBase.group_ids ?? [];
  const { permission, groupIds } = (canEdit ? draft : null) ?? {
    permission: savedPermission,
    groupIds: savedPermission === "PRIVATE" ? [] : savedGroups,
  };
  const isPrivate = permission === "PRIVATE";
  const permissionChanged = permission !== savedPermission;
  const groupsChanged =
    groupIds.length !== savedGroups.length ||
    groupIds.some((id) => !savedGroups.includes(id));
  const hasChanges = draft !== null && (permissionChanged || groupsChanged);
  const groupOptions = buildGroupSelectOptions({
    groups: canEdit
      ? groups
      : allGroups.filter((group) => groupIds.includes(group.group_id)),
    allGroups,
    selectedGroupIds: groupIds,
    deletedGroupLabel: t("group.deleted"),
  });
  const selectedCount = groupOptions.filter(({ value }) =>
    groupIds.includes(value)
  ).length;

  const save = async () => {
    if (!canEdit || !hasChanges || saving) return;
    setSaving(true);
    try {
      await knowledgeBaseService.updateKnowledgeBase(knowledgeBase.id, {
        ...(permissionChanged && { ingroup_permission: permission }),
        ...((groupsChanged || isPrivate) && { group_ids: groupIds }),
      });
      onChange?.({
        ...knowledgeBase,
        ingroup_permission: permission,
        group_ids: groupIds,
      });
      setDraft(null);
      knowledgeBasePollingService.triggerKnowledgeBaseListUpdate(true);
      message.success(t("tenantResources.knowledgeBase.updated"));
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("tenantResources.knowledgeBase.updateFailed")
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card
      size="small"
      variant="outlined"
      title={t("knowledgeBase.detail.access")}
    >
      <div className="space-y-3">
        <div className="space-y-1">
          <div className="text-xs text-[var(--color-text-secondary)]">
            {t("knowledgeBase.create.field.permission")}
          </div>
          {canEdit ? (
            <Select
              aria-label={t("knowledgeBase.create.field.permission")}
              className="w-full"
              value={permission}
              disabled={saving}
              options={groupPermissions.map((value) => ({
                value,
                label: t(`knowledgeBase.ingroup.permission.${value}`),
              }))}
              onChange={(value) =>
                setDraft({
                  permission: value,
                  groupIds: value === "PRIVATE" ? [] : groupIds,
                })
              }
            />
          ) : (
            <div>{t(`knowledgeBase.ingroup.permission.${permission}`)}</div>
          )}
        </div>
        {canViewGroups && (
          <div className="space-y-1">
            <div className="flex flex-wrap justify-between gap-1 text-xs text-[var(--color-text-secondary)]">
              <span>{t("knowledgeBase.create.field.groups")}</span>
              {canEdit && !isPrivate && groupOptions.length > 0 && (
                <span>
                  {t("knowledgeBase.detail.groupsSelected", {
                    selected: selectedCount,
                    total: groupOptions.length,
                  })}
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {isPrivate || groupOptions.length === 0 ? (
                <span className="text-sm text-[var(--color-text-secondary)]">
                  {t("knowledgeBase.create.permission.groupPlaceholder")}
                </span>
              ) : (
                groupOptions.map(({ value, label }) => {
                  const selected = groupIds.includes(value);
                  return canEdit ? (
                    <Button
                      key={value}
                      size="small"
                      type={selected ? "primary" : "default"}
                      ghost={selected}
                      icon={
                        selected ? <Check size={14} aria-hidden /> : undefined
                      }
                      aria-pressed={selected}
                      disabled={saving}
                      onClick={() =>
                        setDraft({
                          permission,
                          groupIds: selected
                            ? groupIds.filter((id) => id !== value)
                            : [...groupIds, value],
                        })
                      }
                    >
                      {label}
                    </Button>
                  ) : (
                    <Tag key={value}>{label}</Tag>
                  );
                })
              )}
            </div>
          </div>
        )}
        <div className="flex items-center justify-between gap-2 border-t border-[var(--color-border-separator)] pt-3">
          <div>
            <p>{t("knowledgeBase.detail.preserveSource")}</p>
            <p className="text-xs text-[var(--color-text-secondary)]">
              {t("knowledgeBase.detail.preserveSourceFixed")}
            </p>
          </div>
          <Tag className="!m-0 shrink-0">
            {t(
              knowledgeBase.preserve_source_file === false
                ? "common.disabled"
                : "common.enabled"
            )}
          </Tag>
        </div>
        {canEdit && hasChanges && (
          <div className="flex justify-end gap-2">
            <Button onClick={() => setDraft(null)} disabled={saving}>
              {t("common.cancel")}
            </Button>
            <Button type="primary" onClick={() => void save()} loading={saving}>
              {t("common.save")}
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}
