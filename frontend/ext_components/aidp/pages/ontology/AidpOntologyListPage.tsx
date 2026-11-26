// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  ConfigProvider,
  Dropdown,
  Empty,
  Input,
  Segmented,
  Skeleton,
  Table,
  Tooltip,
  type MenuProps,
  type TableColumnsType,
} from "antd";
import {
  ApartmentOutlined,
  AppstoreOutlined,
  ClockCircleOutlined,
  DownOutlined,
  MoreOutlined,
  ReloadOutlined,
  SearchOutlined,
  TableOutlined,
  UpOutlined,
} from "@ant-design/icons";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { formatAidpDate } from "@/ext_components/aidp/shared/utils/aidpTime";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { AIDP_ONTOLOGY_MANAGER_ROLES } from "@/ext_components/aidp/shared/utils/aidpOntologyRoles";
import { aidpKnowledgeVisualTheme } from "@/ext_components/aidp/shared/styles/aidpKnowledgeVisualTheme";
import typography from "@/ext_components/aidp/shared/styles/aidpKnowledgeTypography.module.css";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import AidpResizableTitle, {
  type AidpResizableTitleProps,
} from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";
import { AIDP_MIN_COLUMN_WIDTH } from "@/ext_components/aidp/pages/knowledge-list/utils/aidpKnowledgeColumnWidths";
import { useAidpOntologyColumnWidths } from "@/ext_components/aidp/shared/hooks/useAidpOntologyColumnWidths";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type { AidpOntologyDomain } from "@/ext_components/aidp/shared/types/ontology";
import AidpOntologyDomainDrawer from "./components/common/AidpOntologyDomainDrawer";
import AidpOntologyDeleteModal from "./components/common/AidpOntologyDeleteModal";
import AidpOntologyGuide from "./components/common/AidpOntologyGuide";
import styles from "./AidpOntologyListPage.module.css";
import tableStyles from "@/ext_components/aidp/shared/styles/AidpOntologyTable.module.css";

const PAGE_SIZE_OPTIONS = [12, 24, 48] as const;
const DEFAULT_PAGE_SIZE = 12;
const GUIDE_STORAGE_KEY = "aidpOntology.guideExpanded";
const VIEW_MODE_STORAGE_KEY = "aidpOntology.viewMode";

type ListView = "table" | "cards";
type ColumnKey = "name" | "description" | "update_time" | "actions";

const BASE_COLUMN_WEIGHTS: Record<ColumnKey, number> = {
  name: 2,
  description: 4,
  update_time: 1.6,
  actions: 3,
};

