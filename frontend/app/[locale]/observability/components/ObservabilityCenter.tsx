// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { DatePicker, Popover, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Filter, RefreshCw, Trash2 } from "lucide-react";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import { useTranslation } from "react-i18next";
import type { User } from "@/types/auth";
import type {
  DirectoryField,
  DirectoryOption,
  RecordsRequest,
  TrajectoryFilters,
  TrajectoryRecord,
} from "@/types/trajectory";
import { StandardButton } from "@/components/common/StandardButton";
import { StandardInput } from "@/components/common/StandardInput";
import { StandardTable } from "@/components/common/StandardTable";
import { StandardPaginator } from "@/components/common/StandardPaginator";
import { useTrajectoryRecords } from "@/hooks/trajectory/useTrajectoryRecords";
import {
  formatMetric,
  formatTraceTime,
  recordKey,
  resetFilters,
} from "@/lib/trajectory";
import { AgentVersion } from "./AgentVersion";
import { DirectoryFilter } from "./DirectoryFilter";
import { TrajectorySummary } from "./TrajectorySummary";
import { TrajectoryError } from "./TrajectoryFeedback";
import { TrajectoryDrawer } from "./TrajectoryDrawer";
import { CleanupDialog } from "./CleanupDialog";

dayjs.extend(utc);
dayjs.extend(timezone);

