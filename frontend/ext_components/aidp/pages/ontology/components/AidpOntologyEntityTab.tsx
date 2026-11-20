// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Checkbox,
  Dropdown,
  Empty,
  Input,
  Popover,
  Skeleton,
  Table,
  Tag,
  Tooltip,
  type TableColumnsType,
} from "antd";
import {
  QuestionCircleOutlined,
  ReloadOutlined,
  SearchOutlined,
  SettingOutlined,
} from "@ant-design/icons";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import AidpResizableTitle, {
  type AidpResizableTitleProps,
} from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";
import { AIDP_MIN_COLUMN_WIDTH } from "@/ext_components/aidp/pages/knowledge-list/utils/aidpKnowledgeColumnWidths";
import { useAidpOntologyColumnWidths } from "@/ext_components/aidp/shared/hooks/useAidpOntologyColumnWidths";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type { AidpOntologyEntity } from "@/ext_components/aidp/shared/types/ontology";
import styles from "@/ext_components/aidp/shared/styles/AidpOntologyTable.module.css";
import AidpOntologyEntityDrawer from "./AidpOntologyEntityDrawer";
import AidpOntologyEntityDetailDrawer from "./AidpOntologyEntityDetailDrawer";
import entityStyles from "./AidpOntologyEntityTab.module.css";

interface AidpOntologyEntityTabProps {
  domainId: string;
  /** Open the create drawer once when the list quick action navigates here. */
  autoOpenCreate?: boolean;
}

const SEARCH_DEBOUNCE_MS = 300;
const MANAGER_ROLES = new Set(["SU", "ADMIN", "SPEED", "ASSET_OWNER"]);
const DEFAULT_PAGE_SIZE = 10;

