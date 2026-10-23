"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  ConfigProvider,
  Empty,
  Input,
  InputNumber,
  Modal,
  Progress,
  Segmented,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Tooltip,
  message,
} from "antd";
import { Search, Settings2 } from "lucide-react";
import { ColumnsType, TableProps } from "antd/es/table";
import { useAuthorization } from "@/hooks/auth/useAuthorization";
import { useTenantList } from "@/hooks/tenant/useTenantList";
import { USER_ROLES } from "@/const/auth";
import { ErrorCode } from "@/const/errorCode";
import quotaService from "@/services/quotaService";
import { ApiError } from "@/services/api";
import type {
  PersonalCapacitySummary,
  PersonalCapacityUser,
  PersonalDefaultQuota,
  PersonalKnowledgeBaseItem,
  PersonalQuotaPayload,
} from "@/types/quota";

const GB = 1024 * 1024 * 1024;
const MB = 1024 * 1024;
const DEFAULT_PAGE_SIZE = 10;
const DETAIL_PAGE_SIZE = 100;

const PERSONAL_CAPACITY_TABLE_THEME = {
  components: {
    Table: {
      headerSortActiveBg: "transparent",
      headerSortHoverBg: "transparent",
      bodySortBg: "transparent",
    },
  },
};

type SortField =
  "kb_count" | "total_bytes" | "quota_limit_bytes" | "usage_rate";
type SortOrder = "asc" | "desc";

const SORT_FIELDS: SortField[] = [
  "kb_count",
  "total_bytes",
  "quota_limit_bytes",
  "usage_rate",
];

function isSortField(value: string): value is SortField {
  return (SORT_FIELDS as string[]).includes(value);
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "-";
  if (bytes >= GB) return `${(bytes / GB).toFixed(1)} GB`;
  if (bytes >= MB) return `${(bytes / MB).toFixed(1)} MB`;
  return `${bytes} B`;
}

