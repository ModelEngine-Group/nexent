// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useMemo, useState } from "react";
import { Button, InputNumber, Modal, Switch, Table } from "antd";
import type { TableColumnsType } from "antd";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import ResizableTableHeader, {
  type ResizableTableHeaderProps,
} from "@/components/table/ResizableTableHeader";
import { cn } from "@/lib/utils";
import type { ConfigItem, ConfigValue } from "../systemConfigData";
import { formatConfigValue } from "../systemConfigFormat";

const DEFAULT_COLUMN_WIDTHS = {
  parameter: 340,
  value: 220,
  range: 200,
  actions: 96,
};

const MIN_COLUMN_WIDTHS = {
  parameter: 240,
  value: 180,
  range: 140,
  actions: 88,
};

type ConfigColumnKey = keyof typeof DEFAULT_COLUMN_WIDTHS;

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
}

function ConfigDetail({ item }: ConfigDetailProps) {
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
      description: (
        <code className="block overflow-x-auto whitespace-nowrap font-mono">
          {item.key}
        </code>
      ),
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
    <div data-testid={`config-detail-${item.key}`} className="py-1">
      <dl className="m-0 divide-y divide-[var(--color-border-separator-subtle)]">
        {details.map(({ key, term, description }) => (
          <div
            key={key}
            className="grid grid-cols-[112px_minmax(0,1fr)] gap-x-4 py-3 first:pt-1 last:pb-1"
          >
            <dt className="text-[12px] leading-5 text-[var(--color-text-secondary)]">
              {term}
            </dt>
            <dd className="m-0 min-w-0 break-words text-[13px] leading-5 text-[var(--color-text-primary)]">
              {description}
            </dd>
          </div>
        ))}
      </dl>
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
  const [detailItem, setDetailItem] = useState<ConfigItem | null>(null);
  const [columnWidths, setColumnWidths] = useState(DEFAULT_COLUMN_WIDTHS);

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
    {
      title: "",
      key: "actions",
      align: "center",
      render: (_, item) => (
        <Button
          size="small"
          aria-label={t("systemConfig.detail.openFor", {
            name: t(item.label_key),
          })}
          aria-haspopup="dialog"
          onClick={() => setDetailItem(item)}
        >
          {t("systemConfig.detail.action")}
        </Button>
      ),
    },
  ];

  const resizableColumns = columns.map((column) => {
    const key = column.key as ConfigColumnKey;
    const headerLabel =
      key === "actions"
        ? t("systemConfig.detail.action")
        : (column.title as string);
    return {
      ...column,
      width: columnWidths[key],
      onHeaderCell: () =>
        ({
          "aria-label": headerLabel,
          className: "relative !overflow-visible select-none",
          resizeWidth: columnWidths[key],
          minWidth: MIN_COLUMN_WIDTHS[key],
          resizeLabel: t("systemConfig.resizeColumn", {
            column: headerLabel,
          }),
          resizeFromStart: key === "actions",
          onResizeWidth: (width: number) =>
            setColumnWidths((current) => ({ ...current, [key]: width })),
        }) as ResizableTableHeaderProps,
    };
  });

  return (
    <>
      <Table<ConfigItem>
        data-testid="config-table"
        bordered
        className="mt-4 [&_.ant-table-cell]:align-middle"
        rowKey="key"
        columns={resizableColumns}
        components={{ header: { cell: ResizableTableHeader } }}
        tableLayout="fixed"
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
        scroll={{
          x: Object.values(columnWidths).reduce(
            (total, width) => total + width,
            0
          ),
        }}
        locale={{ emptyText: t("systemConfig.empty") }}
        onRow={(item) => ({
          className: "system-config-row",
          "data-testid": `config-row-${item.key}`,
        })}
      />
      <Modal
        open={detailItem !== null}
        title={
          detailItem
            ? `${t(detailItem.label_key)} · ${t("systemConfig.detail.title")}`
            : t("systemConfig.detail.title")
        }
        onCancel={() => setDetailItem(null)}
        footer={
          detailItem ? (
            <Button
              onClick={() => onReset(detailItem)}
              disabled={valueOf(detailItem) === detailItem.default_value}
              aria-label={t("systemConfig.resetDefaultFor", {
                name: t(detailItem.label_key),
              })}
              icon={<RotateCcw className="h-4 w-4" />}
            >
              {t("systemConfig.resetDefault")}
            </Button>
          ) : null
        }
        width={720}
        destroyOnHidden
      >
        {detailItem ? <ConfigDetail item={detailItem} /> : null}
      </Modal>
    </>
  );
}
