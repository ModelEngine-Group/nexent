// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useRef, useState } from "react";
import Link from "next/link";
import { Button, Empty, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeft, RefreshCw, Upload } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import type { User } from "@/types/auth";
import type { SavedTrajectoryRecord } from "@/types/trajectory";
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
  const [opening, setOpening] = useState<string | null>(null);
  const client = useQueryClient();
  const queryKey = ["trajectory-imports", scope];
  const records = useQuery({
    queryKey: [...queryKey, paging],
    queryFn: ({ signal }) =>
      trajectoryService.savedImports(paging.page, paging.page_size, signal),
    retry: false,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });
  const archive = useTrajectoryArchive(scope, true);
  const fileInput = useRef<HTMLInputElement>(null);
  const { confirm } = useConfirmModal();
  const remove = useMutation({
    mutationFn: (id: string) => trajectoryService.deleteImport(id),
    onSuccess: () => {
      archive.clear();
      setOpening(null);
      if (records.data?.items.length === 1 && paging.page > 1)
        setPaging((value) => ({ ...value, page: value.page - 1 }));
    },
    onSettled: () => client.invalidateQueries({ queryKey }),
  });
  const confirmDelete = (id: string) =>
    confirm({
      title: t("trajectory.deleteImport"),
      content: t("trajectory.deleteImportConfirm"),
      danger: true,
      onOk: async () => {
        await remove.mutateAsync(id);
      },
    });
  const columns: ColumnsType<SavedTrajectoryRecord> = [
    {
      title: t("trajectory.importFilename"),
      dataIndex: "filename",
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
            disabled={archive.loading}
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
            onClick={() => confirmDelete(item.import_id)}
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
            loading={archive.loading}
            onClick={() => fileInput.current?.click()}
          >
            {t("trajectory.import")}
          </Button>
          <Button
            icon={<RefreshCw size={14} />}
            loading={records.isFetching}
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
      {remove.isError && (
        <TrajectoryError
          error={remove.error}
          retry={() => confirmDelete(remove.variables)}
        />
      )}
      <section className="trajectory-table-panel min-h-0 flex-1">
        <Table<SavedTrajectoryRecord>
          size="middle"
          rowKey="import_id"
          columns={columns}
          dataSource={records.data?.items ?? []}
          loading={records.isFetching}
          scroll={{ x: 1080 }}
          locale={{
            emptyText: <Empty description={t("trajectory.noImports")} />,
          }}
          pagination={{
            current: paging.page,
            pageSize: paging.page_size,
            total: records.data?.total ?? 0,
            showSizeChanger: true,
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
