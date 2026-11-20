// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, App, Button, Input, Segmented, Switch, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import { RefreshCw, Save, Search, X } from "lucide-react";

import { useSystemConfigurations } from "@/hooks/system/useSystemConfigurations";
import type { SystemConfigurationChanges } from "@/types/systemConfiguration";
import { ConfigTable } from "./components/ConfigTable";
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
    >
      <div className="w-full p-6">
        <header className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="m-0 text-xl font-semibold text-[var(--color-text-primary)]">
              {t("systemConfig.title")}
            </h1>
            <p className="mb-0 mt-1 text-xs leading-[18px] text-[var(--color-text-secondary)]">
              {t("systemConfig.subtitle")}
            </p>
          </div>
          <Tooltip title={t("systemConfig.refresh")}>
            <Button
              type="text"
              className="shrink-0"
              aria-label={t("systemConfig.refresh")}
              icon={
                <RefreshCw
                  className={isFetching ? "h-4 w-4 animate-spin" : "h-4 w-4"}
                />
              }
              onClick={() => void refetch()}
            />
          </Tooltip>
        </header>

        <div data-testid="config-content" className="w-full">
          {error ? (
            <Alert
              className="mt-4"
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
          {!error || items.length ? (
            <>
              <div
                data-testid="config-filter"
                className="mt-5 flex flex-wrap items-center gap-3"
              >
                <div className="w-full lg:w-[320px] lg:shrink-0">
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
                <Segmented
                  className="max-w-full [&_.ant-segmented-group]:flex-wrap"
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
              <ConfigTable
                key={`${query}\n${groupFilter}\n${onlyModified}`}
                items={visibleItems}
                loading={isLoading}
                valueOf={valueOf}
                isModified={isModified}
                errorByKey={errorByKey}
                onValueChange={updateDraft}
                onReset={(item) => updateDraft(item, item.default_value)}
              />
            </>
          ) : null}
          {changes.length ? (
            <div
              data-testid="config-save-bar"
              className="sticky bottom-0 z-20 mt-4 border-t border-[var(--color-border-separator)] bg-[var(--color-bg-5)] py-3"
            >
              <div className="flex flex-wrap items-center gap-3">
                <div className="min-w-0 flex-1">
                  <span className="text-[13px] text-[var(--color-text-primary)]">
                    {t("systemConfig.saveBar.count", { count: changes.length })}
                  </span>
                  {hasErrors ? (
                    <span className="ml-3 text-[11px] text-[var(--color-error)]">
                      {t("systemConfig.saveBar.invalid")}
                    </span>
                  ) : null}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    icon={<X className="h-4 w-4" />}
                    onClick={discardChanges}
                  >
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
            </div>
          ) : null}
        </div>
        <div className="h-4" />
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
