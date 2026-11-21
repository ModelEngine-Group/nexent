// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  Drawer,
  Segmented,
  Skeleton,
  Table,
  Tag,
  type TableColumnsType,
} from "antd";
import {
  ApartmentOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  TeamOutlined,
} from "@ant-design/icons";

import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type {
  AidpOntologyEntity,
  AidpOntologyMetadataField,
  AidpOntologyRule,
} from "@/ext_components/aidp/shared/types/ontology";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import tableStyles from "@/ext_components/aidp/shared/styles/AidpOntologyTable.module.css";
import styles from "./AidpOntologyPreviewDrawer.module.css";

interface AidpOntologyPreviewDrawerProps {
  open: boolean;
  domainId: string | null;
  onClose: () => void;
}

type PreviewView = "metadata" | "entities" | "rules";

const TYPE_LABEL_KEYS: Record<string, string> = {
  string: "aidpKnowledge.ontologyMetadataTypeText",
  time: "aidpKnowledge.ontologyMetadataTypeDate",
  number: "aidpKnowledge.ontologyMetadataTypeNumber",
};

/** Format an audit value with minutes without inventing a timestamp. */
const formatAuditTime = (value?: string | number | null): string => {
  if (!value) return "—";
  const text = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(text)) {
    return text.slice(0, 16).replace("T", " ");
  }
  return text || "—";
};

const relationName = (value: unknown): string => {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return String(
      record.display_name ??
        record.displayName ??
        record.api_name ??
        record.name ??
        record.id ??
        "—"
    );
  }
  return "—";
};

/**
 * Read-only ontology preview used by the knowledge base creation step.
 *
 * It intentionally offers no edit, delete, create, toggle or sync controls; the
 * only interactions are tab switching, pagination and closing the drawer.
 */
