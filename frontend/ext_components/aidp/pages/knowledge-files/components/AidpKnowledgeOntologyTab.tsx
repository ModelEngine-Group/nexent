// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  Empty,
  Input,
  Segmented,
  Skeleton,
  Table,
  Tag,
  type TableColumnsType,
} from "antd";
import { ApartmentOutlined, SearchOutlined } from "@ant-design/icons";

import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { aidpRelationName } from "@/ext_components/aidp/shared/utils/aidpRelationDisplay";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type {
  AidpOntologyEntity,
  AidpOntologyMetadataField,
  AidpOntologyRule,
} from "@/ext_components/aidp/shared/types/ontology";
import tableStyles from "@/ext_components/aidp/shared/styles/AidpOntologyTable.module.css";
import styles from "./AidpKnowledgeOntologyTab.module.css";

interface AidpKnowledgeOntologyTabProps {
  /** AIDP KDS detail bind_lib_id; the domain ID when bind_lib_type=ontology. */
  bindingId?: number | string | null;
  /** AIDP KDS detail bind_lib_type: ontology / jargon / none. */
  bindingType?: string | null;
  /** AIDP KDS detail bind_lib_name. */
  bindingName?: string | null;
  bindingLoading: boolean;
}

type ReadonlyView = "metadata" | "entities" | "rules";

