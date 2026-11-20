// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useMemo, useState } from "react";
import { Button, InputNumber, Switch, Table, Tooltip } from "antd";
import type { TableColumnsType } from "antd";
import { AlertTriangle, ChevronDown, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import type { ConfigItem, ConfigValue } from "../systemConfigData";
import { formatConfigValue } from "../systemConfigFormat";

interface ConfigTableProps {
  items: ConfigItem[];
  loading: boolean;
  valueOf: (item: ConfigItem) => ConfigValue | null;
  isModified: (item: ConfigItem) => boolean;
  errorByKey: Record<string, string | null>;
  onValueChange: (item: ConfigItem, value: ConfigValue | null) => void;
  onReset: (item: ConfigItem) => void;
}

interface ConfigDetailProps {
  item: ConfigItem;
  value: ConfigValue | null;
  onReset: () => void;
}

function ConfigDetail({ item, value, onReset }: ConfigDetailProps) {
  const { t } = useTranslation("common");
  const kindLabel =
    item.kind === "boolean"
      ? t("systemConfig.booleanType")
      : item.kind === "integer"
        ? t("systemConfig.integerType")
        : t("systemConfig.decimalType");
  const details = [
    {
      key: "key",
      term: t("systemConfig.detail.key"),
      description: <code className="break-all font-mono">{item.key}</code>,
    },
    {
      key: "group",
      term: t("systemConfig.detail.group"),
      description: t(`systemConfig.group.${item.group}`),
    },
    {
      key: "default",
      term: t("systemConfig.detail.defaultValue"),
      description: formatConfigValue(item, item.default_value, t),
    },
    {
      key: "kind",
      term: t("systemConfig.detail.kind"),
      description: kindLabel,
    },
    {
      key: "effect",
      term: t("systemConfig.detail.effect"),
      description: t(item.effect_key),
    },
  ];

  return (
    <div
      data-testid={`config-detail-${item.key}`}
      className="bg-[var(--color-fill)] px-4 py-3"
    >
      <div className="flex flex-wrap items-end gap-3">
        <dl className="m-0 grid min-w-0 flex-1 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {details.map(({ key, term, description }) => (
            <div key={key} className="min-w-0">
              <dt className="text-[11px] leading-4 text-[var(--color-text-secondary)]">
                {term}
              </dt>
              <dd className="m-0 mt-1 break-words text-[12px] leading-5 text-[var(--color-text-primary)]">
                {description}
              </dd>
            </div>
          ))}
        </dl>
        <Button
          size="small"
          onClick={onReset}
          disabled={value === item.default_value}
          aria-label={t("systemConfig.resetDefaultFor", {
            name: t(item.label_key),
          })}
          icon={<RotateCcw className="h-3.5 w-3.5" />}
        >
          {t("systemConfig.resetDefault")}
        </Button>
      </div>
    </div>
  );
}