function formatDateTime(date: string | null | undefined): string {
  if (!date) return "-";
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) return "-";
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${parsed.getFullYear()}/${pad(parsed.getMonth() + 1)}/${pad(
    parsed.getDate()
  )} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(
    parsed.getSeconds()
  )}`;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function getLocalizedQuotaErrorMessage(
  error: unknown,
  t: (key: string, options?: Record<string, unknown>) => string
): string {
  if (error instanceof ApiError) {
    const code = String(error.code);
    if (
      code === ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED ||
      code === ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE
    ) {
      return t(`errorCode.${code}`);
    }
  }
  return getErrorMessage(error);
}

function getQuotaSubmitErrorMessage(
  error: unknown,
  t: (key: string, options?: Record<string, unknown>) => string
): string {
  if (
    error instanceof ApiError &&
    error.code === ErrorCode.TENANT_PERSONAL_KB_QUOTA_BELOW_USAGE
  ) {
    const usageBytes = error.details?.usage_bytes;
    const usage =
      typeof usageBytes === "number" ? formatBytes(usageBytes) : "-";
    return t("tenantResources.personalCapacity.quotaBelowUsageWarning", {
      usage,
    });
  }
  return getLocalizedQuotaErrorMessage(error, t);
}

function CompactUserSearchFilter({
  value,
  onChange,
  placeholder,
  close,
  visible,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  close: () => void;
  visible: boolean;
}) {
  const { t } = useTranslation("common");
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    if (visible) setDraft(value);
  }, [visible, value]);

  const commit = (next: string) => {
    onChange(next.trim());
    close();
  };

  return (
    <div className="p-2" onKeyDown={(event) => event.stopPropagation()}>
      <Input
        autoFocus
        allowClear
        className="w-56"
        prefix={<Search size={14} className="text-gray-400" aria-hidden />}
        value={draft}
        placeholder={placeholder}
        onChange={(event) => setDraft(event.target.value)}
        onPressEnter={() => commit(draft)}
        onKeyDown={(event) => {
          if (event.key === "Escape") close();
        }}
      />
      <div className="flex items-center justify-end gap-2 pt-2">
        <Button size="small" onClick={() => commit("")}>
          {t("tenantResources.personalCapacity.resetSearch")}
        </Button>
        <Button type="primary" size="small" onClick={() => commit(draft)}>
          {t("tenantResources.personalCapacity.confirmSearch")}
        </Button>
      </div>
    </div>
  );
}

interface PersonalQuotaModalProps {
  open: boolean;
  mode: "user" | "default";
  title: string;
  currentBytes: number | null;
  currentUsageBytes?: number | null;
  currentUsageReadable?: string | null;
  onCancel: () => void;
  onSubmit: (payload: PersonalQuotaPayload) => Promise<void>;
}

function PersonalQuotaModal({
  open,
  mode,
  title,
  currentBytes,
  currentUsageBytes,
  currentUsageReadable,
  onCancel,
  onSubmit,
}: PersonalQuotaModalProps) {
  const { t } = useTranslation("common");
  const [unit, setUnit] = useState<"GB" | "MB">("GB");
  const [value, setValue] = useState<number | null>(null);
  const [unlimited, setUnlimited] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (currentBytes != null && currentBytes > 0) {
      setUnlimited(false);
      if (currentBytes < GB) {
        setUnit("MB");
        setValue(Math.round(currentBytes / MB));
      } else {
        setUnit("GB");
        setValue(Math.round(currentBytes / GB));
      }
    } else {
      setUnlimited(true);
      setUnit("GB");
      setValue(null);
    }
  }, [open, currentBytes]);

  const changeUnit = (nextUnit: "GB" | "MB") => {
    if (nextUnit === unit) return;
    const bytes = value == null ? null : value * (unit === "GB" ? GB : MB);
    setUnit(nextUnit);
    setValue(
      bytes == null ? null : Math.round(bytes / (nextUnit === "GB" ? GB : MB))
    );
  };

  const handleSave = async () => {
    if (!unlimited && (value == null || value <= 0)) {
      message.error(
        t("tenantResources.personalCapacity.positiveQuotaRequired")
      );
      return;
    }
    const quotaBytes = value == null ? null : value * (unit === "GB" ? GB : MB);
    setSaving(true);
    try {
      await onSubmit(
        unlimited
          ? { unlimited: true }
          : {
              quota_limit_bytes: quotaBytes,
            }
      );
    } catch {
      // Parent already surfaces the error; keep the modal open.
    } finally {
      setSaving(false);
    }
  };

  const quotaBytes = value == null ? null : value * (unit === "GB" ? GB : MB);
  const belowUsage =
    mode === "user" &&
    !unlimited &&
    quotaBytes != null &&
    currentUsageBytes != null &&
    currentUsageBytes > 0 &&
    quotaBytes < currentUsageBytes;
  const usageText = currentUsageReadable || formatBytes(currentUsageBytes);

  return (
    <Modal
      title={title}
      open={open}
      onCancel={onCancel}
      onOk={handleSave}
      confirmLoading={saving}
      okText={t("common.save")}
      cancelText={t("common.cancel")}
      width={520}
      destroyOnHidden
    >
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        {mode === "user" && (
          <div className="text-sm text-gray-600">
            {t("tenantResources.personalCapacity.userQuotaDesc")}
          </div>
        )}
        {mode === "default" && (
          <div className="text-sm text-gray-600">
            {t("tenantResources.personalCapacity.defaultQuotaDesc")}
          </div>
        )}
        {mode === "user" && (
          <div className="flex items-baseline justify-between">
            <span className="text-sm text-gray-500">
              {t("tenantResources.personalCapacity.currentUsage")}
            </span>
            <span className="text-xl font-semibold">{usageText}</span>
          </div>
        )}
        {mode === "default" && (
          <div className="flex items-baseline justify-between">
            <span className="text-sm text-gray-500">
              {t("tenantResources.personalCapacity.currentQuota")}
            </span>
            <span className="text-xl font-semibold">
              {currentBytes == null
                ? t("quota.unlimited")
                : formatBytes(currentBytes)}
            </span>
          </div>
        )}
        <div className="flex items-center gap-2">
          <Switch checked={unlimited} onChange={setUnlimited} />
          <span className="text-sm">
            {mode === "default"
              ? t("tenantResources.personalCapacity.unlimitedDefault")
              : t("tenantResources.personalCapacity.unlimitedQuota")}
          </span>
        </div>
        {!unlimited && (
          <Space>
            <InputNumber
              min={1}
              precision={0}
              value={value}
              onChange={(nextValue) => setValue(nextValue ?? null)}
              addonAfter={unit}
              placeholder={t("tenantResources.personalCapacity.finiteQuota")}
              style={{ width: 220 }}
            />
            <Segmented
              options={["GB", "MB"]}
              value={unit}
              onChange={(nextUnit) => changeUnit(nextUnit as "GB" | "MB")}
            />
          </Space>
        )}
        {mode === "default" && (
          <div className="text-xs text-gray-500">
            {t("tenantResources.personalCapacity.defaultQuotaChangeNote")}
          </div>
        )}
        {belowUsage && (
          <Alert
            type="warning"
            showIcon
            title={t(
              "tenantResources.personalCapacity.quotaBelowUsageWarning",
              {
                usage: usageText,
              }
            )}
          />
        )}
      </Space>
    </Modal>
  );
}

interface KbDetailModalProps {
  kb: PersonalKnowledgeBaseItem | null;
  onClose: () => void;
}

function KbDetailModal({ kb, onClose }: KbDetailModalProps) {
  const { t } = useTranslation("common");
  if (!kb) return null;

  const quotaText =
    kb.quota_limit_bytes == null
      ? t("quota.unlimited")
      : kb.quota_limit_readable || formatBytes(kb.quota_limit_bytes);
  const stats = [
    {
      label: t("tenantResources.personalCapacity.sourceSizeLabel"),
      value:
        kb.source_size ||
        (kb.source_size_bytes != null
          ? formatBytes(kb.source_size_bytes)
          : "-"),
    },
    {
      label: t("tenantResources.personalCapacity.esPhysicalSizeLabel"),
      value:
        kb.es_physical_size ||
        kb.store_size ||
        formatBytes(kb.es_physical_size_bytes ?? kb.store_size_bytes),
    },
    {
      label: t("tenantResources.personalCapacity.documents"),
      value: kb.doc_count ?? 0,
    },
    {
      label: t("tenantResources.personalCapacity.chunks"),
      value: kb.chunk_count ?? 0,
    },
    {
      label: t("tenantResources.personalCapacity.kbQuota"),
      value: quotaText,
    },
  ];
  const infoRows = [
    {
      label: t("tenantResources.personalCapacity.source"),
      value: kb.source || t("common.unknown"),
    },
    {
      label: t("tenantResources.personalCapacity.kbQuota"),
      value: quotaText,
    },
    {
      label: t("tenantResources.personalCapacity.lastUpdated"),
      value: formatDateTime(kb.updated_at),
    },
  ];

  return (
    <Modal
      open
      onCancel={onClose}
      title={<span className="text-base font-medium">{kb.name || "-"}</span>}
      footer={
        <Button type="primary" onClick={onClose}>
          {t("common.close")}
        </Button>
      }
      width={600}
      destroyOnHidden
    >
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        {stats.map((stat) => (
          <div
            key={stat.label}
            className="border border-gray-200 rounded-md p-3"
          >
            <div className="text-sm font-semibold truncate">{stat.value}</div>
            <div className="text-xs text-gray-500 mt-1">{stat.label}</div>
          </div>
        ))}
      </div>
      <div className="border border-gray-200 rounded-md overflow-hidden">
        <div className="px-3 py-2 text-sm font-medium bg-gray-50">
          {t("tenantResources.personalCapacity.basicInfo")}
        </div>
        <div className="divide-y divide-gray-100">
          {infoRows.map((row) => (
            <div
              key={row.label}
              className="flex items-center justify-between px-3 py-2 text-sm"
            >
              <span className="text-gray-500">{row.label}</span>
              <span className="font-medium text-right">{row.value}</span>
            </div>
          ))}
        </div>
      </div>
    </Modal>
  );
}

export default function PersonalKnowledgeBaseCapacity({
  tenantId,
}: {
  tenantId: string | null;
}) {
  const { t } = useTranslation("common");
  const { user, hasPermission } = useAuthorization();
  const userRole = user?.role ?? "";
  const isSuperAdmin =
    userRole === USER_ROLES.SU || userRole === USER_ROLES.SPEED;
  const canRead = hasPermission("kb.capacity:read");
  const canManage = hasPermission("kb.capacity:manage");

  const { data: tenantData, isLoading: tenantsLoading } = useTenantList({
    page: 1,
    page_size: 100,
    enabled: isSuperAdmin,
  });

  const [viewTenantId, setViewTenantId] = useState<string | null>(tenantId);
  useEffect(() => {
    setViewTenantId(tenantId);
  }, [tenantId]);

  const [search, setSearch] = useState("");
  const keyword = search.trim();

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [sortBy, setSortBy] = useState<SortField>("total_bytes");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");
  const [users, setUsers] = useState<PersonalCapacityUser[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const [summary, setSummary] = useState<PersonalCapacitySummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [defaultQuota, setDefaultQuota] = useState<PersonalDefaultQuota | null>(
    null
  );
  const [defaultQuotaLoading, setDefaultQuotaLoading] = useState(false);

  const [detailMap, setDetailMap] = useState<
    Record<string, PersonalKnowledgeBaseItem[]>
  >({});
  const [detailLoading, setDetailLoading] = useState<Record<string, boolean>>(
    {}
  );
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);
  const [kbDetailTarget, setKbDetailTarget] =
    useState<PersonalKnowledgeBaseItem | null>(null);

  const [quotaModalOpen, setQuotaModalOpen] = useState(false);
  const [quotaModalMode, setQuotaModalMode] = useState<"user" | "default">(
    "user"
  );
  const [quotaTarget, setQuotaTarget] = useState<PersonalCapacityUser | null>(
    null
  );

  useEffect(() => {
    setPage(1);
  }, [viewTenantId, search]);

  useEffect(() => {
    setDetailMap({});
    setDetailLoading({});
    setExpandedKeys([]);
  }, [viewTenantId]);

  useEffect(() => {
    if (!viewTenantId) return;
    let cancelled = false;
    setLoading(true);
    quotaService
      .listPersonalCapacityUsers({
        tenantId: viewTenantId,
        page,
        page_size: pageSize,
        sort_by: sortBy,
        sort_order: sortOrder,
        keyword,
      })
      .then((data) => {
        if (cancelled) return;
        setUsers(data.items);
        setTotal(data.total);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          message.error(
            getLocalizedQuotaErrorMessage(err, t) ||
              t("tenantResources.personalCapacity.loadFailed")
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [viewTenantId, keyword, page, pageSize, sortBy, sortOrder, reloadKey, t]);

  useEffect(() => {
    if (!viewTenantId) {
      setSummary(null);
      setDefaultQuota(null);
      return;
    }
    let cancelled = false;
    setSummaryLoading(true);
    setDefaultQuotaLoading(true);
    quotaService
      .getPersonalCapacitySummary(viewTenantId)
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          console.warn(
            "Failed to fetch personal KB capacity summary:",
            getErrorMessage(err)
          );
        }
      })
      .finally(() => {
        if (!cancelled) setSummaryLoading(false);
      });
    quotaService
      .getPersonalDefaultQuota(viewTenantId)
      .then((data) => {
        if (!cancelled) setDefaultQuota(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          console.warn(
            "Failed to fetch personal KB default quota:",
            getErrorMessage(err)
          );
        }
      })
      .finally(() => {
        if (!cancelled) setDefaultQuotaLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [viewTenantId, reloadKey]);

  const handleExpand = useCallback(
    (expanded: boolean, record: PersonalCapacityUser) => {
      setExpandedKeys((prev) =>
        expanded
          ? Array.from(new Set([...prev, record.user_id]))
          : prev.filter((id) => id !== record.user_id)
      );
      if (
        !expanded ||
        !viewTenantId ||
        detailMap[record.user_id] ||
        detailLoading[record.user_id]
      ) {
        return;
      }
      setDetailLoading((prev) => ({ ...prev, [record.user_id]: true }));
      quotaService
        .getPersonalKbDetails(record.user_id, viewTenantId, 1, DETAIL_PAGE_SIZE)
        .then((data) => {
          setDetailMap((prev) => ({
            ...prev,
            [record.user_id]: data.kbs,
          }));
        })
        .catch((err: unknown) => {
          message.error(
            getLocalizedQuotaErrorMessage(err, t) ||
              t("tenantResources.personalCapacity.detailLoadFailed")
          );
        })
        .finally(() => {
          setDetailLoading((prev) => ({
            ...prev,
            [record.user_id]: false,
          }));
        });
    },
    [viewTenantId, detailMap, detailLoading, t]
  );

  const handleQuotaSubmit = useCallback(
    async (payload: PersonalQuotaPayload) => {
      if (!viewTenantId) return;
      try {
        if (quotaModalMode === "user" && quotaTarget) {
          await quotaService.setPersonalUserQuota(
            quotaTarget.user_id,
            viewTenantId,
            payload
          );
        } else {
          await quotaService.setPersonalDefaultQuota(viewTenantId, payload);
        }
        message.success(t("tenantResources.personalCapacity.quotaUpdated"));
        setQuotaModalOpen(false);
        setReloadKey((key) => key + 1);
      } catch (err: unknown) {
        message.error(
          getQuotaSubmitErrorMessage(err, t) ||
            t("tenantResources.personalCapacity.quotaUpdateFailed")
        );
      }
    },
    [viewTenantId, quotaModalMode, quotaTarget, t]
  );

  const handleTableChange: TableProps<PersonalCapacityUser>["onChange"] = (
    pagination,
    _filters,
    sorter
  ) => {
    if (pagination.current) setPage(pagination.current);
    if (pagination.pageSize) setPageSize(pagination.pageSize);
    const singleSorter = Array.isArray(sorter) ? sorter[0] : sorter;
    const field = String(singleSorter?.field ?? "");
    if (isSortField(field) && singleSorter?.order) {
      setSortBy(field);
      setSortOrder(singleSorter.order === "ascend" ? "asc" : "desc");
    }
  };

  const sortOrderFor = (field: SortField): "ascend" | "descend" | null =>
    sortBy === field ? (sortOrder === "asc" ? "ascend" : "descend") : null;

  const defaultQuotaText = useMemo(() => {
    if (summary?.default_quota_bytes != null) {
      return (
        summary.default_quota_readable ||
        formatBytes(summary.default_quota_bytes)
      );
    }
    if (defaultQuota?.unlimited || defaultQuota?.quota_limit_bytes == null) {
      return t("quota.unlimited");
    }
    return (
      defaultQuota.quota_limit_readable ||
      formatBytes(defaultQuota.quota_limit_bytes)
    );
  }, [summary, defaultQuota, t]);

  const statCards = useMemo(() => {
    const cards: Array<{
      key: string;
      label: string;
      value: React.ReactNode;
      action?: React.ReactNode;
    }> = [
      {
        key: "users",
        label: t("tenantResources.personalCapacity.usersWithPersonalKb"),
        value: summary?.user_count ?? 0,
      },
      {
        key: "kbs",
        label: t("tenantResources.personalCapacity.personalKbTotal"),
        value: summary?.kb_count ?? 0,
      },
      {
        key: "usage",
        label: t("tenantResources.personalCapacity.personalKbUsage"),
        value: summary?.total_readable || formatBytes(summary?.total_bytes),
      },
      {
        key: "es-usage",
        label: t("tenantResources.personalCapacity.esPhysicalSize"),
        value: summary?.total_es_physical_readable || "0 B",
      },
      {
        key: "allocated",
        label: t("tenantResources.personalCapacity.allocatedQuota"),
        value:
          summary?.allocated_quota_readable ||
          formatBytes(summary?.allocated_quota_bytes),
      },
      {
        key: "default",
        label: t("tenantResources.personalCapacity.defaultQuota"),
        value: defaultQuotaText,
        action: canManage ? (
          <Button
            type="link"
            size="small"
            className="h-auto p-0"
            onClick={() => {
              setQuotaModalMode("default");
              setQuotaTarget(null);
              setQuotaModalOpen(true);
            }}
          >
            {t("tenantResources.personalCapacity.modify")}
          </Button>
        ) : undefined,
      },
    ];
    return cards;
  }, [summary, defaultQuotaText, canManage, t]);

  const columns: ColumnsType<PersonalCapacityUser> = [
    {
      title: t("tenantResources.personalCapacity.user"),
      dataIndex: "user_name",
      key: "user_name",
      width: 200,
      filteredValue: search ? [search] : null,
      filterIcon: (filtered) => (
        <Search
          size={14}
          className={filtered ? "text-blue-600" : "text-gray-500"}
        />
      ),
      filterDropdown: ({ close, visible }) => (
        <CompactUserSearchFilter
          value={search}
          onChange={setSearch}
          placeholder={t("tenantResources.personalCapacity.searchPlaceholder")}
          close={close}
          visible={visible}
        />
      ),
      render: (_: unknown, record: PersonalCapacityUser) => (
        <div className="min-w-0">
          <Tooltip title={record.user_name || record.user_id}>
            <div className="font-medium truncate max-w-[160px]">
              {record.user_name || record.user_id}
            </div>
          </Tooltip>
          {record.email && (
            <div className="text-xs text-gray-400 truncate max-w-[180px]">
              {record.email}
            </div>
          )}
        </div>
      ),
    },
    {
      title: t("tenantResources.personalCapacity.kbCount"),
      dataIndex: "kb_count",
      key: "kb_count",
      width: 120,
      align: "right",
      sorter: true,
      sortOrder: sortOrderFor("kb_count"),
      render: (value: number) => value ?? 0,
    },
    {
      title: t("tenantResources.personalCapacity.used"),
      dataIndex: "total_bytes",
      key: "total_bytes",
      width: 150,
      sorter: true,
      sortOrder: sortOrderFor("total_bytes"),
      render: (_: unknown, record: PersonalCapacityUser) =>
        record.total_readable || formatBytes(record.total_bytes),
    },
    {
      title: t("tenantResources.personalCapacity.esPhysicalSize"),
      dataIndex: "es_physical_bytes",
      key: "es_physical_bytes",
      width: 150,
      render: (_: unknown, record: PersonalCapacityUser) =>
        record.es_physical_readable || formatBytes(record.es_physical_bytes),
    },
    {
      title: t("tenantResources.personalCapacity.quota"),
      dataIndex: "quota_limit_bytes",
      key: "quota_limit_bytes",
      width: 180,
      sorter: true,
      sortOrder: sortOrderFor("quota_limit_bytes"),
      render: (_: unknown, record: PersonalCapacityUser) => {
        if (
          record.quota_source === "unlimited" ||
          record.effective_quota_bytes == null
        ) {
          return <span>{t("quota.unlimited")}</span>;
        }
        return (
          <Space size={4}>
            <span>
              {record.quota_limit_readable ||
                formatBytes(record.quota_limit_bytes)}
            </span>
            {record.quota_source === "default" && (
              <Tag color="blue">
                {t("tenantResources.personalCapacity.defaultTag")}
              </Tag>
            )}
          </Space>
        );
      },
    },
    {
      title: t("tenantResources.personalCapacity.usageRate"),
      dataIndex: "usage_rate",
      key: "usage_rate",
      width: 160,
      sorter: true,
      sortOrder: sortOrderFor("usage_rate"),
      render: (_: unknown, record: PersonalCapacityUser) => {
        const quotaBytes = record.effective_quota_bytes;
        if (!quotaBytes || quotaBytes <= 0) {
          return <span>{t("quota.unlimited")}</span>;
        }
        const pct =
          record.usage_rate ??
          Math.round((record.total_bytes / quotaBytes) * 100);
        const red = pct > 90;
        return (
          <div className="flex items-center gap-2">
            <Progress
              percent={Math.min(pct, 100)}
              size="small"
              strokeColor={red ? "#ff4d4f" : "#1677ff"}
              format={() => ""}
              style={{ margin: 0, width: 90 }}
            />
            <span
              className={`text-xs ${
                red ? "text-red-500 font-medium" : "text-gray-600"
              }`}
            >
              {pct}%
            </span>
          </div>
        );
      },
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 130,
      fixed: "right",
      render: (_: unknown, record: PersonalCapacityUser) =>
        canManage ? (
          <Button
            type="link"
            size="small"
            icon={<Settings2 className="h-4 w-4" />}
            onClick={() => {
              setQuotaModalMode("user");
              setQuotaTarget(record);
              setQuotaModalOpen(true);
            }}
          >
            {t("tenantResources.personalCapacity.setQuota")}
          </Button>
        ) : null,
    },
  ];

  const kbColumns: ColumnsType<PersonalKnowledgeBaseItem> = [
    {
      title: t("common.name"),
      dataIndex: "name",
      key: "name",
      width: 240,
      render: (value: string, record: PersonalKnowledgeBaseItem) => (
        <Button
          type="link"
          size="small"
          className="h-auto p-0"
          onClick={() => setKbDetailTarget(record)}
        >
          {value || "-"}
        </Button>
      ),
    },
    {
      title: t("tenantResources.personalCapacity.source"),
      dataIndex: "source",
      key: "source",
      width: 110,
      render: (value: string | null) => (
        <Tag color="default">{value || t("common.unknown")}</Tag>
      ),
    },
    {
      title: t("tenantResources.personalCapacity.documents"),
      dataIndex: "doc_count",
      key: "doc_count",
      width: 90,
      align: "right",
      render: (value: number) => value ?? 0,
    },
    {
      title: t("tenantResources.personalCapacity.chunks"),
      dataIndex: "chunk_count",
      key: "chunk_count",
      width: 90,
      align: "right",
      render: (value: number) => value ?? 0,
    },
    {
      title: t("tenantResources.personalCapacity.sourceSize"),
      dataIndex: "source_size",
      key: "source_size",
      width: 130,
      render: (value: string | null, record: PersonalKnowledgeBaseItem) =>
        value ||
        (record.source_size_bytes != null
          ? formatBytes(record.source_size_bytes)
          : "-"),
    },
    {
      title: t("tenantResources.personalCapacity.esPhysicalSize"),
      dataIndex: "es_physical_size",
      key: "es_physical_size",
      width: 130,
      render: (value: string | null, record: PersonalKnowledgeBaseItem) =>
        value ||
        record.store_size ||
        formatBytes(record.es_physical_size_bytes ?? record.store_size_bytes),
    },
    {
      title: t("tenantResources.personalCapacity.kbQuota"),
      dataIndex: "quota_limit_bytes",
      key: "quota_limit_bytes",
      width: 150,
      render: (value: number | null, record: PersonalKnowledgeBaseItem) =>
        value == null
          ? t("quota.unlimited")
          : record.quota_limit_readable || formatBytes(value),
    },
    {
      title: t("tenantResources.personalCapacity.lastUpdated"),
      dataIndex: "updated_at",
      key: "updated_at",
      width: 160,
      render: (value: string | null) => formatDateTime(value),
    },
  ];

  const expandedRowRender = (record: PersonalCapacityUser) => {
    const kbs = detailMap[record.user_id];
    const expandedLoading = detailLoading[record.user_id];
    if (expandedLoading || !kbs) {
      return (
        <div className="py-4 text-center">
          <Spin size="small" />
        </div>
      );
    }
    if (kbs.length === 0) {
      return (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("tenantResources.personalCapacity.noKbs")}
        />
      );
    }
    return (
      <Table
        columns={kbColumns}
        dataSource={kbs}
        rowKey="kb_id"
        size="small"
        rowHoverable={false}
        pagination={{ pageSize: 10, showSizeChanger: false }}
      />
    );
  };

  if (!canRead) {
    return (
      <div className="flex items-center justify-center h-full">
        <Alert
          type="warning"
          showIcon
          title={t("tenantResources.personalCapacity.noPermission")}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden gap-3">
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 px-1">
        {statCards.map((card) => (
          <div
            key={card.key}
            className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md p-4 min-w-0"
          >
            <div className="text-xs text-gray-500 mb-1 truncate">
              {card.label}
            </div>
            <div className="flex items-center justify-between gap-2">
              <Spin
                spinning={summaryLoading || defaultQuotaLoading}
                size="small"
              >
                <span className="text-xl font-semibold truncate">
                  {card.value}
                </span>
              </Spin>
              {card.action}
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2 px-1">
        <div className="flex flex-wrap items-center gap-2">
          {isSuperAdmin && (
            <Select
              value={viewTenantId ?? undefined}
              placeholder={t("tenantResources.personalCapacity.selectTenant")}
              loading={tenantsLoading}
              style={{ minWidth: 200 }}
              options={(tenantData?.data || []).map((tenant) => ({
                value: tenant.tenant_id,
                label: tenant.tenant_name,
              }))}
              onChange={(value: string) => setViewTenantId(value)}
            />
          )}
          {canManage && (
            <Button
              type="primary"
              icon={<Settings2 className="h-4 w-4" />}
              onClick={() => {
                setQuotaModalMode("default");
                setQuotaTarget(null);
                setQuotaModalOpen(true);
              }}
            >
              {t("tenantResources.personalCapacity.setDefaultQuota")}
            </Button>
          )}
        </div>
      </div>

      {!viewTenantId ? (
        <div className="flex-1 flex items-center justify-center">
          <Empty
            description={t("tenantResources.personalCapacity.selectTenant")}
          />
        </div>
      ) : (
        <ConfigProvider theme={PERSONAL_CAPACITY_TABLE_THEME}>
          <Table
            columns={columns}
            dataSource={users}
            rowKey="user_id"
            loading={loading}
            onChange={handleTableChange}
            rowHoverable={false}
            showSorterTooltip={false}
            locale={{
              emptyText: t("tenantResources.personalCapacity.noUsers"),
            }}
            expandable={{
              expandedRowRender,
              expandedRowKeys: expandedKeys,
              onExpand: handleExpand,
            }}
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              showTotal: (value) =>
                t("tenantResources.personalCapacity.total", {
                  total: value,
                }),
            }}
            className="flex-1 min-h-0"
            scroll={{ y: "calc(100vh - 780px)" }}
          />
        </ConfigProvider>
      )}

      <PersonalQuotaModal
        open={quotaModalOpen}
        mode={quotaModalMode}
        title={
          quotaModalMode === "user"
            ? t("tenantResources.personalCapacity.quotaModalTitle")
            : t("tenantResources.personalCapacity.defaultQuotaModalTitle")
        }
        currentBytes={
          quotaModalMode === "user"
            ? (quotaTarget?.effective_quota_bytes ?? null)
            : (defaultQuota?.quota_limit_bytes ?? null)
        }
        currentUsageBytes={
          quotaModalMode === "user" ? (quotaTarget?.total_bytes ?? null) : null
        }
        currentUsageReadable={
          quotaModalMode === "user"
            ? (quotaTarget?.total_readable ?? null)
            : null
        }
        onCancel={() => setQuotaModalOpen(false)}
        onSubmit={handleQuotaSubmit}
      />

      <KbDetailModal
        kb={kbDetailTarget}
        onClose={() => setKbDetailTarget(null)}
      />
    </div>
  );
}