const AidpKnowledgeOntologyTab: React.FC<AidpKnowledgeOntologyTabProps> = ({
  bindingId,
  bindingType,
  bindingName,
  bindingLoading,
}) => {
  const { t } = useTranslation();
  const scope = useAidpQueryScope();
  const [view, setView] = useState<ReadonlyView>("metadata");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 10;

  useEffect(() => {
    const timer = window.setTimeout(
      () => setSearch(searchInput.trim()),
      300
    );
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const domainId =
    bindingType === "ontology" && bindingId ? String(bindingId) : null;
  const isJargonBound = bindingType === "jargon";

  const domainQuery = useQuery({
    queryKey: [...scope.key, "ontology-domain", domainId],
    queryFn: () => aidpOntologyService.getDomain(domainId as string),
    enabled: scope.enabled && !!domainId,
    staleTime: 30_000,
    retry: false,
  });

  const metadataQuery = useQuery({
    queryKey: [
      ...scope.key,
      "ontology-metadata-fields",
      domainId,
      page,
      search,
    ],
    queryFn: () =>
      aidpOntologyService.listMetadataFields(
        domainId as string,
        page,
        pageSize,
        search
      ),
    enabled: scope.enabled && !!domainId && view === "metadata",
    staleTime: 0,
    retry: false,
  });
  const entitiesQuery = useQuery({
    queryKey: [...scope.key, "kb-ontology-entities", domainId, page, search],
    queryFn: () =>
      aidpOntologyService.listEntities(
        domainId as string,
        page,
        pageSize,
        search
      ),
    enabled: scope.enabled && !!domainId && view === "entities",
    staleTime: 0,
    retry: false,
  });
  const rulesQuery = useQuery({
    queryKey: [...scope.key, "kb-ontology-rules", domainId],
    queryFn: () => aidpOntologyService.listRules(domainId as string, 1, 200),
    enabled: scope.enabled && !!domainId && view === "rules",
    staleTime: 0,
    retry: false,
  });

  const metadataColumns: TableColumnsType<AidpOntologyMetadataField> = [
    {
      title: t("aidpKnowledge.ontologyMetadataFieldName"),
      dataIndex: "field_name",
      key: "field_name",
      width: 220,
      render: (value: string) => value,
    },
    {
      title: t("aidpKnowledge.ontologyMetadataFieldType"),
      dataIndex: "field_type",
      key: "field_type",
      width: 120,
      render: (value: string) =>
        t(
          value === "string"
            ? "aidpKnowledge.ontologyMetadataTypeText"
            : value === "number"
              ? "aidpKnowledge.ontologyMetadataTypeNumber"
              : value === "date"
                ? "aidpKnowledge.ontologyMetadataTypeDate"
                : value
        ),
    },
  ];

  const entityColumns: TableColumnsType<AidpOntologyEntity> = [
    {
      title: t("aidpKnowledge.ontologyEntityColumnDisplayName"),
      key: "name",
      width: 160,
      render: (_value, record) => record.display_name || record.api_name,
    },
    {
      title: t("aidpKnowledge.ontologyEntityDescription"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
      render: (value: string) => value || "—",
    },
    {
      title: t("aidpKnowledge.ontologyEntityParent"),
      key: "parent",
      width: 140,
      render: (_value, record) =>
        (record.parent_entities ?? []).map((item) => aidpRelationName(item)).join("、") || "—",
    },
    {
      title: t("aidpKnowledge.ontologyEntitySynonym"),
      key: "synonym",
      width: 140,
      render: (_value, record) =>
        (record.synonym_entities ?? []).map((item) => aidpRelationName(item)).join("、") || "—",
    },
    {
      title: t("aidpKnowledge.ontologyEntityChild"),
      key: "child",
      width: 140,
      render: (_value, record) =>
        (record.child_entities ?? []).map((item) => aidpRelationName(item)).join("、") || "—",
    },
  ];

  const ruleColumns: TableColumnsType<AidpOntologyRule> = [
    {
      title: t("aidpKnowledge.ontologyRulesName"),
      dataIndex: "name",
      key: "name",
    },
    {
      title: t("aidpKnowledge.ontologyRulesDescription"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
      render: (value: string) => value || "—",
    },
    {
      title: t("aidpKnowledge.ontologyRulesEnabled"),
      dataIndex: "enabled",
      key: "enabled",
      width: 120,
      render: (value: boolean) => (
        <Tag color={value ? "green" : "default"}>
          {value
            ? t("aidpKnowledge.ontologyRulesEnabled")
            : t("aidpKnowledge.ontologyRulesDisabled")}
        </Tag>
      ),
    },
    {
      title: t("aidpKnowledge.ontologyRulesUpdatedAt"),
      dataIndex: "updated_at",
      key: "updated_at",
      width: 180,
      render: (value: string | null | undefined) => value || "—",
    },
  ];

  const metadataRows = metadataQuery.data?.value ?? [];
  const entityRows = entitiesQuery.data?.value ?? [];
  const ruleRows = (rulesQuery.data?.value ?? []).filter((item) =>
    (item.name ?? "").toLowerCase().includes(search.toLowerCase())
  );
  const total =
    view === "metadata"
      ? (metadataQuery.data?.total_count ?? metadataRows.length)
      : view === "entities"
        ? (entitiesQuery.data?.total_count ?? entityRows.length)
        : ruleRows.length;
  const hasMore =
    view === "metadata"
      ? (metadataQuery.data?.has_more ?? page * pageSize < total)
      : view === "entities"
        ? (entitiesQuery.data?.has_more ?? page * pageSize < total)
        : page * pageSize < total;

  const renderReadonly = () => {
    if (view === "metadata") {
      if (metadataQuery.isLoading)
        return <Skeleton active paragraph={{ rows: 4 }} />;
      return (
        <Table<AidpOntologyMetadataField>
          rowKey={(record) => String(record.id ?? record.field_name)}
          size="middle"
          className={tableStyles.table}
          columns={metadataColumns}
          dataSource={metadataRows}
          pagination={false}
          scroll={{ x: 760 }}
        />
      );
    }
    if (view === "entities") {
      if (entitiesQuery.isLoading)
        return <Skeleton active paragraph={{ rows: 4 }} />;
      return (
        <Table<AidpOntologyEntity>
          rowKey={(record) => record.entity_id ?? record.api_name}
          size="middle"
          className={tableStyles.table}
          columns={entityColumns}
          dataSource={entityRows}
          pagination={false}
          scroll={{ x: 760 }}
        />
      );
    }
    if (rulesQuery.isLoading)
      return <Skeleton active paragraph={{ rows: 4 }} />;
    return (
      <Table<AidpOntologyRule>
        rowKey="rule_id"
        size="middle"
        className={tableStyles.table}
        columns={ruleColumns}
        dataSource={ruleRows.slice(
          (page - 1) * pageSize,
          page * pageSize
        )}
        pagination={false}
        scroll={{ x: 760 }}
      />
    );
  };

  if (bindingLoading) {
    return <Skeleton active paragraph={{ rows: 4 }} />;
  }

  if (isJargonBound) {
    return (
      <div className={styles.emptyBlock}>
        <Empty
          image={
            <ApartmentOutlined
              className={styles.emptyIcon}
              aria-hidden="true"
            />
          }
          description={t("aidpKnowledge.ontologyKbJargonBound", {
            name: bindingName || "—",
          })}
        />
      </div>
    );
  }

  if (!domainId) {
    return (
      <div className={styles.emptyBlock}>
        <Empty
          image={
            <ApartmentOutlined
              className={styles.emptyIcon}
              aria-hidden="true"
            />
          }
          description={t("aidpKnowledge.ontologyKbEmpty")}
        />
      </div>
    );
  }

  return (
    <div className={styles.tab}>
      <section className={styles.overview}>
        <div className={styles.overviewText}>
          <div className={styles.titleRow}>
            <h2 className={styles.title}>
              {t("aidpKnowledge.ontologyKbHeaderPrefix")}
              {bindingName || domainQuery.data?.name || domainId}
            </h2>
          </div>
          <p className={styles.description}>
            {domainQuery.data?.description || "—"}
          </p>
        </div>
      </section>

      <Segmented<ReadonlyView>
        value={view}
        onChange={(next) => {
          setView(next);
          setPage(1);
          setSearchInput("");
          setSearch("");
        }}
        options={[
          {
            value: "metadata",
            label: t("aidpKnowledge.ontologyTabMetadata"),
          },
          {
            value: "entities",
            label: t("aidpKnowledge.ontologyTabEntities"),
          },
          { value: "rules", label: t("aidpKnowledge.ontologyTabRules") },
        ]}
      />
      <div className={styles.contentToolbar}>
        <Input
          allowClear
          className={styles.contentSearch}
          prefix={<SearchOutlined />}
          value={searchInput}
          onChange={(event) => {
            setSearchInput(event.target.value);
            setPage(1);
          }}
          placeholder={
            view === "metadata"
              ? t("aidpKnowledge.ontologyMetadataSearchPlaceholder")
              : view === "entities"
                ? t("aidpKnowledge.ontologyEntitySearchPlaceholder")
                : t("aidpKnowledge.ontologyKbSearchRules")
          }
        />
      </div>
      <div className={styles.tableArea}>{renderReadonly()}</div>
      {total > 0 && (
        <AidpPagination
          currentPage={page}
          pageSize={pageSize}
          pageSizeOptions={[10]}
          total={total}
          totalReliable
          hasMore={hasMore}
          onPageChange={setPage}
          onPageSizeChange={() => undefined}
        />
      )}
    </div>
  );
};

export default AidpKnowledgeOntologyTab;
