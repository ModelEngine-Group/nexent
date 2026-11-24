// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Checkbox,
  Dropdown,
  Empty,
  Input,
  Segmented,
  Skeleton,
  Table,
  Tag,
  Tooltip,
  type TableColumnsType,
} from "antd";
import {
  ApartmentOutlined,
  DownloadOutlined,
  SearchOutlined,
  SettingOutlined,
} from "@ant-design/icons";

import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type {
  AidpOntologyEntity,
  AidpOntologyMetadataField,
  AidpOntologyRule,
} from "@/ext_components/aidp/shared/types/ontology";
import tableStyles from "@/ext_components/aidp/shared/styles/AidpOntologyTable.module.css";
import AidpKnowledgeOntologyPicker from "./AidpKnowledgeOntologyPicker";
import styles from "./AidpKnowledgeOntologyTab.module.css";

interface AidpKnowledgeOntologyTabProps {
  kdsId: string;
  /** AIDP KDS detail bind_lib_id; the domain ID when bind_lib_type=ontology. */
  bindingId?: number | string | null;
  /** AIDP KDS detail bind_lib_type: ontology / jargon / none. */
  bindingType?: string | null;
  /** AIDP KDS detail bind_lib_name. */
  bindingName?: string | null;
  bindingLoading?: boolean;
  onBindingChanged?: () => void;
}

type ReadonlyView = "metadata" | "entities" | "rules";

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

