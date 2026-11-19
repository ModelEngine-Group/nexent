// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  Button,
  Empty,
  Input,
  Skeleton,
  Table,
  type TableColumnsType,
} from "antd";
import { InfoCircleOutlined, SearchOutlined } from "@ant-design/icons";
import { useParams } from "next/navigation";

import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { useAidpOntologyDemoMode } from "@/ext_components/aidp/shared/hooks/useAidpOntologyDemoMode";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type { AidpOntologyDomain } from "@/ext_components/aidp/shared/types/ontology";
import tableStyles from "@/ext_components/aidp/shared/styles/AidpOntologyTable.module.css";
import AidpOntologyPreviewDrawer from "./AidpOntologyPreviewDrawer";
import styles from "./AidpCreateOntologyStep.module.css";

interface AidpCreateOntologyStepProps {
  selectedDomainId: string | null;
  onSelect: (domainId: string | null) => void;
}

/** Format an audit date with time without inventing a missing value. */
const formatAuditTime = (value?: string | number | null): string => {
  if (value === null || value === undefined || value === "") return "—";
  const text = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(text)) {
    return text.slice(0, 16).replace("T", " ");
  }
  return text || "—";
};

/**
 * Optional ontology picker shown between configuration and user groups.
 *
 * Single-select only; clicking the name opens a read-only preview instead of
 * selecting the row, so the selection and inspection actions stay separate.
 */
const AidpCreateOntologyStep: React.FC<AidpCreateOntologyStepProps> = ({
  selectedDomainId,
  onSelect,
}) => {
  const { t } = useTranslation();
  const params = useParams();
  const locale = (params?.locale as string) || "zh";
  const scope = useAidpQueryScope();
  const demo = useAidpOntologyDemoMode();
  const [page, setPage] = useState(1);
  const pageSize = 10;
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [previewDomainId, setPreviewDomainId] = useState<string | null>(null);

  const query = useQuery({
    queryKey: [...scope.key, "create-ontology-options", { page, search }],
    queryFn: () => aidpOntologyService.listDomains(page, pageSize, search),
    enabled: scope.enabled,
    staleTime: 30_000,
    retry: false,
  });

  const domains = query.data?.value ?? [];
  const total = query.data?.total_count ?? domains.length;

  const columns: TableColumnsType<AidpOntologyDomain> = [
    {
      title: t("aidpKnowledge.ontologyDomainColumnName"),
      dataIndex: "name",
      key: "name",
      width: 180,
      ellipsis: true,
      render: (value: string, record) => (
        <button
          type="button"
          className={styles.nameLink}
          onClick={(event) => {
            event.stopPropagation();
            setPreviewDomainId(record.domain_id);
          }}
        >
          {value}
        </button>
      ),
    },
    {
      title: t("aidpKnowledge.ontologyDomainColumnDescription"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
      render: (value: string) => value || "—",
    },
    {
      title: t("aidpKnowledge.ontologyDomainColumnMetadataCount"),
      dataIndex: "metadata_count",
      key: "metadata_count",
      width: 90,
      render: (value: number | null | undefined) =>
        value === null || value === undefined ? "—" : value,
    },
    {
      title: t("aidpKnowledge.ontologyDomainColumnEntityCount"),
      dataIndex: "entity_count",
      key: "entity_count",
      width: 90,
      render: (value: number | null | undefined) =>
        value === null || value === undefined ? "—" : value,
    },
    {
      title: t("aidpKnowledge.ontologyTabRules"),
      dataIndex: "rule_count",
      key: "rule_count",
      width: 100,
      render: (value: number | null | undefined) =>
        value === null || value === undefined ? "—" : value,
    },
    {
      title: t("aidpKnowledge.ontologyMetadataColumnCreateTime"),
      dataIndex: "create_time",
      key: "create_time",
      width: 170,
      render: (value: string | number | null | undefined) =>
        formatAuditTime(value),
    },
  ];

  return (
    <section className={styles.step}>
      <div className={styles.banner}>
        <InfoCircleOutlined />
        <span>{t("aidpKnowledge.createOntologyBanner")}</span>
      </div>
      <div className={styles.toolbar}>
        <Input
          allowClear
          className={styles.search}
          prefix={<SearchOutlined />}
          placeholder={t("aidpKnowledge.createOntologySearch")}
          value={searchInput}
          onChange={(event) => {
            setSearchInput(event.target.value);
            if (!event.target.value) {
              setSearch("");
              setPage(1);
            }
          }}
          onPressEnter={() => {
            setSearch(searchInput.trim());
            setPage(1);
          }}
        />
        {selectedDomainId && (
          <Button type="link" onClick={() => onSelect(null)}>
            {t("aidpKnowledge.createOntologyClear")}
          </Button>
        )}
      </div>
      <AidpOntologyGapNote>
        {demo
          ? t("aidpKnowledge.createOntologyDemoGap")
          : t("aidpKnowledge.createOntologyRealGap")}
      </AidpOntologyGapNote>
      <div className={styles.tableArea}>
        {query.isLoading ? (
          <Skeleton active paragraph={{ rows: 6 }} />
        ) : query.isError ? (
          <div className={styles.errorText} role="alert">
            {getAidpErrorMessage(
              query.error,
              t,
              t("aidpKnowledge.ontologyListLoadFailed")
            )}
          </div>
        ) : domains.length === 0 ? (
          <Empty
            className={styles.empty}
            image={Empty.PRESENTED_IMAGE_DEFAULT}
            description={
              search
                ? t("aidpKnowledge.ontologySearchEmpty")
                : t("aidpKnowledge.createOntologyEmpty")
            }
          >
            {!search && (
              <Button
                type="primary"
                onClick={() => {
                  window.open(
                    `/${locale}/knowledges/ontology/create`,
                    "_blank",
                    "noopener,noreferrer"
                  );
                }}
              >
                {t("aidpKnowledge.createOntologyEmptyAction")}
              </Button>
            )}
          </Empty>
        ) : (
          <Table<AidpOntologyDomain>
            rowKey="domain_id"
            size="middle"
            className={tableStyles.table}
            columns={columns}
            dataSource={domains}
            pagination={false}
            tableLayout="fixed"
            scroll={{ x: 900 }}
            rowSelection={{
              type: "radio",
              selectedRowKeys: selectedDomainId ? [selectedDomainId] : [],
              onChange: (keys) => onSelect(String(keys[0])),
            }}
            onRow={(record) => ({
              onClick: () => onSelect(record.domain_id),
            })}
          />
        )}
      </div>
      {total > 0 && (
        <AidpPagination
          currentPage={page}
          pageSize={pageSize}
          pageSizeOptions={[10]}
          total={total}
          totalReliable={query.data?.total_reliable !== false}
          hasMore={query.data?.has_more ?? false}
          showTotal
          onPageChange={setPage}
        />
      )}
      <AidpOntologyPreviewDrawer
        open={!!previewDomainId}
        domainId={previewDomainId}
        onClose={() => setPreviewDomainId(null)}
      />
    </section>
  );
};

export default AidpCreateOntologyStep;
