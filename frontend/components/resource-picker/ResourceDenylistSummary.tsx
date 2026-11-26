// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Button, Space, Tag, Tooltip } from "antd";
import { LockKeyhole } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  denylistResourceKind,
  denylistSelectedGroups,
} from "@/lib/resourceDenylist";
import type { DenylistItem, DenylistScope } from "@/types/resourceDenylist";

interface ResourceDenylistSummaryProps {
  scope: DenylistScope;
  items: DenylistItem[];
  selected: Set<string>;
  saving: boolean;
  isLocked: (item: DenylistItem) => boolean;
  onRemove: (item: DenylistItem) => void;
  onClear: () => void;
}

export function ResourceDenylistSummary({
  scope,
  items,
  selected,
  saving,
  isLocked,
  onRemove,
  onClear,
}: ResourceDenylistSummaryProps) {
  const { t } = useTranslation("common");
  const { global, current } = denylistSelectedGroups(scope, items, selected);
  const resources = [...global, ...current];
  const globalKeys = new Set(global.map((item) => item.key));
  const kinds = ["local", "mcpService", "mcpTool", "skill"] as const;
  return (
    <div
      data-testid="resource-denylist-summary"
      className="max-h-56 shrink-0 space-y-2 overflow-y-auto"
    >
      <div className="flex items-center justify-between gap-3 text-sm text-[var(--color-text-secondary)]">
        <span>
          {t("resourceDenylist.selectedCount", { count: resources.length })}
        </span>
        <Button
          type="link"
          size="small"
          disabled={saving || !current.length}
          onClick={onClear}
          title={
            scope === "tenant"
              ? t("resourceDenylist.summary.clearEditable")
              : undefined
          }
        >
          {t("resourceDenylist.clear")}
        </Button>
      </div>
      {!resources.length && (
        <span className="text-xs text-[var(--color-text-secondary)]">
          {t("resourceDenylist.notConfigured")}
        </span>
      )}
      {kinds.map((kind) => {
        const entries = resources.filter(
          (item) => denylistResourceKind(item) === kind
        );
        if (!entries.length) return null;
        return (
          <div
            key={kind}
            role="group"
            aria-label={t(`resourceDenylist.summary.${kind}`)}
            className="flex items-start gap-3"
          >
            <span className="w-24 shrink-0 pt-0.5 text-xs text-[var(--color-text-secondary)]">
              {t(`resourceDenylist.summary.${kind}`)} {entries.length}
            </span>
            <Space size={[4, 6]} wrap>
              {entries.map((item) => {
                const readonly = globalKeys.has(item.key);
                const hint = readonly
                  ? selected.has(item.key)
                    ? t("resourceDenylist.summary.tenantRetained")
                    : t("resourceDenylist.summary.platformManaged")
                  : undefined;
                return (
                  <Tooltip key={item.key} title={hint}>
                    <Tag
                      closable={!readonly && !isLocked(item) && !saving}
                      onClose={(event) => {
                        event.preventDefault();
                        if (!readonly) onRemove(item);
                      }}
                    >
                      {kind === "mcpTool" && item.service
                        ? `${item.service} / ${item.name}`
                        : item.name}
                      {readonly && (
                        <LockKeyhole
                          role="img"
                          aria-label={t("resourceDenylist.globalBlocked")}
                          size={12}
                          className="ml-1 inline align-middle"
                        />
                      )}
                    </Tag>
                  </Tooltip>
                );
              })}
            </Space>
          </div>
        );
      })}
    </div>
  );
}