const AidpOntologyListPage: React.FC = () => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const router = useRouter();
  const params = useParams();
  const locale = (params?.locale as string) || "zh";
  const queryClient = useQueryClient();
  const scope = useAidpQueryScope();
  const { user } = useAuthorizationContext();
  const canManage = !!user && AIDP_ONTOLOGY_MANAGER_ROLES.has(user.role);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [viewMode, setViewMode] = useState<ListView>(() => {
    try {
      const saved = window.sessionStorage.getItem(VIEW_MODE_STORAGE_KEY);
      if (saved === "table" || saved === "cards") return saved;
    } catch {
      // Fall through to the card default when storage is unavailable.
    }
    return "cards";
  });
  const [guideExpanded, setGuideExpanded] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<AidpOntologyDomain | null>(null);
  const [deletingDomain, setDeletingDomain] =
    useState<AidpOntologyDomain | null>(null);

  const activeColumnKeys = useMemo<ColumnKey[]>(
    () =>
      canManage
        ? ["name", "description", "update_time", "actions"]
        : ["name", "description", "update_time"],
    [canManage]
  );
  const {
    tableContainer,
    columnWidths,
    totalWidth: totalTableWidth,
    handleResize,
  } = useAidpOntologyColumnWidths(activeColumnKeys, BASE_COLUMN_WEIGHTS);
  const changeViewMode = (value: ListView) => {
    setViewMode(value);
    try {
      window.sessionStorage.setItem(VIEW_MODE_STORAGE_KEY, value);
    } catch {
      // Keep the choice in memory when storage is unavailable.
    }
  };

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      try {
        if (window.sessionStorage.getItem(GUIDE_STORAGE_KEY) === "false") {
          setGuideExpanded(false);
        }
      } catch {
        // Keep the tutorial expanded when browser storage is unavailable.
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  const toggleGuide = () => {
    const next = !guideExpanded;
    setGuideExpanded(next);
    try {
      window.sessionStorage.setItem(GUIDE_STORAGE_KEY, String(next));
    } catch {
      // Keep the change in memory when browser storage is unavailable.
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = searchInput.trim();
      setSearch((current) => (current === next ? current : next));
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const queryKey = useMemo(
    () => [...scope.key, "ontology-domains", { page, pageSize, search }],
    [page, pageSize, scope.key, search]
  );

  const query = useQuery({
    queryKey,
    queryFn: () =>
      aidpOntologyService.listDomains(page, pageSize, search || undefined),
    enabled: scope.enabled,
    staleTime: 30_000,
    retry: false,
  });

  const domains = query.data?.value ?? [];
  const total = query.data?.total_count ?? domains.length;
  const totalReliable = query.data?.total_reliable !== false;
  const hasMore = query.data?.has_more ?? false;
  const errorMessage = query.error
    ? getAidpErrorMessage(
        query.error,
        t,
        t("aidpKnowledge.ontologyListLoadFailed")
      )
    : undefined;

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "ontology-domains"],
    });
  }, [queryClient, scope.key]);

  const domainPath = useCallback(
    (record: AidpOntologyDomain, action?: "entity" | "metadata") =>
      `/${locale}/knowledges/ontology/${encodeURIComponent(record.domain_id)}${
        action ? `?create=${action}` : ""
      }`,
    [locale]
  );

  const openDetail = useCallback(
    (record: AidpOntologyDomain) => router.push(domainPath(record)),
    [domainPath, router]
  );

  const openCreateEntity = useCallback(
    (record: AidpOntologyDomain) => router.push(domainPath(record, "entity")),
    [domainPath, router]
  );

  const openCreateMetadata = useCallback(
    (record: AidpOntologyDomain) => router.push(domainPath(record, "metadata")),
    [domainPath, router]
  );

  const openCreate = () => {
    if (!canManage) return;
    router.push(`/${locale}/knowledges/ontology/create`);
  };

  const openEdit = (domain: AidpOntologyDomain) => {
    if (!canManage) return;
    setEditing(domain);
    setDrawerOpen(true);
  };

  const handleDelete = (domain: AidpOntologyDomain) => {
    if (!canManage) return;
    setDeletingDomain(domain);
  };

  const handleQuickAction = (domain: AidpOntologyDomain, key: string): void => {
    if (key === "edit") openEdit(domain);
    else if (key === "create-entity") openCreateEntity(domain);
    else if (key === "create-metadata") openCreateMetadata(domain);
    else if (key === "delete") handleDelete(domain);
  };

  const cardMenuItems: MenuProps["items"] = canManage
    ? [
        { key: "edit", label: t("aidpKnowledge.ontologyEdit") },
        {
          key: "create-metadata",
          label: t("aidpKnowledge.ontologyCreateMetadata"),
        },
        {
          key: "create-entity",
          label: t("aidpKnowledge.ontologyEntityCreate"),
        },
        { type: "divider" },
        {
          key: "delete",
          label: t("aidpKnowledge.ontologyDelete"),
        },
      ]
    : [];

  const makeColumn = (
    key: ColumnKey,
    column: TableColumnsType<AidpOntologyDomain>[number]
  ): TableColumnsType<AidpOntologyDomain>[number] => {
    const nextKey = activeColumnKeys[activeColumnKeys.indexOf(key) + 1];
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
            ? (delta: number, renderedWidths: Record<string, number>) =>
                handleResize(key, nextKey, delta, renderedWidths)
            : undefined,
        }) as AidpResizableTitleProps,
    };
  };

  const columns: TableColumnsType<AidpOntologyDomain> = [
    makeColumn("name", {
      title: t("aidpKnowledge.ontologyDomainColumnName"),
      dataIndex: "name",
      key: "name",
      render: (name: string, record) => (
        <Tooltip title={name} placement="topLeft">
          <button
            type="button"
            className={styles.nameLink}
            onClick={() => openDetail(record)}
          >
            {name}
          </button>
        </Tooltip>
      ),
    }),
    makeColumn("description", {
      title: t("aidpKnowledge.ontologyDomainColumnDescription"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
      responsive: ["md"],
      render: (description: string) => (
        <Tooltip title={description || undefined} placement="topLeft">
          <span className={styles.ellipsis}>{description || "—"}</span>
        </Tooltip>
      ),
    }),
    makeColumn("update_time", {
      title: t("aidpKnowledge.ontologyDomainColumnUpdateTime"),
      dataIndex: "update_time",
      key: "update_time",
      render: (value: string | number | null | undefined) =>
        formatAidpDate(value),
    }),
  ];

  if (canManage) {
    columns.push(
      makeColumn("actions", {
        title: t("aidpKnowledge.ontologyColumnActions"),
        key: "actions",
        render: (_value, record) => (
          <div className={styles.rowActions}>
            <Button
              type="link"
              size="small"
              onClick={() => openCreateEntity(record)}
            >
              {t("aidpKnowledge.ontologyEntityCreate")}
            </Button>
            <Button
              type="link"
              size="small"
              onClick={() => openCreateMetadata(record)}
            >
              {t("aidpKnowledge.ontologyCreateMetadata")}
            </Button>
            <Button type="link" size="small" onClick={() => openEdit(record)}>
              {t("aidpKnowledge.ontologyEdit")}
            </Button>
            <Button
              type="link"
              size="small"
              onClick={() => handleDelete(record)}
            >
              {t("aidpKnowledge.ontologyDelete")}
            </Button>
          </div>
        ),
      })
    );
  }

  const renderCard = (domain: AidpOntologyDomain) => (
    <article
      key={domain.domain_id}
      className={styles.card}
      role="link"
      tabIndex={0}
      onClick={() => openDetail(domain)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openDetail(domain);
        }
      }}
    >
      <div className={styles.cardHeader}>
        <span className={styles.cardIcon} aria-hidden="true">
          <ApartmentOutlined />
        </span>
        <span className={styles.cardTitle} title={domain.name}>
          {domain.name}
        </span>
        {canManage && cardMenuItems.length > 0 && (
          <Dropdown
            trigger={["click"]}
            menu={{
              items: cardMenuItems,
              onClick: ({ key, domEvent }) => {
                domEvent.stopPropagation();
                handleQuickAction(domain, key);
              },
            }}
          >
            <Button
              type="text"
              size="small"
              className={styles.cardMore}
              aria-label={t("aidpKnowledge.ontologyMoreActions")}
              icon={<MoreOutlined />}
              onClick={(event) => event.stopPropagation()}
            />
          </Dropdown>
        )}
      </div>
      <p
        className={styles.cardDescription}
        title={domain.description || undefined}
      >
        {domain.description || "—"}
      </p>
      <div className={styles.cardFooter}>
        <span className={styles.cardUpdated}>
          <ClockCircleOutlined />
          {t("aidpKnowledge.ontologyCardUpdatedAt", {
            time: formatAidpDate(domain.update_time),
          })}
        </span>
      </div>
    </article>
  );

  const renderBody = () => {
    if (query.isLoading) {
      return (
        <div className={styles.stateBlock}>
          <Skeleton active title={false} paragraph={{ rows: 6 }} />
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
    if (domains.length === 0) {
      return (
        <Empty
          className={styles.emptyState}
          image={Empty.PRESENTED_IMAGE_DEFAULT}
          description={
            search
              ? t("aidpKnowledge.ontologySearchEmpty")
              : t("aidpKnowledge.ontologyListEmpty")
          }
        >
          {!search && canManage && (
            <Button type="primary" onClick={openCreate}>
              {t("aidpKnowledge.ontologyCreateDomain")}
            </Button>
          )}
        </Empty>
      );
    }
    if (viewMode === "cards") {
      return <div className={styles.cardGrid}>{domains.map(renderCard)}</div>;
    }
    return (
      <div className={tableStyles.tableArea} ref={tableContainer}>
        <Table<AidpOntologyDomain>
          rowKey="domain_id"
          size="middle"
          className={tableStyles.table}
          columns={columns}
          dataSource={domains}
          pagination={false}
          tableLayout="fixed"
          components={{
            header: { cell: AidpResizableTitle },
          }}
          scroll={{ x: totalTableWidth }}
        />
      </div>
    );
  };

  return (
    <ConfigProvider theme={aidpKnowledgeVisualTheme}>
      <div
        className={`${typography.page} ${styles.page} flex h-full min-h-0 w-full flex-col gap-4 overflow-y-auto`}
      >
        <div className={styles.headerRow}>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className={typography.pageTitle}>
              {t("aidpKnowledge.ontologyTitle")}
            </h1>
          </div>
          <Button
            type="link"
            size="small"
            className={styles.guideToggle}
            icon={guideExpanded ? <UpOutlined /> : <DownOutlined />}
            iconPlacement="end"
            onClick={toggleGuide}
            aria-expanded={guideExpanded}
          >
            {guideExpanded
              ? t("aidpKnowledge.guideCollapse")
              : t("aidpKnowledge.ontologyGuideExpand")}
          </Button>
        </div>
        {guideExpanded && <AidpOntologyGuide />}
        <section
          className={`${styles.panel} flex min-h-[320px] flex-1 flex-col`}
        >
          {query.isError && domains.length > 0 && (
            <div className={styles.inlineError} role="alert">
              {errorMessage}
            </div>
          )}
          <div className={styles.toolbar}>
            <Input
              allowClear
              className={styles.toolbarSearch}
              placeholder={t("aidpKnowledge.ontologyDomainSearchPlaceholder")}
              prefix={<SearchOutlined />}
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
            <div className={styles.toolbarActions}>
              <Button
                type="text"
                aria-label={t("aidpKnowledge.refresh")}
                icon={<ReloadOutlined spin={query.isFetching} />}
                onClick={refresh}
              />
              {canManage && (
                <Button type="primary" onClick={openCreate}>
                  {t("aidpKnowledge.ontologyCreateDomain")}
                </Button>
              )}
              <Segmented
                value={viewMode}
                onChange={(value) => changeViewMode(value as ListView)}
                options={[
                  {
                    value: "table",
                    title: t("aidpKnowledge.viewTable"),
                    label: <TableOutlined />,
                  },
                  {
                    value: "cards",
                    title: t("aidpKnowledge.viewCards"),
                    label: <AppstoreOutlined />,
                  },
                ]}
              />
            </div>
          </div>
          <div className={tableStyles.tableArea}>{renderBody()}</div>
          {domains.length > 0 && (
            <div className={styles.paginationRow}>
              <AidpPagination
                currentPage={page}
                pageSize={pageSize}
                pageSizeOptions={PAGE_SIZE_OPTIONS}
                total={total}
                totalReliable={totalReliable}
                hasMore={hasMore}
                onPageChange={setPage}
                onPageSizeChange={(nextSize) => {
                  setPageSize(nextSize);
                  setPage(1);
                }}
              />
            </div>
          )}
        </section>

        <AidpOntologyDomainDrawer
          open={drawerOpen && !!editing}
          domain={editing}
          onClose={() => setDrawerOpen(false)}
          onSaved={() => {
            setDrawerOpen(false);
            setEditing(null);
            refresh();
          }}
        />
        <AidpOntologyDeleteModal
          open={!!deletingDomain}
          domain={deletingDomain}
          onClose={() => setDeletingDomain(null)}
          onDeleted={() => {
            setDeletingDomain(null);
            message.success(t("aidpKnowledge.ontologyDomainDeleted"));
            setPage(1);
            refresh();
          }}
        />
      </div>
    </ConfigProvider>
  );
};

export default AidpOntologyListPage;