export function ObservabilityCenter({ user }: { user: User }) {
  const { t } = useTranslation();
  const initial = (): TrajectoryFilters =>
    user.role === "ADMIN" ? { tenant_id: user.tenantId } : {};
  const [filters, setFilters] = useState<TrajectoryFilters>(initial);
  const [search, setSearch] = useState("");
  const [paging, setPaging] = useState({ page: 1, page_size: 10 });
  const [sorting, setSorting] = useState<
    Pick<RecordsRequest, "sort_by" | "sort_order">
  >({ sort_by: "started_at", sort_order: "desc" });
  const [selected, setSelected] = useState<TrajectoryRecord | null>(null);
  const [cleaning, setCleaning] = useState(false);
  const scope = JSON.stringify([user.id, user.tenantId, user.role]);
  const records = useTrajectoryRecords(scope, {
    view: "conversation",
    ...filters,
    ...paging,
    ...sorting,
  });
  const change = (next: TrajectoryFilters) => {
    setFilters(next);
    setPaging((value) => ({ ...value, page: 1 }));
    setSelected(null);
  };
  const directoryChange = (field: DirectoryField, option?: DirectoryOption) => {
    let next = resetFilters(filters, field, option?.id);
    // Cross-tenant IDs need the tenant returned by the authorized facet.
    if (option && field !== "tenant_id" && !filters.tenant_id)
      next = { ...next, tenant_id: option.tenant_id };
    setSearch("");
    change(next);
    if (field === "tenant_id") setCleaning(false);
  };
  const clear = () => {
    setSearch("");
    change(initial());
    setCleaning(false);
  };
  const refresh = () => {
    setSelected(null);
    setPaging((value) => ({ ...value, page: 1 }));
    records.refresh();
  };
  const tenant = filters.tenant_id;
  const canCleanup = !!tenant && tenant === user.tenantId;
  const sortOrder = (field: RecordsRequest["sort_by"]) =>
    sorting.sort_by === field
      ? sorting.sort_order === "asc"
        ? ("ascend" as const)
        : ("descend" as const)
      : null;
  const modelHeader = (
    <div className="flex items-center gap-1">
      {t("trajectory.models")}
      <Popover
        trigger="click"
        content={
          <DirectoryFilter
            key={tenant || "all"}
            facet="models"
            filters={{ tenant_id: tenant }}
            value={filters.model}
            onChange={(option) => change({ ...filters, model: option?.id })}
          />
        }
      >
        <button
          aria-label={t("trajectory.filterModels")}
          className={filters.model ? "text-blue-600" : "text-gray-400"}
        >
          <Filter size={13} />
        </button>
      </Popover>
    </div>
  );
  const columns: ColumnsType<TrajectoryRecord> = [
    {
      title: t("trajectory.agents"),
      dataIndex: "root_agent_name",
      width: 180,
      render: (_, row) => (
        <button className="trajectory-link" onClick={() => setSelected(row)}>
          {row.root_agent_name ||
            row.root_agent_id ||
            t("trajectory.unknownAgent")}
        </button>
      ),
    },
    {
      title: t("trajectory.agentVersion"),
      key: "root_agent_version_no",
      width: 100,
      render: (_, row) => (
        <AgentVersion
          version={row.root_agent_version_no}
          name={row.root_agent_version_name}
        />
      ),
    },
    {
      title: t("trajectory.conversations"),
      width: 220,
      render: (_, row) => (
        <div className="py-2">
          <div className="truncate" title={row.conversation_title || ""}>
            {row.conversation_title || "—"}
          </div>
          <small className="text-gray-500">{row.conversation_id}</small>
        </div>
      ),
    },
    {
      title: t("trajectory.rounds"),
      key: "round_count",
      width: 80,
      render: (_, row) => formatMetric(row.round_count, 0),
    },
    {
      title: t("trajectory.users"),
      width: 170,
      render: (_, row) => (
        <div className="py-2">
          <div>{row.user_name || row.user_id}</div>
          <small className="text-gray-500">
            {row.tenant_name || row.tenant_id}
          </small>
        </div>
      ),
    },
    {
      title: modelHeader,
      key: "models",
      width: 180,
      render: (_, row) => row.models.join(", ") || "—",
    },
    {
      title: t("trajectory.status"),
      key: "status",
      width: 130,
      filteredValue: filters.status ? [filters.status] : null,
      filters: [
        { text: t("trajectory.success"), value: "success" },
        { text: t("trajectory.error"), value: "error" },
        {
          text: t("trajectory.availability.not_captured"),
          value: "not_captured",
        },
        { text: t("trajectory.availability.expired"), value: "expired" },
      ],
      filterMultiple: false,
      render: (_, row) => (
        <div>
          <Tag
            color={
              row.status === "success"
                ? "success"
                : row.status === "error"
                  ? "error"
                  : "default"
            }
          >
            {t(`trajectory.availability.${row.status || row.availability}`, {
              defaultValue: row.availability,
            })}
          </Tag>
          {row.coverage.complete !== true && row.trajectory_id && (
            <small className="block text-amber-700">
              {t("trajectory.partial")}
            </small>
          )}
        </div>
      ),
    },
    {
      title: (
        <div className="flex items-center gap-1">
          {t("trajectory.started")}
          <Popover
            trigger="click"
            content={
              <div className="flex flex-col gap-3">
                <span>{t("trajectory.shanghai")}</span>
                <DatePicker.RangePicker
                  showTime
                  allowEmpty={[true, true]}
                  value={[
                    filters.started_from
                      ? dayjs(filters.started_from).tz("Asia/Shanghai")
                      : null,
                    filters.started_to
                      ? dayjs(filters.started_to).tz("Asia/Shanghai")
                      : null,
                  ]}
                  onChange={(values) =>
                    change({
                      ...filters,
                      started_from: values?.[0]
                        ? dayjs
                            .tz(
                              values[0].format("YYYY-MM-DD HH:mm:ss"),
                              "Asia/Shanghai"
                            )
                            .toISOString()
                        : undefined,
                      started_to: values?.[1]
                        ? dayjs
                            .tz(
                              values[1].format("YYYY-MM-DD HH:mm:ss"),
                              "Asia/Shanghai"
                            )
                            .toISOString()
                        : undefined,
                    })
                  }
                />
                <StandardButton
                  onClick={() =>
                    change({
                      ...filters,
                      started_from: undefined,
                      started_to: undefined,
                    })
                  }
                >
                  {t("trajectory.clear")}
                </StandardButton>
              </div>
            }
          >
            <button
              aria-label={t("trajectory.filterTime")}
              className={
                filters.started_from || filters.started_to
                  ? "text-blue-600"
                  : "text-gray-400"
              }
            >
              <Filter size={13} />
            </button>
          </Popover>
        </div>
      ),
      key: "started_at",
      width: 190,
      sorter: true,
      sortOrder: sortOrder("started_at"),
      render: (_, row) => formatTraceTime(row.started_at),
    },
    {
      title: t("trajectory.finished"),
      dataIndex: "finished_at",
      width: 180,
      render: formatTraceTime,
    },
    {
      title: t("trajectory.duration"),
      key: "duration_ms",
      width: 110,
      sorter: true,
      sortOrder: sortOrder("duration_ms"),
      render: (_, row) =>
        `${formatMetric(row.duration_ms == null ? null : row.duration_ms / 1000)} s`,
    },
    {
      title: "Token",
      key: "total_tokens",
      width: 120,
      sorter: true,
      sortOrder: sortOrder("total_tokens"),
      render: (_, row) => (
        <>
          {formatMetric(row.usage?.total, 0)}
          {row.usage && !row.usage.complete && (
            <small className="block text-amber-700">
              {t("trajectory.partial")}
            </small>
          )}
        </>
      ),
    },
  ];
  return (
    <main className="trajectory-center">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{t("trajectory.title")}</h1>
          <p className="mt-1 text-xs text-gray-500">
            {t("trajectory.subtitle")}
          </p>
        </div>
        <Tooltip title={canCleanup ? "" : t("trajectory.cleanupContext")}>
          <span>
            <StandardButton
              icon={<Trash2 size={14} />}
              disabled={!canCleanup}
              onClick={() => setCleaning(true)}
            >
              {t("trajectory.cleanup")}
            </StandardButton>
          </span>
        </Tooltip>
      </header>
      <section className="trajectory-panel flex flex-wrap items-center gap-3">
        {user.role === "SU" ? (
          <DirectoryFilter
            facet="tenants"
            filters={{}}
            value={tenant}
            onChange={(option) => directoryChange("tenant_id", option)}
          />
        ) : (
          <Tag>
            {t("trajectory.currentTenant")}: {user.tenantId}
          </Tag>
        )}
        <DirectoryFilter
          key={`users:${tenant || "all"}`}
          facet="users"
          filters={{ tenant_id: tenant }}
          value={filters.target_user_id}
          onChange={(option) => directoryChange("target_user_id", option)}
        />
        <DirectoryFilter
          key={`agents:${tenant}:${filters.target_user_id}`}
          facet="agents"
          filters={{
            tenant_id: tenant,
            target_user_id: filters.target_user_id,
          }}
          value={filters.agent_id}
          onChange={(option) => directoryChange("agent_id", option)}
        />
        <DirectoryFilter
          key={`conversations:${tenant}:${filters.target_user_id}:${filters.agent_id}`}
          facet="conversations"
          filters={{
            tenant_id: tenant,
            target_user_id: filters.target_user_id,
            agent_id: filters.agent_id,
          }}
          value={filters.conversation_id}
          onChange={(option) => directoryChange("conversation_id", option)}
        />
        <StandardInput
          className="!w-56"
          aria-label={t("trajectory.idSearch")}
          placeholder={t("trajectory.idSearch")}
          maxLength={200}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          onPressEnter={() => {
            change({ ...filters, id_query: search.trim() });
            records.refresh();
          }}
        />
        <StandardButton
          variant="primary"
          icon={<RefreshCw size={14} />}
          loading={records.isFetching}
          onClick={() => {
            change({ ...filters, id_query: search.trim() });
            records.refresh();
          }}
        >
          {t("trajectory.query")}
        </StandardButton>
        <StandardButton onClick={clear}>{t("trajectory.clear")}</StandardButton>
      </section>
      <div className="flex flex-wrap gap-2">
        {Object.entries(filters)
          .filter(
            ([key, value]) =>
              !!value && !(user.role === "ADMIN" && key === "tenant_id")
          )
          .map(([key, value]) => (
            <Tag
              key={key}
              closable
              onClose={() => {
                if (
                  [
                    "tenant_id",
                    "target_user_id",
                    "agent_id",
                    "conversation_id",
                  ].includes(key)
                )
                  directoryChange(key as DirectoryField);
                else {
                  change({ ...filters, [key]: undefined });
                  if (key === "id_query") setSearch("");
                }
              }}
            >
              {t(`trajectory.filterLabels.${key}`)}: {value}
            </Tag>
          ))}
      </div>
      <TrajectorySummary summary={records.data?.summary} />
      {records.isError && (
        <TrajectoryError error={records.error} retry={refresh} />
      )}
      <section className="trajectory-panel min-h-0 flex-1">
        <div className="mb-3 flex justify-between text-xs text-gray-500">
          <span>
            {t("trajectory.total", { count: records.data?.total ?? 0 })}
          </span>
          <span>
            {records.data &&
              `${t("trajectory.asOf")}: ${formatTraceTime(records.data.as_of)}`}
          </span>
        </div>
        <StandardTable<TrajectoryRecord>
          className="[&_.ant-table-tbody>tr.ant-table-measure-row>td]:!h-0 [&_.ant-table-tbody>tr.ant-table-measure-row>td]:!border-0"
          rowKey={recordKey}
          columns={columns}
          dataSource={records.data?.items ?? []}
          loading={records.isFetching}
          pagination={false}
          scroll={{ x: 1550 }}
          locale={{
            emptyText: records.isError
              ? t("trajectory.queryFailed")
              : t("trajectory.empty"),
          }}
          onRow={(row) => ({
            onClick: () => setSelected(row),
            className: "cursor-pointer",
            tabIndex: 0,
            onKeyDown: (event) => {
              if (event.key === "Enter" && event.target === event.currentTarget)
                setSelected(row);
            },
          })}
          onChange={(_pagination, tableFilters, sorter, extra) => {
            if (extra.action === "filter")
              change({
                ...filters,
                status: tableFilters.status?.[0] as TrajectoryFilters["status"],
              });
            if (extra.action === "sort" && !Array.isArray(sorter)) {
              setSorting({
                sort_by: sorter.order
                  ? (sorter.columnKey as RecordsRequest["sort_by"])
                  : "started_at",
                sort_order: sorter.order === "ascend" ? "asc" : "desc",
              });
              setPaging((previous) => ({ ...previous, page: 1 }));
            }
          }}
        />
        <div className="mt-4 flex justify-end">
          <StandardPaginator
            current={paging.page}
            pageSize={paging.page_size}
            total={records.data?.total ?? 0}
            showSizeChanger
            pageSizeOptions={[5, 10, 20]}
            onChange={(page, page_size) =>
              setPaging({
                page: page_size === paging.page_size ? page : 1,
                page_size,
              })
            }
          />
        </div>
      </section>
      {selected && (
        <TrajectoryDrawer
          key={recordKey(selected)}
          row={selected}
          queryId={records.data?.query_id}
          onReset={refresh}
          onClose={() => setSelected(null)}
        />
      )}
      {cleaning && canCleanup && (
        <CleanupDialog
          key={tenant}
          tenant={tenant!}
          onClose={() => setCleaning(false)}
          onComplete={refresh}
        />
      )}
    </main>
  );
}