/** Format an AIDP entity audit value with minutes, never inventing a time. */
const formatAuditTime = (value?: string | null): string => {
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

const AidpOntologyEntityTab: React.FC<AidpOntologyEntityTabProps> = ({
  domainId,
  autoOpenCreate = false,
}) => {
  const { t } = useTranslation();
  const { modal, message } = App.useApp();
  const scope = useAidpQueryScope();
  const queryClient = useQueryClient();
  const { user, isAuthzReady } = useAuthorizationContext();
  const canManage = !!user && MANAGER_ROLES.has(user.role) && isAuthzReady;
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [visibleColumns, setVisibleColumns] = useState({
    kind: true,
    description: true,
    extended: true,
    parent: true,
    synonym: true,
    child: true,
    createTime: true,
  });
  const [keyword, setKeyword] = useState("");
  const [appliedKeyword, setAppliedKeyword] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(autoOpenCreate);
  const [editing, setEditing] = useState<AidpOntologyEntity | null>(null);
  const [detailEntity, setDetailEntity] = useState<AidpOntologyEntity | null>(
    null
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setAppliedKeyword(keyword.trim());
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [keyword]);

  const queryKey = useMemo(
    () => [
      ...scope.key,
      "ontology-entities",
      domainId,
      { page, pageSize, keyword: appliedKeyword },
    ],
    [appliedKeyword, domainId, page, pageSize, scope.key]
  );

  const query = useQuery({
    queryKey,
    queryFn: () =>
      aidpOntologyService.listEntities(
        domainId,
        page,
        pageSize,
        appliedKeyword || undefined
      ),
    enabled: scope.enabled && !!domainId,
    staleTime: 30_000,
    retry: false,
  });

  const entities = query.data?.value ?? [];
  const selectedEntities = entities.filter((entity) =>
    selectedKeys.includes(
      entity.entity_id ?? `${entity.api_name}-${entity.kind}`
    )
  );
  const total = query.data?.total_count ?? entities.length;
  const totalReliable = query.data?.total_reliable !== false;
  const hasMore = query.data?.has_more ?? false;
  const errorMessage = query.error
    ? getAidpErrorMessage(
        query.error,
        t,
        t("aidpKnowledge.ontologyEntityLoadFailed")
      )
    : undefined;

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "ontology-entities", domainId],
    });
  }, [domainId, queryClient, scope.key]);

  const handleDelete = (entity: AidpOntologyEntity) => {
    if (!entity.entity_id) {
      message.warning(t("aidpKnowledge.ontologyEntityMissingIdAction"));
      return;
    }
    modal.confirm({
      title: t("aidpKnowledge.ontologyEntityDeleteTitleFixed"),
      content: (
        <div className={entityStyles.confirmBody}>
          <p>
            {t("aidpKnowledge.ontologyEntityDeleteContentWithName", {
              name: entity.display_name || entity.api_name,
            })}
          </p>
        </div>
      ),
      width: 500,
      okText: t("aidpKnowledge.ontologyDelete"),
      cancelText: t("common.cancel"),
      centered: true,
      onOk: async () => {
        try {
          await aidpOntologyService.deleteEntity(
            domainId,
            entity.entity_id as string
          );
          message.success(t("aidpKnowledge.ontologyEntityDeleted"));
          refresh();
        } catch (error) {
          message.error(
            getAidpErrorMessage(
              error,
              t,
              t("aidpKnowledge.ontologyEntityDeleteFailed")
            )
          );
          throw error;
        }
      },
    });
  };

  const headerHint = (label: string, hint: string) => (
    <span className={entityStyles.columnTitle}>
      {label}
      <Tooltip title={hint}>
        <QuestionCircleOutlined className={entityStyles.hintIcon} />
      </Tooltip>
    </span>
  );

  const renderRelations = (values: unknown[] | undefined) => {
    if (!values || values.length === 0) {
      return <span className={entityStyles.muted}>—</span>;
    }
    const names = values.map(relationName);
    const visible = names.slice(0, 1);
    const hidden = names.slice(1);
    return (
      <Popover
        trigger="hover"
        placement="topLeft"
        content={
          <div className={entityStyles.popoverTags}>
            {names.map((name, index) => (
              <Tag key={`${name}-${index}`}>{name}</Tag>
            ))}
          </div>
        }
      >
        <div
          className={`${styles.metadataTags} ${entityStyles.relationTrigger}`}
        >
          {visible.map((name, index) => (
            <Tag key={`${name}-${index}`} className={styles.metadataTag}>
              {name}
            </Tag>
          ))}
          {hidden.length > 0 && (
            <span className={styles.metadataMore}>+{hidden.length}</span>
          )}
        </div>
      </Popover>
    );
  };

  const handleBatchDelete = () => {
    if (selectedEntities.length === 0) {
      message.warning(t("aidpKnowledge.ontologyEntitySelectDeleteRequired"));
      return;
    }
    modal.confirm({
      title: t("aidpKnowledge.ontologyEntityBatchDeleteTitle", {
        count: selectedEntities.length,
      }),
      width: 500,
      content: (
        <div className={entityStyles.confirmBody}>
          <p>{t("aidpKnowledge.ontologyEntityDeleteWarning")}</p>
        </div>
      ),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      centered: true,
      onOk: async () => {
        const outcomes = await Promise.allSettled(
          selectedEntities.map((entity) =>
            aidpOntologyService.deleteEntity(
              domainId,
              entity.entity_id as string
            )
          )
        );
        const failed = outcomes.filter(
          (outcome) => outcome.status === "rejected"
        ).length;
        if (failed > 0) {
          message.warning(
            t("aidpKnowledge.ontologyEntityBatchDeletePartial", {
              count: failed,
            })
          );
        } else {
          message.success(t("aidpKnowledge.ontologyEntityDeleted"));
        }
        setSelectedKeys([]);
        refresh();
      },
    });
  };

  const columns: TableColumnsType<AidpOntologyEntity> = [
    {
      title: t("aidpKnowledge.ontologyEntityNameLabel"),
      dataIndex: "display_name",
      key: "display_name",
      width: 150,
      render: (value: string, record) => (
        <button
          type="button"
          className={entityStyles.nameButton}
          onClick={() => setDetailEntity(record)}
        >
          {value || record.api_name}
        </button>
      ),
    },
    ...(visibleColumns.kind
      ? [
          {
            title: t("aidpKnowledge.ontologyEntityObjectKind"),
            key: "kind",
            width: 100,
            render: (_value: unknown, record: AidpOntologyEntity) => (
              <Tag
                className={entityStyles.kindTag}
                color={record.kind === "type" ? "blue" : "default"}
              >
                {record.kind === "type"
                  ? t("aidpKnowledge.ontologyEntityKindType")
                  : t("aidpKnowledge.ontologyEntityKindEntity")}
              </Tag>
            ),
          },
        ]
      : []),
    ...(visibleColumns.description
      ? [
          {
            title: t("aidpKnowledge.ontologyEntityColumnDescription"),
            dataIndex: "description",
            key: "description",
            width: 160,
            ellipsis: true,
            render: (value: string) => (
              <Tooltip title={value || undefined} placement="topLeft">
                <span className={styles.ellipsis}>{value || "—"}</span>
              </Tooltip>
            ),
          },
        ]
      : []),
    ...(visibleColumns.extended
      ? [
          {
            title: headerHint(
              t("aidpKnowledge.ontologyEntityExtended"),
              t("aidpKnowledge.ontologyEntityExtendedHint")
            ),
            key: "extended",
            width: 140,
            render: (_value: unknown, record: AidpOntologyEntity) => {
              const properties = record.properties ?? [];
              if (properties.length === 0) {
                return <span className={entityStyles.muted}>—</span>;
              }
              return (
                <Popover
                  trigger="hover"
                  placement="topLeft"
                  content={
                    <div className={entityStyles.popoverList}>
                      {properties.map((property, index) => (
                        <span key={`${property.api_name}-${index}`}>
                          {property.display_name || property.api_name}:{" "}
                          {property.value || "—"}
                        </span>
                      ))}
                    </div>
                  }
                >
                  <span className={entityStyles.relationTrigger}>
                    {t("aidpKnowledge.ontologyEntityExtendedCount", {
                      count: properties.length,
                    })}
                  </span>
                </Popover>
              );
            },
          },
        ]
      : []),
    ...(visibleColumns.parent
      ? [
          {
            title: headerHint(
              t("aidpKnowledge.ontologyEntityParent"),
              t("aidpKnowledge.ontologyEntityParentHint")
            ),
            key: "parents",
            width: 130,
            render: (_value: unknown, record: AidpOntologyEntity) =>
              renderRelations(record.parent_entities),
          },
        ]
      : []),
    ...(visibleColumns.synonym
      ? [
          {
            title: headerHint(
              t("aidpKnowledge.ontologyEntitySynonym"),
              t("aidpKnowledge.ontologyEntitySynonymHint")
            ),
            key: "synonyms",
            width: 140,
            render: (_value: unknown, record: AidpOntologyEntity) =>
              renderRelations(record.synonym_entities),
          },
        ]
      : []),
    ...(visibleColumns.child
      ? [
          {
            title: headerHint(
              t("aidpKnowledge.ontologyEntityChild"),
              t("aidpKnowledge.ontologyEntityChildHint")
            ),
            key: "children",
            width: 140,
            render: (_value: unknown, record: AidpOntologyEntity) =>
              renderRelations(record.child_entities),
          },
        ]
      : []),
    ...(visibleColumns.createTime
      ? [
          {
            title: t("aidpKnowledge.ontologyMetadataColumnCreateTime"),
            key: "create_time",
            width: 170,
            render: (_value: unknown, record: AidpOntologyEntity) => (
              <span>{formatAuditTime(record.create_time)}</span>
            ),
          },
        ]
      : []),
    {
      title: t("aidpKnowledge.ontologyColumnActions"),
      key: "actions",
      width: 150,
      render: (_value, record) => (
        <div className={styles.rowActions}>
          <Tooltip
            title={
              record.entity_id
                ? undefined
                : t("aidpKnowledge.ontologyEntityMissingIdAction")
            }
          >
            <Button
              type="link"
              size="small"
              disabled={!canManage || !record.entity_id}
              onClick={() => {
                setEditing(record);
                setDrawerOpen(true);
              }}
            >
              {t("aidpKnowledge.ontologyEdit")}
            </Button>
          </Tooltip>
          <Tooltip
            title={
              record.entity_id
                ? undefined
                : t("aidpKnowledge.ontologyEntityMissingIdAction")
            }
          >
            <Button
              type="link"
              size="small"
              disabled={!canManage || !record.entity_id}
              onClick={() => handleDelete(record)}
            >
              {t("aidpKnowledge.ontologyDelete")}
            </Button>
          </Tooltip>
        </div>
      ),
    },
  ];

  const columnKeys = columns.map((column) => String(column.key));
  const { tableContainer, columnWidths, totalWidth, handleResize } =
    useAidpOntologyColumnWidths(columnKeys, {
      display_name: 1.3,
      kind: 1.3,
      description: 1.8,
      extended: 1.1,
      parents: 1,
      synonyms: 1,
      children: 1,
      create_time: 1.7,
      actions: 1.3,
    });
  const resizableColumns = columns.map((column, index) => {
    const key = columnKeys[index];
    const nextKey = columnKeys[index + 1];
    return {
      ...column,
      width: columnWidths[key],
      onHeaderCell: () =>
        ({
          width: columnWidths[key],
          maxWidth: nextKey
            ? columnWidths[key] + columnWidths[nextKey] - AIDP_MIN_COLUMN_WIDTH
            : undefined,
          "data-column-key": key,
          onResize: nextKey
            ? (delta: number, rendered: Record<string, number>) =>
                handleResize(key, nextKey, delta, rendered)
            : undefined,
        }) as AidpResizableTitleProps,
    };
  });

  const renderBody = () => {
    if (query.isLoading) {
      return (
        <div className={styles.stateBlock}>
          <Skeleton active title={false} paragraph={{ rows: 5 }} />
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
    if (entities.length === 0) {
      return (
        <Empty
          className={styles.emptyState}
          description={
            appliedKeyword
              ? t("aidpKnowledge.ontologyEntitySearchEmpty")
              : t("aidpKnowledge.ontologyEntityEmpty")
          }
        >
          {!appliedKeyword && canManage && (
            <Button
              type="primary"
              onClick={() => {
                setEditing(null);
                setDrawerOpen(true);
              }}
            >
              {t("aidpKnowledge.ontologyEntityCreateAction")}
            </Button>
          )}
        </Empty>
      );
    }
    return (
      <div className={styles.tableArea} ref={tableContainer}>
        <Table<AidpOntologyEntity>
          rowKey={(record) =>
            record.entity_id ?? `${record.api_name}-${record.kind}`
          }
          size="middle"
          className={styles.table}
          columns={resizableColumns}
          dataSource={entities}
          pagination={false}
          tableLayout="fixed"
          components={{ header: { cell: AidpResizableTitle } }}
          scroll={{ x: totalWidth }}
          rowSelection={
            canManage
              ? {
                  selectedRowKeys: selectedKeys,
                  onChange: setSelectedKeys,
                  getCheckboxProps: (record) => ({
                    disabled: !record.entity_id,
                  }),
                }
              : undefined
          }
        />
      </div>
    );
  };

  return (
    <div className={styles.tab}>
      <div className={styles.toolbar}>
        <Input
          allowClear
          className={styles.searchInput}
          placeholder={t("aidpKnowledge.ontologyEntitySearchPlaceholder")}
          prefix={<SearchOutlined />}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
        />
        <div className={styles.toolbarActions}>
          <Button
            type="text"
            aria-label={t("aidpKnowledge.refresh")}
            icon={<ReloadOutlined spin={query.isFetching} />}
            onClick={refresh}
          />
          <Button
            disabled={!canManage || selectedKeys.length === 0}
            onClick={handleBatchDelete}
          >
            {t("aidpKnowledge.ontologyDelete")}
          </Button>
          <Button
            type="primary"
            disabled={!canManage}
            onClick={() => {
              setEditing(null);
              setDrawerOpen(true);
            }}
          >
            {t("aidpKnowledge.ontologyEntityCreateAction")}
          </Button>
          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                {
                  key: "kind",
                  label: (
                    <Checkbox
                      checked={visibleColumns.kind}
                      onChange={(event) =>
                        setVisibleColumns((previous) => ({
                          ...previous,
                          kind: event.target.checked,
                        }))
                      }
                    >
                      {t("aidpKnowledge.ontologyEntityObjectKind")}
                    </Checkbox>
                  ),
                },
                {
                  key: "description",
                  label: (
                    <Checkbox
                      checked={visibleColumns.description}
                      onChange={(event) =>
                        setVisibleColumns((previous) => ({
                          ...previous,
                          description: event.target.checked,
                        }))
                      }
                    >
                      {t("aidpKnowledge.ontologyEntityColumnDescription")}
                    </Checkbox>
                  ),
                },
                {
                  key: "extended",
                  label: (
                    <Checkbox
                      checked={visibleColumns.extended}
                      onChange={(event) =>
                        setVisibleColumns((previous) => ({
                          ...previous,
                          extended: event.target.checked,
                        }))
                      }
                    >
                      {t("aidpKnowledge.ontologyEntityExtended")}
                    </Checkbox>
                  ),
                },
                {
                  key: "parent",
                  label: (
                    <Checkbox
                      checked={visibleColumns.parent}
                      onChange={(event) =>
                        setVisibleColumns((previous) => ({
                          ...previous,
                          parent: event.target.checked,
                        }))
                      }
                    >
                      {t("aidpKnowledge.ontologyEntityParent")}
                    </Checkbox>
                  ),
                },
                {
                  key: "synonym",
                  label: (
                    <Checkbox
                      checked={visibleColumns.synonym}
                      onChange={(event) =>
                        setVisibleColumns((previous) => ({
                          ...previous,
                          synonym: event.target.checked,
                        }))
                      }
                    >
                      {t("aidpKnowledge.ontologyEntitySynonym")}
                    </Checkbox>
                  ),
                },
                {
                  key: "child",
                  label: (
                    <Checkbox
                      checked={visibleColumns.child}
                      onChange={(event) =>
                        setVisibleColumns((previous) => ({
                          ...previous,
                          child: event.target.checked,
                        }))
                      }
                    >
                      {t("aidpKnowledge.ontologyEntityChild")}
                    </Checkbox>
                  ),
                },
                {
                  key: "createTime",
                  label: (
                    <Checkbox
                      checked={visibleColumns.createTime}
                      onChange={(event) =>
                        setVisibleColumns((previous) => ({
                          ...previous,
                          createTime: event.target.checked,
                        }))
                      }
                    >
                      {t("aidpKnowledge.ontologyMetadataColumnCreateTime")}
                    </Checkbox>
                  ),
                },
              ],
            }}
          >
            <Tooltip title={t("aidpKnowledge.ontologyMetadataColumnSettings")}>
              <Button
                aria-label={t("aidpKnowledge.ontologyMetadataColumnSettings")}
                icon={<SettingOutlined />}
              />
            </Tooltip>
          </Dropdown>
        </div>
      </div>
      {query.isError && entities.length > 0 && (
        <div className={styles.inlineError} role="alert">
          {errorMessage}
        </div>
      )}
      {renderBody()}
      {entities.length > 0 && (
        <div className={styles.paginationRow}>
          <AidpPagination
            currentPage={page}
            pageSize={pageSize}
            pageSizeOptions={[10, 20, 50, 100]}
            total={total}
            totalReliable={totalReliable}
            hasMore={hasMore}
            selectionHint={
              selectedKeys.length
                ? t("aidpKnowledge.selectedCount", {
                    count: selectedKeys.length,
                  })
                : undefined
            }
            onPageChange={setPage}
            onPageSizeChange={(nextSize) => {
              setPageSize(nextSize);
              setPage(1);
            }}
          />
        </div>
      )}
      {canManage && (
        <AidpOntologyEntityDrawer
          open={drawerOpen}
          domainId={domainId}
          entity={editing}
          onClose={() => setDrawerOpen(false)}
          onSaved={() => {
            setDrawerOpen(false);
            refresh();
          }}
        />
      )}
      <AidpOntologyEntityDetailDrawer
        open={!!detailEntity}
        entity={detailEntity}
        onClose={() => setDetailEntity(null)}
        onEdit={(record) => {
          setDetailEntity(null);
          setEditing(record);
          setDrawerOpen(true);
        }}
        onDelete={(record) => {
          setDetailEntity(null);
          handleDelete(record);
        }}
      />
    </div>
  );
};

export default AidpOntologyEntityTab;