const AidpOntologyPreviewDrawer: React.FC<AidpOntologyPreviewDrawerProps> = ({
  open,
  domainId,
  onClose,
}) => {
  const { t } = useTranslation();
  const scope = useAidpQueryScope();
  const [view, setView] = useState<PreviewView>("metadata");
  const [page, setPage] = useState(1);
  const pageSize = 10;

  const domainQuery = useQuery({
    queryKey: [...scope.key, "ontology-domain", domainId],
    queryFn: () => aidpOntologyService.getDomain(domainId as string),
    enabled: scope.enabled && open && !!domainId,
    staleTime: 30_000,
    retry: false,
  });
  const metadataQuery = useQuery({
    queryKey: [...scope.key, "ontology-metadata-fields", domainId],
    queryFn: () => aidpOntologyService.listMetadataFields(domainId as string),
    enabled: scope.enabled && open && !!domainId && view === "metadata",
    staleTime: 0,
    retry: false,
  });
  const entitiesQuery = useQuery({
    queryKey: [...scope.key, "kb-ontology-entities", domainId],
    queryFn: () => aidpOntologyService.listEntities(domainId as string, 1, 50),
    enabled: scope.enabled && open && !!domainId && view === "entities",
    staleTime: 0,
    retry: false,
  });
  const rulesQuery = useQuery({
    queryKey: [...scope.key, "kb-ontology-rules", domainId],
    queryFn: () => aidpOntologyService.listRules(domainId as string, 1, 50),
    enabled: scope.enabled && open && !!domainId && view === "rules",
    staleTime: 0,
    retry: false,
  });
  const ruleCountQuery = useQuery({
    queryKey: [...scope.key, "ontology-rule-count", domainId],
    queryFn: () => aidpOntologyService.countRules(domainId as string),
    enabled: scope.enabled && open && !!domainId,
    staleTime: 30_000,
    retry: false,
  });

  const domain = domainQuery.data;
  const metadataColumns: TableColumnsType<AidpOntologyMetadataField> = [
    {
      title: t("aidpKnowledge.ontologyMetadataFieldName"),
      dataIndex: "field_name",
      key: "field_name",
      ellipsis: true,
    },
    {
      title: t("aidpKnowledge.ontologyMetadataFieldType"),
      dataIndex: "field_type",
      key: "field_type",
      width: 140,
      render: (value: string) => t(TYPE_LABEL_KEYS[value] ?? value),
    },
  ];
  const entityColumns: TableColumnsType<AidpOntologyEntity> = [
    {
      title: t("aidpKnowledge.ontologyEntityColumnDisplayName"),
      key: "name",
      width: 180,
      ellipsis: true,
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
        (record.parent_entities ?? []).map(relationName).join("、") || "—",
    },
  ];
  const ruleColumns: TableColumnsType<AidpOntologyRule> = [
    {
      title: t("aidpKnowledge.ontologyRulesName"),
      dataIndex: "name",
      key: "name",
      ellipsis: true,
    },
    {
      title: t("aidpKnowledge.ontologyRulesEnabled"),
      dataIndex: "enabled",
      key: "enabled",
      width: 120,
      render: (value: boolean) => (
        <Tag color={value ? "green" : "default"}>
          {value ? t("aidpKnowledge.ontologyRulesFilterEnabled") : "—"}
        </Tag>
      ),
    },
    {
      title: t("aidpKnowledge.ontologyMetadataColumnUpdateTime"),
      dataIndex: "updated_at",
      key: "updated_at",
      width: 170,
      render: (value: string | null | undefined) => formatAuditTime(value),
    },
  ];

  const rows =
    view === "metadata"
      ? (metadataQuery.data?.value ?? [])
      : view === "entities"
        ? (entitiesQuery.data?.value ?? [])
        : (rulesQuery.data?.value ?? []);
  const total =
    view === "metadata"
      ? (metadataQuery.data?.total_count ?? rows.length)
      : view === "entities"
        ? (entitiesQuery.data?.total_count ?? rows.length)
        : (rulesQuery.data?.total_count ?? rows.length);
  const pagedRows = rows.slice((page - 1) * pageSize, page * pageSize);
  const loading =
    (view === "metadata" && metadataQuery.isLoading) ||
    (view === "entities" && entitiesQuery.isLoading) ||
    (view === "rules" && rulesQuery.isLoading);

  return (
    <Drawer
      rootClassName={drawerStyles.drawer}
      open={open}
      width={760}
      onClose={onClose}
      destroyOnHidden
      title={domain?.name ?? t("aidpKnowledge.ontologyPreviewTitle")}
    >
      {domainQuery.isLoading ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : (
        <div className={styles.body}>
          <section className={styles.hero}>
            <div className={styles.heroTop}>
              <span className={styles.heroIcon} aria-hidden="true">
                <ApartmentOutlined />
              </span>
              <div className={styles.heroText}>
                <h2 className={styles.name}>{domain?.name ?? "—"}</h2>
                <p className={styles.description}>
                  {domain?.description || "—"}
                </p>
              </div>
            </div>
            <div className={styles.stats}>
              <div className={styles.statItem}>
                <DatabaseOutlined className={styles.statIcon} />
                <span className={styles.statText}>
                  <span className={styles.statLabel}>
                    {t("aidpKnowledge.ontologyDomainColumnMetadataCount")}
                  </span>
                  <span className={styles.statValue}>
                    {metadataQuery.data?.total_count ??
                      domain?.metadata_count ??
                      "—"}
                  </span>
                </span>
              </div>
              <div className={styles.statItem}>
                <TeamOutlined className={styles.statIcon} />
                <span className={styles.statText}>
                  <span className={styles.statLabel}>
                    {t("aidpKnowledge.ontologyDomainColumnEntityCount")}
                  </span>
                  <span className={styles.statValue}>
                    {entitiesQuery.data?.total_count ??
                      domain?.entity_count ??
                      "—"}
                  </span>
                </span>
              </div>
              <div className={styles.statItem}>
                <FileTextOutlined className={styles.statIcon} />
                <span className={styles.statText}>
                  <span className={styles.statLabel}>
                    {t("aidpKnowledge.ontologyTabRules")}
                  </span>
                  <span className={styles.statValue}>
                    {ruleCountQuery.data?.count ?? "—"}
                  </span>
                </span>
              </div>
              <div className={styles.statItem}>
                <ClockCircleOutlined className={styles.statIcon} />
                <span className={styles.statText}>
                  <span className={styles.statLabel}>
                    {t("aidpKnowledge.ontologyDomainColumnUpdateTime")}
                  </span>
                  <span className={styles.statValue}>
                    {formatAuditTime(domain?.update_time)}
                  </span>
                </span>
              </div>
            </div>
            <AidpOntologyGapNote>
              {t("aidpKnowledge.ontologyPreviewCountsGap")}
            </AidpOntologyGapNote>
          </section>

          <Segmented<PreviewView>
            value={view}
            onChange={(next) => {
              setView(next);
              setPage(1);
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

          <div className={styles.tableArea}>
            {loading ? (
              <Skeleton active paragraph={{ rows: 5 }} />
            ) : view === "metadata" ? (
              <Table<AidpOntologyMetadataField>
                rowKey={(record) => String(record.id ?? record.field_name)}
                size="middle"
                className={tableStyles.table}
                columns={metadataColumns}
                dataSource={pagedRows as AidpOntologyMetadataField[]}
                pagination={false}
                locale={{ emptyText: t("aidpKnowledge.ontologyTableEmpty") }}
              />
            ) : view === "entities" ? (
              <Table<AidpOntologyEntity>
                rowKey={(record) => record.entity_id ?? record.api_name}
                size="middle"
                className={tableStyles.table}
                columns={entityColumns}
                dataSource={pagedRows as AidpOntologyEntity[]}
                pagination={false}
                locale={{ emptyText: t("aidpKnowledge.ontologyTableEmpty") }}
              />
            ) : (
              <Table<AidpOntologyRule>
                rowKey="rule_id"
                size="middle"
                className={tableStyles.table}
                columns={ruleColumns}
                dataSource={pagedRows as AidpOntologyRule[]}
                pagination={false}
                locale={{ emptyText: t("aidpKnowledge.ontologyTableEmpty") }}
              />
            )}
          </div>

          {total > 0 && (
            <AidpPagination
              currentPage={page}
              pageSize={pageSize}
              pageSizeOptions={[10]}
              total={total}
              totalReliable
              hasMore={page * pageSize < total}
              showTotal
              onPageChange={setPage}
            />
          )}
        </div>
      )}
    </Drawer>
  );
};

export default AidpOntologyPreviewDrawer;
