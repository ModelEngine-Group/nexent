// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Empty,
  Grid,
  Select,
  Skeleton,
  Table,
  Tag,
  Tooltip,
  type TableColumnsType,
} from "antd";
import { ReloadOutlined } from "@ant-design/icons";

import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type {
  AidpBatchMetadataResult,
  AidpChunk,
} from "@/ext_components/aidp/shared/types/ontology";
import styles from "@/ext_components/aidp/shared/styles/AidpOntologyTable.module.css";
import AidpOntologyChunkDetailDrawer from "./AidpOntologyChunkDetailDrawer";
import AidpOntologyChunkAnnotateDrawer from "./AidpOntologyChunkAnnotateDrawer";
import chunkStyles from "./AidpOntologyMetadataChunks.module.css";

interface AidpOntologyMetadataChunksProps {
  domainId: string;
}

const renderMetadataTags = (metadata: Record<string, unknown>) => {
  const entries = Object.entries(metadata ?? {});
  if (entries.length === 0) return "—";
  const visible = entries.slice(0, 2);
  return (
    <div className={styles.metadataTags}>
      {visible.map(([key, value]) => (
        <Tag
          key={key}
          className={styles.metadataTag}
          title={`${key}: ${String(value)}`}
        >
          {key}: {String(value)}
        </Tag>
      ))}
      {entries.length > visible.length && (
        <span className={styles.metadataMore}>
          +{entries.length - visible.length}
        </span>
      )}
    </div>
  );
};

