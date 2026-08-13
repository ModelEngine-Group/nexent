"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
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
import quotaService from "@/services/quotaService";
import type {
  PersonalCapacityUser,
  PersonalDefaultQuota,
  PersonalKnowledgeBaseItem,
  PersonalQuotaPayload,
} from "@/types/quota";

const GB = 1024 * 1024 * 1024;
const MB = 1024 * 1024;
const DEFAULT_PAGE_SIZE = 10;
const DETAIL_PAGE_SIZE = 100;
const SEARCH_MAX_PAGES = 20;

type SortField = "user_name" | "kb_count" | "total_bytes" | "quota_limit_bytes";
type SortOrder = "asc" | "desc";

const SORT_FIELDS: SortField[] = [
  "user_name",
  "kb_count",
  "total_bytes",
  "quota_limit_bytes",
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

function compareUsers(
  a: PersonalCapacityUser,
  b: PersonalCapacityUser,
  field: SortField,
  order: SortOrder
): number {
  let result = 0;
  switch (field) {
    case "user_name":
      result = (a.user_name || "").localeCompare(b.user_name || "");
      break;
    case "kb_count":
      result = (a.kb_count ?? 0) - (b.kb_count ?? 0);
      break;
    case "total_bytes":
      result = (a.total_bytes ?? 0) - (b.total_bytes ?? 0);
      break;
    case "quota_limit_bytes":
      result = (a.quota_limit_bytes ?? -1) - (b.quota_limit_bytes ?? -1);
      break;
  }
  return order === "asc" ? result : -result;
}

interface PersonalQuotaModalProps {
  open: boolean;
  title: string;
  currentBytes: number | null;
  currentUsageReadable?: string | null;
  onCancel: () => void;
  onSubmit: (payload: PersonalQuotaPayload) => Promise<void>;
}

function PersonalQuotaModal({
  open,
  title,
  currentBytes,
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

  return (
    <Modal
      title={title}
      open={open}
      onCancel={onCancel}
      onOk={handleSave}
      confirmLoading={saving}
      okText={t("common.save")}
      cancelText={t("common.cancel")}
      width={480}
      destroyOnClose
    >
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        {currentUsageReadable && (
          <div className="text-sm text-gray-500">
            {t("tenantResources.personalCapacity.currentUsage")}:{" "}
            {currentUsageReadable}
          </div>
        )}
        <div className="flex items-center gap-2">
          <Switch checked={unlimited} onChange={setUnlimited} />
          <span className="text-sm">
            {t("tenantResources.personalCapacity.unlimitedQuota")}
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
        {currentBytes != null && (
          <div className="text-sm text-gray-500">
            {t("tenantResources.personalCapacity.currentQuota")}:{" "}
            {formatBytes(currentBytes)}
          </div>
        )}
      </Space>
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
  });

  const [viewTenantId, setViewTenantId] = useState<string | null>(tenantId);
  useEffect(() => {
    setViewTenantId(tenantId);
  }, [tenantId]);

  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 400);
    return () => clearTimeout(timer);
  }, [search]);
  const searchMode = debouncedSearch.trim().length > 0;

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [sortBy, setSortBy] = useState<SortField>("total_bytes");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");
  const [users, setUsers] = useState<PersonalCapacityUser[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

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

  const [quotaModalOpen, setQuotaModalOpen] = useState(false);
  const [quotaModalMode, setQuotaModalMode] = useState<"user" | "default">(
    "user"
  );
  const [quotaTarget, setQuotaTarget] = useState<PersonalCapacityUser | null>(
    null
  );

  useEffect(() => {
    setPage(1);
  }, [viewTenantId, debouncedSearch]);

  useEffect(() => {
    setDetailMap({});
    setDetailLoading({});
    setExpandedKeys([]);
  }, [viewTenantId]);

  useEffect(() => {
    if (!searchMode || !viewTenantId) return;
    let cancelled = false;
    setLoading(true);
    const keyword = debouncedSearch.trim().toLowerCase();
    (async () => {
      try {
        const all: PersonalCapacityUser[] = [];
        let currentPage = 1;
        let totalPages = 1;
        let pageTotal = 0;
        while (currentPage <= totalPages && currentPage <= SEARCH_MAX_PAGES) {
          const data = await quotaService.listPersonalCapacityUsers({
            tenantId: viewTenantId,
            page: currentPage,
            page_size: 100,
            sort_by: "user_name",
            sort_order: "asc",
          });
          all.push(...data.items);
          totalPages = data.total_pages;
          pageTotal = data.total;
          currentPage += 1;
          if (all.length >= pageTotal) break;
        }
        if (cancelled) return;
        const filtered = all.filter(
          (userItem) =>
            (userItem.user_name || "").toLowerCase().includes(keyword) ||
            (userItem.email || "").toLowerCase().includes(keyword)
        );
        const sorted = [...filtered].sort((a, b) =>
          compareUsers(a, b, sortBy, sortOrder)
        );
        setUsers(sorted);
        setTotal(sorted.length);
      } catch (err: unknown) {
        if (!cancelled) {
          message.error(
            getErrorMessage(err) ||
              t("tenantResources.personalCapacity.loadFailed")
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    viewTenantId,
    searchMode,
    debouncedSearch,
    sortBy,
    sortOrder,
    reloadKey,
    t,
  ]);

  useEffect(() => {
    if (searchMode || !viewTenantId) return;
    let cancelled = false;
    setLoading(true);
    quotaService
      .listPersonalCapacityUsers({
        tenantId: viewTenantId,
        page,
        page_size: pageSize,
        sort_by: sortBy,
        sort_order: sortOrder,
      })
      .then((data) => {
        if (cancelled) return;
        setUsers(data.items);
        setTotal(data.total);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          message.error(
            getErrorMessage(err) ||
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
  }, [
    viewTenantId,
    searchMode,
    page,
    pageSize,
    sortBy,
    sortOrder,
    reloadKey,
    t,
  ]);

  useEffect(() => {
    if (!viewTenantId) {
      setDefaultQuota(null);
      return;
    }
    let cancelled = false;
    setDefaultQuotaLoading(true);
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
            getErrorMessage(err) ||
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
          getErrorMessage(err) ||
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

  const displayUsers = useMemo(() => {
    if (!searchMode) return users;
    const start = (page - 1) * pageSize;
    return users.slice(start, start + pageSize);
  }, [users, searchMode, page, pageSize]);
  const displayTotal = searchMode ? users.length : total;

  const sortOrderFor = (field: SortField): "ascend" | "descend" | null =>
    sortBy === field ? (sortOrder === "asc" ? "ascend" : "descend") : null;

  const columns: ColumnsType<PersonalCapacityUser> = [
    {
      title: t("tenantResources.personalCapacity.user"),
      key: "user_name",
      width: 220,
      sorter: true,
      sortOrder: sortOrderFor("user_name"),
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
      key: "total_bytes",
      width: 180,
      sorter: true,
      sortOrder: sortOrderFor("total_bytes"),
      render: (_: unknown, record: PersonalCapacityUser) => {
        const usagePct =
          record.effective_quota_bytes && record.effective_quota_bytes > 0
            ? Math.min(
                100,
                Math.round(
                  (record.total_bytes / record.effective_quota_bytes) * 100
                )
              )
            : null;
        return (
          <div className="min-w-[120px]">
            <div>
              {record.total_readable || formatBytes(record.total_bytes)}
            </div>
            {usagePct != null && (
              <Progress
                percent={usagePct}
                size="small"
                strokeColor={
                  usagePct >= 100
                    ? "#ff4d4f"
                    : usagePct >= 80
                      ? "#faad14"
                      : "#52c41a"
                }
                format={() => ""}
                style={{ marginBottom: 0, width: 120 }}
              />
            )}
          </div>
        );
      },
    },
    {
      title: t("tenantResources.personalCapacity.quota"),
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
      render: (value: string) => value || "-",
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
      title: t("tenantResources.personalCapacity.storeSize"),
      dataIndex: "store_size",
      key: "store_size",
      width: 130,
      render: (value: string | null, record: PersonalKnowledgeBaseItem) =>
        value || formatBytes(record.store_size_bytes),
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
      title: t("common.updated"),
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
          message={t("tenantResources.personalCapacity.noPermission")}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-600">
            {t("tenantResources.personalCapacity.defaultQuota")}:
          </span>
          <Spin spinning={defaultQuotaLoading} size="small">
            <span className="text-sm font-medium">
              {defaultQuota?.unlimited ||
              defaultQuota?.quota_limit_bytes == null
                ? t("quota.unlimited")
                : defaultQuota.quota_limit_readable ||
                  formatBytes(defaultQuota.quota_limit_bytes)}
            </span>
          </Spin>
        </div>
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
          <Input
            prefix={<Search className="h-4 w-4 text-gray-400" />}
            placeholder={t(
              "tenantResources.personalCapacity.searchPlaceholder"
            )}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            allowClear
            style={{ width: 220 }}
          />
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
        <Table
          columns={columns}
          dataSource={displayUsers}
          rowKey="user_id"
          loading={loading}
          onChange={handleTableChange}
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
            total: displayTotal,
            showSizeChanger: true,
            showTotal: (value) =>
              t("tenantResources.personalCapacity.total", {
                total: value,
              }),
          }}
          className="flex-1 min-h-0"
          scroll={{ y: "calc(100vh - 560px)" }}
        />
      )}

      <PersonalQuotaModal
        open={quotaModalOpen}
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
        currentUsageReadable={
          quotaModalMode === "user"
            ? (quotaTarget?.total_readable ?? null)
            : null
        }
        onCancel={() => setQuotaModalOpen(false)}
        onSubmit={handleQuotaSubmit}
      />
    </div>
  );
}
