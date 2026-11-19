// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  Alert,
  App,
  Button,
  Empty,
  Input,
  Segmented,
  Spin,
  Switch,
  Tooltip,
} from "antd";
import { useTranslation } from "react-i18next";
import { ChevronRight, RefreshCw, Save, Search, X } from "lucide-react";

import { useSystemConfigurations } from "@/hooks/system/useSystemConfigurations";
import type { SystemConfigurationChanges } from "@/types/systemConfiguration";
import { ConfigRow } from "./components/ConfigRow";
import { ConfigSummary } from "./components/ConfigSummary";
import {
  SaveReviewModal,
  type ConfigChange,
} from "./components/SaveReviewModal";
import {
  CONFIG_GROUPS,
  validateConfigValue,
  type ConfigGroupId,
  type ConfigItem,
  type ConfigValue,
} from "./systemConfigData";

type GroupFilter = "all" | ConfigGroupId;

const CONFIG_PAGE_STYLE = {
  "--color-text-secondary": "var(--palette-gray-60)",
  "--color-icon-tertiary": "var(--palette-gray-60)",
} as CSSProperties;

export function SystemConfigPage() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { data, isLoading, isFetching, error, refetch, saveMutation } =
    useSystemConfigurations();
  const items = useMemo(() => data?.items ?? [], [data?.items]);
  const [drafts, setDrafts] = useState<Record<string, ConfigValue | null>>({});
  const editVersionsRef = useRef<Record<string, number>>({});
  const [query, setQuery] = useState("");
  const [groupFilter, setGroupFilter] = useState<GroupFilter>("all");
  const [onlyModified, setOnlyModified] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);

  const valueOf = (item: ConfigItem): ConfigValue | null =>
    Object.prototype.hasOwnProperty.call(drafts, item.key)
      ? drafts[item.key]
      : item.value;
  const isModified = (item: ConfigItem) => valueOf(item) !== item.value;

  const changes: ConfigChange[] = items.filter(isModified).map((item) => ({
    item,
    from: item.value,
    to: valueOf(item) as ConfigValue,
  }));
  const errorByKey = Object.fromEntries(
    items.map((item) => [
      item.key,
      isModified(item) ? validateConfigValue(item, valueOf(item)) : null,
    ])
  );
  const hasErrors = Object.values(errorByKey).some(Boolean);

  const updateDraft = (item: ConfigItem, value: ConfigValue | null) => {
    setDrafts((current) => ({ ...current, [item.key]: value }));
    const nextVersion = (editVersionsRef.current[item.key] ?? 0) + 1;
    editVersionsRef.current = {
      ...editVersionsRef.current,
      [item.key]: nextVersion,
    };
  };

  const discardChanges = () => {
    setDrafts({});
    editVersionsRef.current = {};
  };

  const performSave = async () => {
    const submitted = changes;
    if (!submitted.length || hasErrors) return;
    const payload: SystemConfigurationChanges = Object.fromEntries(
      submitted.map((change) => [change.item.key, change.to])
    );
    const versions = { ...editVersionsRef.current };
    try {
      const result = await saveMutation.mutateAsync(payload);
      setDrafts((current) => {
        const next = { ...current };
        submitted.forEach(({ item }) => {
          if (
            (versions[item.key] ?? 0) ===
            (editVersionsRef.current[item.key] ?? 0)
          )
            delete next[item.key];
        });
        return next;
      });
      const nextVersions = { ...editVersionsRef.current };
      submitted.forEach(({ item }) => {
        if ((versions[item.key] ?? 0) === (nextVersions[item.key] ?? 0))
          delete nextVersions[item.key];
      });
      editVersionsRef.current = nextVersions;
      setReviewOpen(false);
      if (result.notification === "degraded")
        message.warning(t("systemConfig.save.degraded"));
      else
        message.success(
          t("systemConfig.save.success", { count: submitted.length })
        );
    } catch (saveError) {
      message.error(
        saveError instanceof Error
          ? saveError.message
          : t("systemConfig.save.failed")
      );
    }
  };

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (!changes.length) return;
      event.preventDefault();
      event.returnValue = "";
    };
    const guardLinks = (event: MouseEvent) => {
      if (!changes.length || event.defaultPrevented) return;
      const anchor = (event.target as HTMLElement).closest("a[href]");
      if (anchor && !window.confirm(t("systemConfig.leaveWarning"))) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    };
    window.addEventListener("beforeunload", warn);
    document.addEventListener("click", guardLinks, true);
    return () => {
      window.removeEventListener("beforeunload", warn);
      document.removeEventListener("click", guardLinks, true);
    };
  }, [changes.length, t]);

  const hasUnsavedChanges = changes.length > 0;
  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const currentUrl = window.location.href;
    window.history.pushState(null, "", currentUrl);
    const guardHistory = () => {
      if (window.confirm(t("systemConfig.leaveWarning"))) {
        window.removeEventListener("popstate", guardHistory);
        window.history.back();
      } else {
        window.history.pushState(null, "", currentUrl);
      }
    };
    window.addEventListener("popstate", guardHistory);
    return () => window.removeEventListener("popstate", guardHistory);
  }, [hasUnsavedChanges, t]);

  const normalizedQuery = query.trim().toLowerCase();
  const visibleItems = items.filter((item) => {
    const matchesGroup = groupFilter === "all" || item.group === groupFilter;
    const matchesQuery =
      !normalizedQuery ||
      [item.key, t(item.label_key), t(item.description_key)]
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery);
    return matchesGroup && matchesQuery && (!onlyModified || isModified(item));
  });

  return (
    <div
      data-testid="config-page"
      className="min-h-full bg-[var(--color-bg-5)]"
      style={CONFIG_PAGE_STYLE}
    >
      <div className="mx-auto w-full max-w-[1200px] px-4 py-7 sm:px-6 lg:px-8">
        <header className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-1.5 text-[12px] text-[var(--color-text-secondary)]">
              <span>{t("systemConfig.breadcrumb.ops")}</span>
              <ChevronRight className="h-3 w-3" />
              <span>{t("systemConfig.breadcrumb.config")}</span>
            </div>
            <h1 className="mt-2 text-[24px] font-semibold text-[var(--color-text-primary)]">
              {t("systemConfig.title")}
            </h1>
            <p className="mt-2 max-w-[760px] text-[13px] leading-6 text-[var(--color-text-secondary)]">
              {t("systemConfig.subtitle")}
            </p>
          </div>
          <Tooltip title={t("systemConfig.refresh")}>
            <Button
              aria-label={t("systemConfig.refresh")}
              icon={
                <RefreshCw
                  className={isFetching ? "h-4 w-4 animate-spin" : "h-4 w-4"}
                />
              }
              onClick={() => void refetch()}
            >
              <span className="hidden sm:inline">
                {t("systemConfig.refresh")}
              </span>
            </Button>
          </Tooltip>
        </header>

        <Alert
          className="mt-5"
          type="info"
          showIcon
          title={t("systemConfig.notice")}
        />

        {!isLoading && !error ? (
          <div className="mt-4">
            <ConfigSummary
              itemCount={items.length}
              groupCount={CONFIG_GROUPS.length}
              modifiedCount={changes.length}
            />
          </div>
        ) : null}

        <div data-testid="config-filter" className="mt-5">
          <div className="flex flex-wrap items-center gap-3">
            <div className="w-full md:w-[300px]">
              <label
                htmlFor="system-config-search"
                className="mb-1 block text-[12px] font-medium text-[var(--color-text-secondary)]"
              >
                {t("systemConfig.searchLabel")}
              </label>
              <Input
                id="system-config-search"
                allowClear
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                prefix={
                  <Search className="h-4 w-4 text-[var(--color-icon-tertiary)]" />
                }
                placeholder={t("systemConfig.searchPlaceholder")}
                className="w-full"
              />
            </div>
            <div className="max-w-full">
              <Segmented
                className="[&_.ant-segmented-group]:flex-wrap"
                value={groupFilter}
                onChange={(value) => setGroupFilter(value as GroupFilter)}
                options={[
                  {
                    label: `${t("systemConfig.filter.all")} ${items.length}`,
                    value: "all",
                  },
                  ...CONFIG_GROUPS.map((group) => ({
                    label: `${t(group.labelKey)} ${items.filter((item) => item.group === group.id).length}`,
                    value: group.id,
                  })),
                ]}
              />
            </div>
            <label className="flex cursor-pointer items-center gap-2 text-[12px] text-[var(--color-text-secondary)] md:ml-auto">
              <Switch
                size="small"
                checked={onlyModified}
                onChange={setOnlyModified}
                aria-label={t("systemConfig.onlyModified")}
              />
              {t("systemConfig.onlyModified")}
            </label>
          </div>
        </div>

        {isLoading ? (
          <div className="mt-6 flex justify-center rounded-lg border border-[var(--color-border-separator)] bg-[var(--color-bg-5)] py-20 shadow-sm">
            <Spin aria-label={t("systemConfig.loading")} />
          </div>
        ) : null}
        {error ? (
          <Alert
            className="mt-6 rounded-lg shadow-sm"
            type="error"
            showIcon
            message={error.message}
            action={
              <Button onClick={() => void refetch()}>
                {t("systemConfig.retry")}
              </Button>
            }
          />
        ) : null}
        {!isLoading && !error
          ? CONFIG_GROUPS.map((group) => {
              const groupItems = visibleItems.filter(
                (item) => item.group === group.id
              );
              if (!groupItems.length) return null;
              return (
                <section key={group.id} className="mt-6">
                  <div className="mb-3 flex items-end justify-between gap-4">
                    <div>
                      <h2 className="text-[15px] font-semibold text-[var(--color-text-primary)]">
                        {t(group.labelKey)}
                      </h2>
                      <p className="mt-1 text-[12px] text-[var(--color-text-secondary)]">
                        {t(group.descriptionKey)}
                      </p>
                    </div>
                    <span className="text-[11px] text-[var(--color-text-secondary)]">
                      {t("systemConfig.paramCount", {
                        count: groupItems.length,
                      })}
                    </span>
                  </div>
                  <div className="overflow-hidden rounded-lg border border-[var(--color-border-separator-subtle)] bg-[var(--color-bg-5)] shadow-sm">
                    <div className="overflow-x-auto">
                      <div className="min-w-[860px]">
                        <div className="grid grid-cols-[minmax(280px,1.7fr)_190px_160px_180px_32px] gap-4 border-b border-[var(--color-border-separator-subtle)] bg-[var(--color-table-header)] px-5 py-2 text-[11px] text-[var(--color-text-secondary)]">
                          <span>{t("systemConfig.table.parameter")}</span>
                          <span>{t("systemConfig.table.value")}</span>
                          <span>{t("systemConfig.table.range")}</span>
                          <span>{t("systemConfig.table.effect")}</span>
                          <span />
                        </div>
                        <div className="divide-y divide-[var(--color-border-separator-subtle)]">
                          {groupItems.map((item) => (
                            <ConfigRow
                              key={item.key}
                              item={item}
                              value={valueOf(item)}
                              modified={isModified(item)}
                              errorKey={errorByKey[item.key]}
                              onValueChange={(value) =>
                                updateDraft(item, value)
                              }
                              onReset={() =>
                                updateDraft(item, item.default_value)
                              }
                            />
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                </section>
              );
            })
          : null}
        {!isLoading && !error && !visibleItems.length ? (
          <div className="mt-6 rounded-lg border border-[var(--color-border-separator)] bg-[var(--color-bg-5)] py-10 shadow-sm">
            <Empty description={t("systemConfig.empty")} />
          </div>
        ) : null}
        {changes.length ? (
          <div className="sticky bottom-4 z-30 rounded-lg border border-[var(--color-border-separator)] bg-[var(--color-bg-5)] px-4 py-3 shadow-lg">
            <div className="flex flex-wrap items-center gap-3">
              <span className="rounded-xs bg-[var(--color-select)] px-2 py-0.5 text-[12px] font-medium text-[var(--color-brand)]">
                {changes.length}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium text-[var(--color-text-primary)]">
                  {t("systemConfig.saveBar.count", { count: changes.length })}
                </div>
                {hasErrors ? (
                  <div className="text-[11px] text-[var(--color-error)]">
                    {t("systemConfig.saveBar.invalid")}
                  </div>
                ) : null}
              </div>
              <Button icon={<X className="h-4 w-4" />} onClick={discardChanges}>
                {t("systemConfig.discard")}
              </Button>
              <Button
                type="primary"
                icon={<Save className="h-4 w-4" />}
                disabled={hasErrors}
                onClick={() => setReviewOpen(true)}
              >
                {t("systemConfig.saveBar.action")}
              </Button>
            </div>
          </div>
        ) : null}
        <div className="h-16" />
      </div>

      <SaveReviewModal
        open={reviewOpen}
        changes={changes}
        saving={saveMutation.isPending}
        onCancel={() => setReviewOpen(false)}
        onConfirm={() => void performSave()}
      />
    </div>
  );
}