const AidpOntologyMetadataChunks: React.FC<AidpOntologyMetadataChunksProps> = ({
  domainId,
}) => {
  const { t } = useTranslation();
  const scope = useAidpQueryScope();
  const queryClient = useQueryClient();
  const [kdsId, setKdsId] = useState<string | undefined>();
  const [fileUuid, setFileUuid] = useState<string | undefined>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedRowKeys, setSelectedRowKeys] = useState<
    Array<string | number>
  >([]);
  const [detailChunkId, setDetailChunkId] = useState<string | number | null>(
    null
  );
  const [annotateIds, setAnnotateIds] = useState<Array<string | number> | null>(
    null
  );
  const screens = Grid.useBreakpoint();
  const isNarrow = screens.md === false;

  const bindingsQuery = useQuery({
    queryKey: [...scope.key, "ontology-bindings", domainId],
    queryFn: () => aidpOntologyService.listBindings(domainId),
    enabled: scope.enabled && !!domainId,
    staleTime: 0,
    retry: false,
  });

  const kbOptions = useMemo(
    () =>
      (bindingsQuery.data?.value ?? []).map((binding) => ({
        value: binding.kds_id,
        label: binding.kds_name || binding.kds_id,
      })),
    [bindingsQuery.data?.value]
  );

  const kbDetailQuery = useQuery({
    queryKey: [...scope.key, "ontology-kb-permission", kdsId],
    queryFn: () => aidpKnowledgeService.getKb(kdsId as string),
    enabled: scope.enabled && !!kdsId,
    staleTime: 30_000,
    retry: false,
  });
  const permission = kbDetailQuery.data?.permission as
    string | null | undefined;
  const canEdit = permission === "EDIT" || permission === "CREATOR";

  const toChunkKey = (key: React.Key): string | number =>
    typeof key === "bigint" ? key.toString() : key;

  const filesQuery = useQuery({
    queryKey: [...scope.key, "ontology-chunk-files", kdsId],
    queryFn: () =>
      aidpKnowledgeService.listIngestedFiles(kdsId as string, 1, 100),
    enabled: scope.enabled && !!kdsId,
    staleTime: 30_000,
    retry: false,
  });

  const fileOptions = useMemo(
    () =>
      (filesQuery.data?.value ?? []).map((file) => ({
        value: file.file_uuid,
        label: file.file_name || file.file_uuid,
      })),
    [filesQuery.data?.value]
  );

  const fieldsQuery = useQuery({
    queryKey: [...scope.key, "ontology-metadata-fields", domainId],
    queryFn: () => aidpOntologyService.listMetadataFields(domainId),
    enabled: scope.enabled && !!domainId,
    staleTime: 0,
    retry: false,
  });
  const fields = fieldsQuery.data?.value ?? [];

  const chunksQuery = useQuery({
    queryKey: [
      ...scope.key,
      "ontology-chunks",
      domainId,
      kdsId,
      fileUuid,
      { page, pageSize },
    ],
    queryFn: () =>
      aidpOntologyService.listChunks(
        kdsId as string,
        fileUuid as string,
        page,
        pageSize
      ),
    enabled: scope.enabled && !!kdsId && !!fileUuid,
    staleTime: 0,
    retry: false,
  });

  const chunks = chunksQuery.data?.value ?? [];
  const total = chunksQuery.data?.total_count ?? chunks.length;
  const totalReliable = chunksQuery.data?.total_reliable !== false;
  const hasMore = chunksQuery.data?.has_more ?? false;
  const errorMessage = chunksQuery.error
    ? getAidpErrorMessage(
        chunksQuery.error,
        t,
        t("aidpKnowledge.ontologyChunkLoadFailed")
      )
    : undefined;

  const refreshChunks = () => {
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "ontology-chunks", domainId, kdsId, fileUuid],
    });
    if (detailChunkId !== null) {
      void queryClient.invalidateQueries({
        queryKey: [...scope.key, "ontology-chunk", kdsId, detailChunkId],
      });
    }
  };

  const handleAnnotateFinished = (result: AidpBatchMetadataResult) => {
    refreshChunks();
    const failedIds = result.failed_list.map((item) => item.chunk_id);
    setSelectedRowKeys(failedIds);
  };

  const columns: TableColumnsType<AidpChunk> = [
    {
      title: t("aidpKnowledge.ontologyChunkId"),
      dataIndex: "chunk_id",
      key: "chunk_id",
      width: 120,
      render: (value: string | number) => (
        <span className={styles.ellipsis}>{value}</span>
      ),
    },
    {
      title: t("aidpKnowledge.ontologyChunkSummary"),
      dataIndex: "chunk_text",
      key: "chunk_text",
      render: (value: string) => (
        <Tooltip title={value} placement="topLeft">
          <span className={styles.cellSummary}>{value || "—"}</span>
        </Tooltip>
      ),
    },
    {
      title: t("aidpKnowledge.ontologyChunkType"),
      dataIndex: "chunk_type",
      key: "chunk_type",
      width: 110,
      render: (value: string) => (
        <Tag className={styles.kindTag}>{value || "—"}</Tag>
      ),
    },
    {
      title: t("aidpKnowledge.ontologyChunkMetadata"),
      dataIndex: "metadata",
      key: "metadata",
      width: 260,
      render: (value: Record<string, unknown>) =>
        renderMetadataTags(value ?? {}),
    },
    {
      title: t("aidpKnowledge.ontologyColumnActions"),
      key: "actions",
      width: 160,
      fixed: isNarrow ? undefined : "right",
      render: (_value, record) => (
        <div className={styles.rowActions}>
          <Button
            type="link"
            size="small"
            onClick={() => setDetailChunkId(record.chunk_id)}
          >
            {t("aidpKnowledge.ontologyChunkView")}
          </Button>
          <Tooltip
            title={
              canEdit
                ? undefined
                : t("aidpKnowledge.ontologyAnnotateNoPermission")
            }
          >
            <Button
              type="link"
              size="small"
              disabled={!canEdit || fields.length === 0}
              onClick={() => setAnnotateIds([record.chunk_id])}
            >
              {t("aidpKnowledge.ontologyChunkAnnotate")}
            </Button>
          </Tooltip>
        </div>
      ),
    },
  ];

  const renderChunkBody = () => {
    if (!kdsId) {
      return (
        <Empty
          className={styles.stateBlock}
          description={t("aidpKnowledge.ontologyChunkSelectKb")}
        />
      );
    }
    if (!fileUuid) {
      return (
        <Empty
          className={styles.stateBlock}
          description={t("aidpKnowledge.ontologyChunkSelectFile")}
        />
      );
    }
    if (chunksQuery.isLoading) {
      return (
        <div className={styles.stateBlock}>
          <Skeleton active title={false} paragraph={{ rows: 5 }} />
        </div>
      );
    }
    if (chunksQuery.isError) {
      return (
        <div className={styles.stateBlock}>
          <div className={styles.errorText} role="alert">
            {errorMessage}
          </div>
          <Button onClick={() => void chunksQuery.refetch()}>
            {t("aidpKnowledge.retry")}
          </Button>
        </div>
      );
    }
    if (chunks.length === 0) {
      return (
        <Empty
          className={styles.stateBlock}
          description={t("aidpKnowledge.ontologyChunkEmpty")}
        />
      );
    }
    return (
      <Table<AidpChunk>
        rowKey="chunk_id"
        size="middle"
        className={styles.table}
        columns={columns}
        dataSource={chunks}
        pagination={false}
        tableLayout="fixed"
        scroll={{ x: isNarrow ? 620 : 900 }}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys.map(toChunkKey)),
        }}
      />
    );
  };

  const kbName =
    kbOptions.find((option) => option.value === kdsId)?.label ?? kdsId ?? "";
  const fileName =
    fileOptions.find((option) => option.value === fileUuid)?.label ??
    fileUuid ??
    "";

  return (
    <div className={styles.tab}>
      {bindingsQuery.isSuccess && kbOptions.length === 0 && (
        <Alert
          type="warning"
          showIcon
          message={t("aidpKnowledge.ontologyChunkNoBoundKb")}
        />
      )}
      <div className={chunkStyles.contextRow}>
        <label className={chunkStyles.contextField}>
          <span className={chunkStyles.contextLabel}>
            {t("aidpKnowledge.ontologyChunkKbLabel")}
          </span>
          <Select
            className={chunkStyles.contextSelect}
            value={kdsId}
            onChange={(value) => {
              setKdsId(value);
              setFileUuid(undefined);
              setPage(1);
              setSelectedRowKeys([]);
            }}
            options={kbOptions}
            placeholder={t("aidpKnowledge.ontologyChunkKbPlaceholder")}
            showSearch
            optionFilterProp="label"
            loading={bindingsQuery.isFetching}
          />
        </label>
        <label className={chunkStyles.contextField}>
          <span className={chunkStyles.contextLabel}>
            {t("aidpKnowledge.ontologyChunkFileLabel")}
          </span>
          <Select
            className={chunkStyles.contextSelect}
            value={fileUuid}
            onChange={(value) => {
              setFileUuid(value);
              setPage(1);
              setSelectedRowKeys([]);
            }}
            options={fileOptions}
            disabled={!kdsId}
            placeholder={t("aidpKnowledge.ontologyChunkFilePlaceholder")}
            showSearch
            optionFilterProp="label"
            loading={filesQuery.isFetching}
            notFoundContent={
              filesQuery.isFetching
                ? t("aidpKnowledge.listLoading")
                : t("aidpKnowledge.ontologyChunkNoFiles")
            }
          />
        </label>
      </div>

      <div className={styles.toolbar}>
        <div className={styles.toolbarTitle}>
          <span className={styles.sectionTitle}>
            {t("aidpKnowledge.ontologyChunkTitle")}
          </span>
          {fileUuid && (
            <span className={styles.counter}>
              {t("aidpKnowledge.showTotal", { count: total })}
            </span>
          )}
        </div>
        <div className={styles.toolbarActions}>
          <Button
            type="text"
            aria-label={t("aidpKnowledge.refresh")}
            icon={<ReloadOutlined spin={chunksQuery.isFetching} />}
            disabled={!fileUuid}
            onClick={refreshChunks}
          />
          <Tooltip
            title={
              fields.length === 0
                ? t("aidpKnowledge.ontologyAnnotateNeedFields")
                : !canEdit
                  ? t("aidpKnowledge.ontologyAnnotateNoPermission")
                  : undefined
            }
          >
            <Button
              type="primary"
              disabled={
                selectedRowKeys.length === 0 || fields.length === 0 || !canEdit
              }
              onClick={() => setAnnotateIds(selectedRowKeys)}
            >
              {t("aidpKnowledge.ontologyBatchAnnotate")}
            </Button>
          </Tooltip>
        </div>
      </div>

      {errorMessage && chunks.length > 0 && (
        <div className={styles.inlineError} role="alert">
          {errorMessage}
        </div>
      )}
      <div className={styles.tableArea}>{renderChunkBody()}</div>
      {chunks.length > 0 && (
        <div className={styles.paginationRow}>
          <AidpPagination
            currentPage={page}
            pageSize={pageSize}
            pageSizeOptions={[10, 20, 50, 100]}
            total={total}
            totalReliable={totalReliable}
            hasMore={hasMore}
            showTotal={false}
            onPageChange={(nextPage) => {
              setPage(nextPage);
              setSelectedRowKeys([]);
            }}
            onPageSizeChange={(nextSize) => {
              setPageSize(nextSize);
              setPage(1);
              setSelectedRowKeys([]);
            }}
          />
        </div>
      )}

      <AidpOntologyChunkDetailDrawer
        open={detailChunkId !== null}
        kdsId={kdsId ?? ""}
        chunkId={detailChunkId}
        onClose={() => setDetailChunkId(null)}
      />
      {annotateIds && kdsId && (
        <AidpOntologyChunkAnnotateDrawer
          open={!!annotateIds}
          domainId={domainId}
          kdsId={kdsId}
          kbName={kbName}
          fileName={fileName}
          chunkIds={annotateIds}
          fields={fields}
          onClose={() => setAnnotateIds(null)}
          onFinished={handleAnnotateFinished}
        />
      )}
    </div>
  );
};

export default AidpOntologyMetadataChunks;