export function ConfigTable({
  items,
  loading,
  valueOf,
  isModified,
  errorByKey,
  onValueChange,
  onReset,
}: ConfigTableProps) {
  const { t } = useTranslation("common");
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const visiblePage = Math.min(currentPage, pageCount);
  const pagedItems = useMemo(
    () => items.slice((visiblePage - 1) * pageSize, visiblePage * pageSize),
    [items, pageSize, visiblePage]
  );

  const columns: TableColumnsType<ConfigItem> = [
    {
      title: t("systemConfig.table.parameter"),
      key: "parameter",
      render: (_, item) => {
        const label = t(item.label_key);
        const modified = isModified(item);
        return (
          <div className="min-w-0 py-0.5">
            <div className="flex items-center gap-2">
              <label
                htmlFor={`config-input-${item.key}`}
                className="text-[13px] font-medium text-[var(--color-text-primary)]"
              >
                {label}
              </label>
              {modified ? (
                <span className="shrink-0 text-[11px] text-[var(--color-brand)]">
                  {t("systemConfig.modifiedTag")}
                </span>
              ) : null}
            </div>
            <p className="mb-0 mt-1 text-[12px] leading-5 text-[var(--color-text-secondary)]">
              {t(item.description_key)}
            </p>
          </div>
        );
      },
    },
    {
      title: t("systemConfig.table.value"),
      key: "value",
      width: 220,
      align: "center",
      render: (_, item) => {
        const label = t(item.label_key);
        const value = valueOf(item);
        const modified = isModified(item);
        const errorKey = errorByKey[item.key];
        return (
          <div
            data-testid={`config-value-${item.key}`}
            className={cn(
              "relative flex items-center justify-center text-center",
              errorKey || modified ? "min-h-[56px]" : "min-h-[44px]"
            )}
          >
            {item.kind === "boolean" ? (
              <div className="flex items-center justify-center gap-2">
                <Switch
                  size="small"
                  checked={value === true}
                  onChange={(next) => onValueChange(item, next)}
                  aria-label={label}
                />
                <span className="text-[12px] text-[var(--color-text-secondary)]">
                  {formatConfigValue(item, value, t)}
                </span>
              </div>
            ) : (
              <div className="flex items-center justify-center gap-1.5">
                <InputNumber
                  id={`config-input-${item.key}`}
                  size="small"
                  value={typeof value === "number" ? value : null}
                  min={item.kind === "integer" ? 1 : undefined}
                  step={item.kind === "integer" ? 1 : 0.1}
                  precision={item.kind === "integer" ? 0 : undefined}
                  controls={false}
                  status={errorKey ? "error" : undefined}
                  onChange={(next) => onValueChange(item, next)}
                  aria-label={label}
                  className={cn(
                    "!w-[120px]",
                    modified && !errorKey && "!border-[var(--color-brand)]"
                  )}
                />
                {item.unit_key ? (
                  <span className="text-[11px] text-[var(--color-text-secondary)]">
                    {t(item.unit_key)}
                  </span>
                ) : null}
              </div>
            )}
            <div className="absolute inset-x-0 bottom-0 min-h-[16px] text-[11px] leading-4">
              {errorKey ? (
                <span className="inline-flex items-center gap-1 text-[var(--color-error)]">
                  <AlertTriangle className="h-3 w-3" />
                  {t(errorKey)}
                </span>
              ) : modified ? (
                <span className="text-[var(--color-text-secondary)]">
                  {t("systemConfig.originalValue")}{" "}
                  {formatConfigValue(item, item.value, t)}
                </span>
              ) : null}
            </div>
          </div>
        );
      },
    },
    {
      title: t("systemConfig.table.range"),
      key: "range",
      width: 200,
      align: "center",
      render: (_, item) => (
        <span className="text-[12px] text-[var(--color-text-secondary)]">
          {item.kind === "boolean"
            ? t("systemConfig.booleanRange")
            : item.kind === "integer"
              ? t("systemConfig.integerRange")
              : t("systemConfig.numberRange")}
        </span>
      ),
    },
  ];

  return (
    <Table<ConfigItem>
      data-testid="config-table"
      bordered
      className="mt-4 [&_.ant-table-cell]:align-middle"
      rowKey="key"
      columns={[...columns, Table.EXPAND_COLUMN]}
      dataSource={pagedItems}
      loading={loading}
      pagination={{
        current: visiblePage,
        pageSize,
        total: items.length,
        showSizeChanger: true,
        pageSizeOptions: [10, 20, 50],
        showTotal: (total) => t("common.pagination.total", { total }),
        onChange: (page, nextPageSize) => {
          if (nextPageSize !== pageSize) {
            setPageSize(nextPageSize);
            setCurrentPage(1);
          } else {
            setCurrentPage(page);
          }
        },
      }}
      scroll={{ x: 760 }}
      locale={{ emptyText: t("systemConfig.empty") }}
      expandable={{
        columnWidth: 48,
        expandedRowRender: (item) => (
          <ConfigDetail
            item={item}
            value={valueOf(item)}
            onReset={() => onReset(item)}
          />
        ),
        expandIcon: ({ expanded, onExpand, record: item }) => (
          <Tooltip
            title={
              expanded ? t("systemConfig.collapse") : t("systemConfig.expand")
            }
          >
            <Button
              type="text"
              size="small"
              className="!h-7 !w-7 !p-0"
              aria-label={t(
                expanded
                  ? "systemConfig.detail.closeFor"
                  : "systemConfig.detail.openFor",
                { name: t(item.label_key) }
              )}
              aria-expanded={expanded}
              onClick={(event) => onExpand(item, event)}
              icon={
                <ChevronDown
                  className={`h-4 w-4 transition-transform duration-150 ${
                    expanded ? "rotate-180" : ""
                  }`}
                />
              }
            />
          </Tooltip>
        ),
      }}
      onRow={(item) => ({
        className: "system-config-row",
        "data-testid": `config-row-${item.key}`,
      })}
    />
  );
}
