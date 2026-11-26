// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useMemo, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Empty,
  Input,
  Space,
  Switch,
  Tag,
  Tooltip,
} from "antd";
import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { DenylistItem, DenylistState } from "@/types/resourceDenylist";
import type { DenylistScope } from "@/types/resourceDenylist";
import { denylistResourceKind } from "@/lib/resourceDenylist";
import { ResourceDrawer, CheckMark } from "./ResourceDrawer";
import { McpResourceGroup } from "./McpResourceGroup";
import { ResourceDenylistSummary } from "./ResourceDenylistSummary";
import styles from "./ResourcePickerDrawer.module.css";

interface ResourceDenylistDrawerProps {
  scope: DenylistScope;
  snapshot: DenylistState;
  saving: boolean;
  error: boolean;
  onClose: () => void;
  onSave: (selected: string[]) => void;
  onReload: () => void;
}

export function ResourceDenylistDrawer({
  scope,
  snapshot,
  saving,
  error,
  onClose,
  onSave,
  onReload,
}: ResourceDenylistDrawerProps) {
  const { t } = useTranslation("common");
  const [selected, setSelected] = useState(() => new Set(snapshot.selected));
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("local");
  const [onlyBlocked, setOnlyBlocked] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const items = snapshot.items;
  const byKey = useMemo(
    () => new Map(items.map((item) => [item.key, item])),
    [items]
  );
  const inherited = (item: DenylistItem) =>
    Boolean(
      item.parent_key &&
      (selected.has(item.parent_key) ||
        byKey.get(item.parent_key)?.global_blocked)
    );
  const checked = (item: DenylistItem) =>
    Boolean(item.global_blocked || selected.has(item.key) || inherited(item));
  const locked = (item: DenylistItem) =>
    Boolean(item.global_blocked || inherited(item));
  const toggle = (item: DenylistItem, enabled: boolean) => {
    if (locked(item) || saving) return;
    setSelected((current) => {
      const next = new Set(current);
      if (enabled) next.add(item.key);
      else next.delete(item.key);
      return next;
    });
  };
  const normalized = search.trim().toLocaleLowerCase();
  const matches = (item: DenylistItem) =>
    !normalized ||
    [item.name, item.description, item.service].some((text) =>
      text?.toLocaleLowerCase().includes(normalized)
    );
  const isMcpTool = (item: DenylistItem) =>
    denylistResourceKind(item) === "mcpTool";
  const visible = items.filter(
    (item) =>
      (category === "local"
        ? item.resource_type === "tool" && !isMcpTool(item)
        : category === "mcp"
          ? item.resource_type === "mcp" ||
            (item.resource_type === "tool" && isMcpTool(item))
          : item.resource_type === "skill") &&
      (!onlyBlocked ||
        checked(item) ||
        (item.resource_type === "mcp" &&
          items.some(
            (child) => child.parent_key === item.key && checked(child)
          )))
  );
  const roots = visible
    .filter(
      (item) =>
        !item.parent_key ||
        !byKey.has(item.parent_key) ||
        !visible.some((parent) => parent.key === item.parent_key)
    )
    .filter(
      (item) =>
        matches(item) ||
        visible.some((child) => child.parent_key === item.key && matches(child))
    );
  const currentPage = Math.min(
    page,
    Math.max(1, Math.ceil(roots.length / pageSize))
  );
  const pagedRoots = roots.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize
  );
  const changed =
    selected.size !== snapshot.selected.length ||
    snapshot.selected.some((key) => !selected.has(key));
  const renderItem = (item: DenylistItem) => (
    <div className="flex w-full items-start gap-3 text-left">
      <Checkbox
        aria-label={item.service ? `${item.service} / ${item.name}` : item.name}
        checked={checked(item)}
        disabled={
          locked(item) || saving || (item.missing && !selected.has(item.key))
        }
        onClick={(event) => event.stopPropagation()}
        onChange={(event) => toggle(item, event.target.checked)}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="break-all text-sm font-medium">{item.name}</span>
          {item.global_blocked && (
            <Tag>{t("resourceDenylist.globalBlocked")}</Tag>
          )}
          {!item.global_blocked && inherited(item) && (
            <Tag>{t("resourceDenylist.serviceBlocked")}</Tag>
          )}
          {item.missing && <Tag>{t("resourceDenylist.missing")}</Tag>}
        </div>
        {item.description && (
          <Tooltip title={item.description}>
            <p className="mb-0 mt-1 line-clamp-2 text-xs leading-[18px] text-[var(--color-text-secondary)]">
              {item.description}
            </p>
          </Tooltip>
        )}
      </div>
    </div>
  );

  return (
    <ResourceDrawer
      open
      width="min(768px, 100vw)"
      bodyClassName={styles.drawer}
      title={t("resourceDenylist.drawerTitle")}
      onClose={onClose}
      onConfirm={() => onSave([...selected])}
      confirmDisabled={!changed}
      confirmLoading={saving}
      confirmText={t("common.confirm")}
      closeText={t("common.cancel")}
      searchContent={
        <div className="flex shrink-0 flex-col gap-4">
          <Input
            allowClear
            suffix={
              <Search
                size={14}
                className="text-[var(--color-text-secondary)]"
              />
            }
            aria-label={t("resourceDenylist.search")}
            placeholder={t("resourceDenylist.search")}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
          />
          <ResourceDenylistSummary
            scope={scope}
            items={items}
            selected={selected}
            saving={saving}
            isLocked={locked}
            onRemove={(item) => toggle(item, false)}
            onClear={() =>
              setSelected(
                (current) =>
                  new Set(
                    [...current].filter((key) => byKey.get(key)?.global_blocked)
                  )
              )
            }
          />
        </div>
      }
      listTitle={t("resourceDenylist.listTitle")}
      semanticTabs
      tabs={[
        { key: "local", label: t("toolPool.group.local") },
        { key: "mcp", label: "MCP" },
        { key: "skill", label: t("resourceDenylist.kind.skill") },
      ]}
      activeTab={category}
      onTabChange={(key) => {
        setCategory(key);
        setPage(1);
      }}
      listHeaderExtra={
        <Space size="small">
          <Switch
            size="small"
            checked={onlyBlocked}
            onChange={(value) => {
              setOnlyBlocked(value);
              setPage(1);
            }}
            aria-label={t("resourceDenylist.onlyBlocked")}
          />
          <span className="text-xs text-[var(--color-text-secondary)]">
            {t("resourceDenylist.onlyBlocked")}
          </span>
        </Space>
      }
      controlsContent={
        error ? (
          <Alert
            type="error"
            showIcon
            message={t("resourceDenylist.saveFailed")}
            action={
              <Button size="small" disabled={saving} onClick={onReload}>
                {t("resourceDenylist.reload")}
              </Button>
            }
          />
        ) : undefined
      }
      total={roots.length}
      page={currentPage}
      pageSize={pageSize}
      onPageChange={setPage}
      onPageSizeChange={(size) => {
        setPageSize(size);
        setPage(1);
      }}
    >
      <div data-testid="resource-denylist-options">
        {!roots.length && (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("resourceDenylist.empty")}
          />
        )}
        {pagedRoots.map((item) => {
          const children = visible.filter(
            (child) =>
              child.parent_key === item.key && (matches(item) || matches(child))
          );
          return item.resource_type === "mcp" ? (
            <McpResourceGroup
              key={item.key}
              name={item.name}
              description={item.description}
              toolCount={children.length}
              searching={Boolean(normalized)}
              status={
                item.global_blocked ? (
                  <Tag>{t("resourceDenylist.globalBlocked")}</Tag>
                ) : undefined
              }
              selection={
                <CheckMark
                  checked={checked(item)}
                  indeterminate={!checked(item) && children.some(checked)}
                  disabled={
                    locked(item) ||
                    saving ||
                    Boolean(item.missing && !selected.has(item.key))
                  }
                  ariaLabel={item.name}
                  onToggle={() => toggle(item, !checked(item))}
                />
              }
            >
              {children.map((child) => (
                <div key={`${item.key}-${child.key}`} className="px-3 py-2">
                  {renderItem(child)}
                </div>
              ))}
            </McpResourceGroup>
          ) : (
            <div
              key={item.key}
              className="border-b border-[var(--color-border-separator)] px-3 py-2"
            >
              {renderItem(item)}
            </div>
          );
        })}
      </div>
    </ResourceDrawer>
  );
}
