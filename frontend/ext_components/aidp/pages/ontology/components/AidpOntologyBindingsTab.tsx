// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Empty,
  Input,
  Skeleton,
  Table,
  type TableColumnsType,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";

import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { useAidpOntologyDemoMode } from "@/ext_components/aidp/shared/hooks/useAidpOntologyDemoMode";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type { AidpOntologyBinding } from "@/ext_components/aidp/shared/types/ontology";
import styles from "@/ext_components/aidp/shared/styles/AidpOntologyTable.module.css";
import AidpOntologyBindingDrawer from "./AidpOntologyBindingDrawer";
import bindingStyles from "./AidpOntologyBindingsTab.module.css";

interface AidpOntologyBindingsTabProps {
  domainId: string;
  boundKbCount: number | null;
  onChanged: () => void;
}

/** Format an AIDP binding time with minutes without inventing a value. */
const formatAuditTime = (value?: string | null): string => {
  if (!value) return "—";
  const text = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(text)) {
    return text.slice(0, 16).replace("T", " ");
  }
  return text || "—";
};

const AidpOntologyBindingsTab: React.FC<AidpOntologyBindingsTabProps> = ({
  domainId,
  boundKbCount,
  onChanged,
}) => {
  const { t } = useTranslation();
  const { modal, message } = App.useApp();
  const scope = useAidpQueryScope();
  const queryClient = useQueryClient();
  const demo = useAidpOntologyDemoMode();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);

  const query = useQuery({
    queryKey: [...scope.key, "ontology-bindings", domainId],
    queryFn: () => aidpOntologyService.listBindings(domainId),
    enabled: scope.enabled && !!domainId,
    staleTime: 0,
    retry: false,
  });

  const bindings = useMemo(() => query.data?.value ?? [], [query.data?.value]);
  const detailQuery = useQuery({
    queryKey: [
      ...scope.key,
      "ontology-binding-kb-details",
      domainId,
      bindings
        .map((binding) => binding.kds_id)
        .sort()
        .join(","),
    ],
    queryFn: () =>
      aidpKnowledgeService.batchGetKbs(
        bindings.map((binding) => binding.kds_id)
      ),
    enabled: scope.enabled && bindings.length > 0,
    staleTime: 30_000,
    retry: false,
  });
  const displayBindings = useMemo(() => {
    const details = new Map(
      (detailQuery.data?.value ?? []).map((item) => [item.kds_id, item])
    );
    return bindings.map((binding) => {
      const detail = details.get(binding.kds_id);
      return {
        ...binding,
        kds_name: detail?.kds_name || binding.kds_name,
        description: detail?.description || "",
      };
    });
  }, [bindings, detailQuery.data?.value]);
  const filteredBindings = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return displayBindings;
    return displayBindings.filter((binding) =>
      (binding.kds_name ?? "").toLowerCase().includes(needle)
    );
  }, [displayBindings, search]);
  const total = query.data?.total_count ?? boundKbCount ?? bindings.length;
  const pagedBindings = filteredBindings.slice(
    (page - 1) * pageSize,
    page * pageSize
  );
  const selectedBindings = displayBindings.filter((binding) =>
    selectedKeys.includes(binding.kds_id)
  );
  const errorMessage = query.error
    ? getAidpErrorMessage(
        query.error,
        t,
        t("aidpKnowledge.ontologyBindingLoadFailed")
      )
    : undefined;

  const refresh = () => {
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "ontology-bindings", domainId],
    });
    onChanged();
  };

  const removeBindings = async (rows: AidpOntologyBinding[]) => {
    const outcomes = await Promise.allSettled(
      rows.map((binding) =>
        aidpOntologyService.deleteBinding(domainId, binding.kds_id)
      )
    );
    const failed = outcomes.filter(
      (outcome) => outcome.status === "rejected"
    ).length;
    if (failed > 0) {
      message.warning(
        t("aidpKnowledge.ontologyBindingBatchPartial", { count: failed })
      );
    } else {
      message.success(t("aidpKnowledge.ontologyUnbindSuccess"));
    }
    setSelectedKeys([]);
    refresh();
  };

  const openCancelConfirm = (rows: AidpOntologyBinding[]) => {
    modal.confirm({
      title: t("aidpKnowledge.ontologyBindingCancelTitle"),
      content: (
        <div className={bindingStyles.confirmBody}>
          <p>
            {t("aidpKnowledge.ontologyBindingCancelCount", {
              count: rows.length,
            })}
          </p>
          <div className={bindingStyles.confirmNames}>
            {rows.map((binding) => (
              <span key={binding.kds_id}>
                {binding.kds_name || binding.kds_id}
              </span>
            ))}
          </div>
          <p>{t("aidpKnowledge.ontologyBindingCancelBody")}</p>
          <AidpOntologyGapNote>
            {t("aidpKnowledge.ontologyUnbindGap")}
          </AidpOntologyGapNote>
        </div>
      ),
      width: 560,
      okText: t("aidpKnowledge.ontologyBindingCancelConfirm"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      centered: true,
      onOk: () => removeBindings(rows),
    });
  };

  const handleBatchCancel = () => {
    if (selectedBindings.length === 0) {
      message.warning(t("aidpKnowledge.ontologyBindingCancelSelectRequired"));
      return;
    }
    openCancelConfirm(selectedBindings);
  };

  const columns: TableColumnsType<AidpOntologyBinding> = [
    {
      title: t("aidpKnowledge.ontologyBindingColumnKbName"),
      dataIndex: "kds_name",
      key: "kds_name",
      width: 280,
      ellipsis: true,
      render: (value: string | null, record) => value || record.kds_id,
    },
    {
      title: t("aidpKnowledge.ontologyBindingColumnDescription"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
      render: (value: string | null | undefined) =>
        value || <span className={styles.metadataMore}>—</span>,
    },
    {
      title: t("aidpKnowledge.ontologyMetadataColumnCreateTime"),
      dataIndex: "create_time",
      key: "create_time",
      width: 170,
      render: (value: string | null | undefined) => formatAuditTime(value),
    },
    {
      title: t("aidpKnowledge.ontologyColumnActions"),
      key: "actions",
      width: 120,
      render: (_value, record) => (
        <div className={styles.rowActions}>
          <Button
            type="link"
            size="small"
            onClick={() => openCancelConfirm([record])}
          >
            {t("aidpKnowledge.ontologyBindCancelShort")}
          </Button>
        </div>
      ),
    },
  ];

  const renderBody = () => {
    if (query.isLoading) {
      return (
        <div className={styles.stateBlock}>
          <Skeleton active title={false} paragraph={{ rows: 4 }} />
        </div>
      );
    }
    if (query.isError) {
      return (
        <div className={styles.stateBlock}>
          <div className={styles.errorText} role="alert">
            {errorMessage}
          </div>
          <Button onClick={() => void query.refetch()}>
            {t("aidpKnowledge.retry")}
          </Button>
        </div>
      );
    }
    if (bindings.length === 0) {
      return (
        <Empty
          className={styles.emptyState}
          description={t("aidpKnowledge.ontologyBindingEmpty")}
        >
          <Button type="primary" onClick={() => setDrawerOpen(true)}>
            {t("aidpKnowledge.ontologyBindingAdd")}
          </Button>
        </Empty>
      );
    }
    return (
      <Table<AidpOntologyBinding>
        rowKey={(record) => record.kds_id}
        size="middle"
        className={styles.table}
        columns={columns}
        dataSource={pagedBindings}
        pagination={false}
        tableLayout="fixed"
        scroll={{ x: 900 }}
        rowSelection={{
          selectedRowKeys: selectedKeys,
          onChange: setSelectedKeys,
        }}
        locale={{ emptyText: t("aidpKnowledge.ontologyBindingSearchEmpty") }}
      />
    );
  };

  return (
    <div className={styles.tab}>
      <div className={styles.toolbar}>
        <Input
          allowClear
          className={styles.searchInput}
          prefix={<SearchOutlined />}
          placeholder={t("aidpKnowledge.ontologyBindingSearchPlaceholder")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(1);
          }}
        />
        <div className={styles.toolbarActions}>
          <Button
            disabled={selectedKeys.length === 0}
            onClick={handleBatchCancel}
          >
            {t("aidpKnowledge.ontologyBindCancelShort")}
          </Button>
          <Button type="primary" onClick={() => setDrawerOpen(true)}>
            {t("aidpKnowledge.ontologyBindingAdd")}
          </Button>
        </div>
      </div>
      <AidpOntologyGapNote>
        {demo
          ? t("aidpKnowledge.ontologyBindingDemoGap")
          : t("aidpKnowledge.ontologyBindingRealGap")}
      </AidpOntologyGapNote>
      <AidpOntologyGapNote>
        {t("aidpKnowledge.ontologyBindingDescriptionGap")}
      </AidpOntologyGapNote>
      <AidpOntologyGapNote>
        {t("aidpKnowledge.ontologyBindingStatusGap")}
      </AidpOntologyGapNote>
      {query.isError && bindings.length > 0 && (
        <div className={styles.inlineError} role="alert">
          {errorMessage}
        </div>
      )}
      <div className={styles.tableArea}>{renderBody()}</div>
      {filteredBindings.length > 0 && (
        <div className={styles.paginationRow}>
          <AidpPagination
            currentPage={page}
            pageSize={pageSize}
            pageSizeOptions={[10, 20, 50]}
            total={search.trim() ? filteredBindings.length : total}
            totalReliable
            hasMore={page * pageSize < filteredBindings.length}
            selectedCount={selectedKeys.length}
            onPageChange={setPage}
            onPageSizeChange={(nextSize) => {
              setPageSize(nextSize);
              setPage(1);
            }}
          />
        </div>
      )}
      <AidpOntologyBindingDrawer
        open={drawerOpen}
        domainId={domainId}
        onClose={() => setDrawerOpen(false)}
        onBound={() => {
          setDrawerOpen(false);
          refresh();
        }}
      />
    </div>
  );
};

export default AidpOntologyBindingsTab;
