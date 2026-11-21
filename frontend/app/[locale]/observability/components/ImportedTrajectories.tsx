// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Button, Empty, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeft, RefreshCw, Trash2, Upload } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import type { User } from "@/types/auth";
import type {
  SavedImportsSort,
  SavedTrajectoryRecord,
} from "@/types/trajectory";
import { AUTH_EVENTS } from "@/const/auth";
import { effectiveRoles } from "@/lib/roles";
import { formatMetric, formatTraceTime } from "@/lib/trajectory";
import { trajectoryService } from "@/services/trajectoryService";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { useTrajectoryArchive } from "@/hooks/trajectory/useTrajectoryArchive";
import { TrajectoryError } from "./TrajectoryFeedback";
import { TrajectoryDrawer } from "./TrajectoryDrawer";

export function ImportedTrajectories({ user }: { user: User }) {
  const { t, i18n } = useTranslation();
  const scope = JSON.stringify([user.id, user.tenantId, effectiveRoles(user)]);
  const [paging, setPaging] = useState({ page: 1, page_size: 20 });
  const [sorting, setSorting] = useState<SavedImportsSort>({
    sort_by: "imported_at",
    sort_order: "desc",
  });
  const [selected, setSelected] = useState<string[]>([]);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const deletion = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const [opening, setOpening] = useState<string | null>(null);
  const client = useQueryClient();
  const queryKey = ["trajectory-imports", scope];
  const records = useQuery({
    queryKey: [...queryKey, paging, sorting],
    queryFn: ({ signal }) =>
      trajectoryService.savedImports(
        paging.page,
        paging.page_size,
        signal,
        sorting
      ),
    retry: false,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });
  const archive = useTrajectoryArchive(scope, true);
  const fileInput = useRef<HTMLInputElement>(null);
  const { confirm } = useConfirmModal();
  useEffect(() => {
    mounted.current = true;
    const stop = () => deletion.current?.abort();
    window.addEventListener("pagehide", stop);
    window.addEventListener(AUTH_EVENTS.LOGOUT, stop);
    window.addEventListener(AUTH_EVENTS.SESSION_EXPIRED, stop);
    return () => {
      mounted.current = false;
      stop();
      window.removeEventListener("pagehide", stop);
      window.removeEventListener(AUTH_EVENTS.LOGOUT, stop);
      window.removeEventListener(AUTH_EVENTS.SESSION_EXPIRED, stop);
    };
  }, [scope]);
  const remove = useMutation({
    mutationFn: async (ids: string[]) => {
      const controller = new AbortController();
      deletion.current = controller;
      const deleted: string[] = [];
      const failed: { id: string; error: unknown }[] = [];
      setProgress({ done: 0, total: ids.length });
      try {
        // Each request takes the same owner's nonblocking file lock.
        for (const id of ids) {
          if (controller.signal.aborted) break;
          try {
            await trajectoryService.deleteImport(id, controller.signal);
            deleted.push(id);
          } catch (error) {
            if (controller.signal.aborted) break;
            failed.push({ id, error });
          }
          if (mounted.current)
            setProgress({
              done: deleted.length + failed.length,
              total: ids.length,
            });
        }
        return { deleted, failed };
      } finally {
        if (deletion.current === controller) deletion.current = null;
      }
    },
    onSuccess: ({ deleted }) => {
      if (!mounted.current) return;
      setSelected((ids) => ids.filter((id) => !deleted.includes(id)));
      if (deleted.length) {
        archive.clear();
        setOpening(null);
        const remaining = Math.max(
          0,
          (records.data?.total ?? 0) - deleted.length
        );
        setPaging((value) => ({
          ...value,
          page: Math.min(
            value.page,
            Math.max(1, Math.ceil(remaining / value.page_size))
          ),
        }));
      }
    },
    onSettled: () =>
      mounted.current ? client.invalidateQueries({ queryKey }) : undefined,
  });
  const confirmDelete = (ids: string[]) =>
    confirm({
      title: t(
        ids.length === 1
          ? "trajectory.deleteImport"
          : "trajectory.deleteSelected"
      ),
      content: t("trajectory.deleteSelectedConfirm", { count: ids.length }),
      danger: true,
      onOk: async () => {
        if (!mounted.current || deletion.current) return;
        await remove.mutateAsync([...ids]);
      },
    });
  const sortOrder = (field: SavedImportsSort["sort_by"]) =>
    sorting.sort_by === field
      ? sorting.sort_order === "asc"
        ? ("ascend" as const)
        : ("descend" as const)
      : null;
  const columns: ColumnsType<SavedTrajectoryRecord> = [
    {
      title: t("trajectory.importFilename"),
      dataIndex: "filename",
      key: "filename",
      sorter: true,
      sortOrder: sortOrder("filename"),
      ellipsis: true,
      width: 220,
    },
    {
      title: t("trajectory.agentSession"),
      render: (_, item) =>
        item.row.root_agent_name || t("trajectory.unknownAgent"),
      width: 180,
    },
    {
      title: t("trajectory.conversationId"),
      render: (_, item) => <code>{item.row.conversation_id}</code>,
      width: 200,
    },
    {
      title: t("trajectory.rounds"),
      render: (_, item) => formatMetric(item.row.round_count, 0),
      width: 100,
    },
    {
      title: t("trajectory.importSize"),
      render: (_, item) => `${formatMetric(item.size_bytes / 1024, 1)} KiB`,
      width: 120,
    },
    {
      title: t("trajectory.importedAt"),
      key: "imported_at",
      sorter: true,
      sortOrder: sortOrder("imported_at"),
      render: (_, item) => formatTraceTime(item.imported_at),
      width: 180,
    },
    {
      title: t("trajectory.importActions"),
      width: 180,
      render: (_, item) => (
        <div className="flex gap-2">
          <Button
            size="small"
            disabled={archive.loading || remove.isPending}
            onClick={() => {
              setOpening(item.import_id);
              void archive.open(item.import_id);
            }}
          >
            {t("trajectory.viewImport")}
          </Button>
          <Button
            size="small"
            danger
            disabled={remove.isPending}
            onClick={() => confirmDelete([item.import_id])}
          >
            {t("trajectory.deleteImport")}
          </Button>
        </div>
      ),
    },
  ];
  return (
    <main className="trajectory-center">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">
            {t("trajectory.importedList")}
          </h1>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            {t("trajectory.importedListHint")}
          </p>
        </div>
        <div className="trajectory-page-actions">
          <input
            ref={fileInput}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            aria-label={t("trajectory.import")}
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              event.currentTarget.value = "";
              if (file) {
                setOpening(null);
                void archive
                  .open(file)
                  .then(() => client.invalidateQueries({ queryKey }));
              }
            }}
          />
          <Button
            icon={<Upload size={14} />}
            disabled={remove.isPending}
            loading={archive.loading}
            onClick={() => fileInput.current?.click()}
          >
            {t("trajectory.import")}
          </Button>
          <Button
            icon={<RefreshCw size={14} />}
            loading={records.isFetching}
            disabled={remove.isPending}
            onClick={() => void records.refetch()}
          >
            {t("common.refresh")}
          </Button>
          <Link
            href={`/${i18n?.language?.startsWith("en") ? "en" : "zh"}/observability`}
          >
            <Button icon={<ArrowLeft size={14} />}>
              {t("trajectory.backToTraces")}
            </Button>
          </Link>
        </div>
      </header>
      {records.isError && (
        <TrajectoryError
          error={records.error}
          retry={() => void records.refetch()}
        />
      )}
      {archive.error != null && (
        <TrajectoryError
          error={archive.error}
          retry={() => {
            if (opening) void archive.open(opening);
            else fileInput.current?.click();
          }}
        />
      )}
      {!!remove.data?.failed.length && (
        <>
          <p role="status">
            {t("trajectory.deleteImportsPartial", {
              succeeded: remove.data.deleted.length,
              failed: remove.data.failed.length,
            })}
          </p>
          <TrajectoryError
            error={remove.data.failed[0].error}
            retry={() => confirmDelete(remove.data!.failed.map(({ id }) => id))}
          />
        </>
      )}
      <section className="trajectory-table-panel min-h-0 flex-1">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <Button
            danger
            icon={<Trash2 size={14} />}
            disabled={!selected.length || remove.isPending}
            loading={remove.isPending}
            onClick={() => confirmDelete([...selected])}
          >
            {t("trajectory.deleteSelected")}
          </Button>
          <span
            className="text-sm text-[var(--color-text-secondary)]"
            role="status"
          >
            {remove.isPending
              ? t("trajectory.deletingImports", progress)
              : t("trajectory.selectedImports", { count: selected.length })}
          </span>
        </div>
        <Table<SavedTrajectoryRecord>
          size="middle"
          rowKey="import_id"
          columns={columns}
          sortDirections={["ascend", "descend", "ascend"]}
          rowSelection={{
            selectedRowKeys: selected,
            preserveSelectedRowKeys: true,
            onChange: (keys) => setSelected(keys.map(String)),
            getCheckboxProps: () => ({ disabled: remove.isPending }),
          }}
          dataSource={records.data?.items ?? []}
          loading={records.isFetching}
          scroll={{ x: 1080 }}
          onChange={(_pagination, _filters, sorter, extra) => {
            if (
              remove.isPending ||
              extra.action !== "sort" ||
              Array.isArray(sorter)
            )
              return;
            const field = sorter.columnKey;
            if (field === "filename" || field === "imported_at") {
              setSorting({
                sort_by: field,
                sort_order: sorter.order === "ascend" ? "asc" : "desc",
              });
              setPaging((value) => ({ ...value, page: 1 }));
            }
          }}
          locale={{
            emptyText: <Empty description={t("trajectory.noImports")} />,
          }}
          pagination={{
            current: paging.page,
            pageSize: paging.page_size,
            total: records.data?.total ?? 0,
            showSizeChanger: true,
            disabled: remove.isPending,
            onChange: (page, pageSize) =>
              setPaging({ page, page_size: pageSize }),
          }}
        />
      </section>
      {archive.data && (
        <TrajectoryDrawer
          row={archive.data.row}
          imported={archive.data}
          onClose={archive.clear}
        />
      )}
    </main>
  );
}