const AidpKnowledgeOntologyTab: React.FC<AidpKnowledgeOntologyTabProps> = ({
  kdsId,
  bindingId,
  bindingType,
  bindingName,
  bindingLoading = false,
  onBindingChanged,
}) => {
  const { t } = useTranslation();
  const { modal, message } = App.useApp();
  const scope = useAidpQueryScope();
  const queryClient = useQueryClient();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [view, setView] = useState<ReadonlyView>("metadata");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [showChunkCount, setShowChunkCount] = useState(true);
  const pageSize = 10;

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
    queryKey: [...scope.key, "ontology-metadata-fields", domainId],
    queryFn: () => aidpOntologyService.listMetadataFields(domainId as string),
    enabled: scope.enabled && !!domainId && view === "metadata",
    staleTime: 0,
    retry: false,
  });
  const entitiesQuery = useQuery({
    queryKey: [...scope.key, "kb-ontology-entities", domainId],
    queryFn: () => aidpOntologyService.listEntities(domainId as string, 1, 50),
    enabled: scope.enabled && !!domainId && view === "entities",
    staleTime: 0,
    retry: false,
  });
  const rulesQuery = useQuery({
    queryKey: [...scope.key, "kb-ontology-rules", domainId],
    queryFn: () => aidpOntologyService.listRules(domainId as string, 1, 50),
    enabled: scope.enabled && !!domainId && view === "rules",
    staleTime: 0,
    retry: false,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "ontology-domain"],
    });
    onBindingChanged?.();
  };

  const handleUnbind = (change: boolean) => {
    if (!domainId) return;
    modal.confirm({
      title: change
        ? t("aidpKnowledge.ontologyKbChangeTitle")
        : t("aidpKnowledge.ontologyKbUnbindTitle", {
            name: domainQuery.data?.name || bindingName || domainId,
          }),
      content: (
        <div className={styles.confirmBody}>
          <p>{t("aidpKnowledge.ontologyKbUnbindContent")}</p>
        </div>
      ),
      width: 520,
      okText: change
        ? t("aidpKnowledge.ontologyKbUnbindFirst")
        : t("common.confirm"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      centered: true,
      onOk: async () => {
        try {
          await aidpOntologyService.deleteBinding(domainId, kdsId);
          message.success(t("aidpKnowledge.ontologyUnbindSuccess"));
          refresh();
        } catch (error) {
          message.error(
            getAidpErrorMessage(
              error,
              t,
              t("aidpKnowledge.ontologyUnbindFailed")
            )
          );
          throw error;
        }
      },
    });
  };

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
        (record.parent_entities ?? []).map(relationName).join("、") || "—",
    },
    {
      title: t("aidpKnowledge.ontologyEntitySynonym"),
      key: "synonym",
      width: 140,
      render: (_value, record) =>
        (record.synonym_entities ?? []).map(relationName).join("、") || "—",
    },
    {
      title: t("aidpKnowledge.ontologyEntityChild"),
      key: "child",
      width: 140,
      render: (_value, record) =>
        (record.child_entities ?? []).map(relationName).join("、") || "—",
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
          {value ? t("aidpKnowledge.ontologyRulesFilterEnabled") : "—"}
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

  const metadataRows = (metadataQuery.data?.value ?? []).filter((item) =>
    item.field_name.toLowerCase().includes(search.trim().toLowerCase())
  );
  const entityRows = (entitiesQuery.data?.value ?? []).filter((item) =>
    `${item.display_name ?? ""} ${item.api_name}`
      .toLowerCase()
      .includes(search.trim().toLowerCase())
  );
  const ruleRows = (rulesQuery.data?.value ?? []).filter((item) =>
    (item.name ?? "").toLowerCase().includes(search.trim().toLowerCase())
  );
  const activeTotal =
    view === "metadata"
      ? metadataRows.length
      : view === "entities"
        ? entityRows.length
        : ruleRows.length;

  const handleExport = () => {
    const rows =
      view === "metadata"
        ? metadataRows
        : view === "entities"
          ? entityRows
          : ruleRows;
    const blob = new Blob([JSON.stringify(rows, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `ontology-${domainId}-${view}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
    message.success(t("aidpKnowledge.ontologyKbExportDone"));
  };

  const renderReadonly = () => {
    if (view === "metadata") {
      if (metadataQuery.isLoading)
        return <Skeleton active paragraph={{ rows: 4 }} />;
      return (
        <Table<AidpOntologyMetadataField>
          rowKey={(record) => String(record.id ?? record.field_name)}
          size="middle"
          className={tableStyles.table}
          columns={metadataColumns.filter(
            (column) => showChunkCount || column.key !== "chunk"
          )}
          dataSource={metadataRows.slice(
            (page - 1) * pageSize,
            page * pageSize
          )}
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
          columns={entityColumns.filter(
            (column) => showChunkCount || column.key !== "chunk"
          )}
          dataSource={entityRows.slice((page - 1) * pageSize, page * pageSize)}
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
        dataSource={ruleRows.slice((page - 1) * pageSize, page * pageSize)}
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
        >
          <Button type="primary" onClick={() => setPickerOpen(true)}>
            {t("aidpKnowledge.ontologyKbAdd")}
          </Button>
        </Empty>
        <AidpKnowledgeOntologyPicker
          open={pickerOpen}
          kdsId={kdsId}
          mode="add"
          onClose={() => setPickerOpen(false)}
          onBound={() => {
            setPickerOpen(false);
            refresh();
          }}
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
        <div className={styles.actions}>
          <Button danger onClick={() => handleUnbind(false)}>
            {t("aidpKnowledge.ontologyKbRemoveBinding")}
          </Button>
          <Button type="primary" onClick={() => handleUnbind(true)}>
            {t("aidpKnowledge.ontologyKbChangeShort")}
          </Button>
        </div>
      </section>

      <Segmented<ReadonlyView>
        value={view}
        onChange={(next) => {
          setView(next);
          setPage(1);
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
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
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
        <Tooltip title={t("aidpKnowledge.ontologyMetadataExport")}>
          <Button
            aria-label={t("aidpKnowledge.ontologyMetadataExport")}
            icon={<DownloadOutlined />}
            disabled={activeTotal === 0}
            onClick={handleExport}
          />
        </Tooltip>
        <Dropdown
          trigger={["click"]}
          menu={{
            items: [
              {
                key: "chunk",
                label: (
                  <Checkbox
                    checked={showChunkCount}
                    onChange={(event) =>
                      setShowChunkCount(event.target.checked)
                    }
                  >
                    {t("aidpKnowledge.ontologyMetadataColumnChunkCount")}
                  </Checkbox>
                ),
              },
            ],
          }}
        >
          <Button
            aria-label={t("aidpKnowledge.ontologyMetadataColumnSettings")}
            icon={<SettingOutlined />}
          />
        </Dropdown>
      </div>
      <div className={styles.tableArea}>{renderReadonly()}</div>
      {activeTotal > 0 && (
        <AidpPagination
          currentPage={page}
          pageSize={pageSize}
          pageSizeOptions={[10]}
          total={activeTotal}
          totalReliable
          hasMore={page * pageSize < activeTotal}
          onPageChange={setPage}
          onPageSizeChange={() => undefined}
        />
      )}
    </div>
  );
};

export default AidpKnowledgeOntologyTab;
