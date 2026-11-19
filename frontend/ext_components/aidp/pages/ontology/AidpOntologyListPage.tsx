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
  Grid,
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
  DeploymentUnitOutlined,
  DownOutlined,
  FileTextOutlined,
  MoreOutlined,
  ReloadOutlined,
  SearchOutlined,
  TableOutlined,
  UpOutlined,
} from "@ant-design/icons";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { useAidpOntologyDemoMode } from "@/ext_components/aidp/shared/hooks/useAidpOntologyDemoMode";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { aidpKnowledgeVisualTheme } from "@/ext_components/aidp/shared/styles/aidpKnowledgeVisualTheme";
import typography from "@/ext_components/aidp/shared/styles/aidpKnowledgeTypography.module.css";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type { AidpOntologyDomain } from "@/ext_components/aidp/shared/types/ontology";
import AidpOntologyDomainDrawer from "./components/AidpOntologyDomainDrawer";
import AidpOntologyDeleteModal from "./components/AidpOntologyDeleteModal";
import AidpOntologyGuide from "./components/AidpOntologyGuide";
import styles from "./AidpOntologyListPage.module.css";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 10;
const GUIDE_STORAGE_KEY = "aidpOntology.guideExpanded";
const MANAGER_ROLES = new Set(["SU", "ADMIN", "SPEED", "ASSET_OWNER"]);

type ListView = "table" | "cards";

/** Format AIDP audit values without inventing a missing date. */
const formatDisplayDate = (value?: string | number | null): string => {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number" && Number.isFinite(value)) {
    const milliseconds = value < 1_000_000_000_000 ? value * 1000 : value;
    const date = new Date(milliseconds);
    return Number.isNaN(date.getTime())
      ? String(value)
      : date.toISOString().slice(0, 10);
  }
  const text = String(value).trim();
  return /^\d{4}-\d{2}-\d{2}/.test(text) ? text.slice(0, 10) : text || "—";
};

const AidpOntologyListPage: React.FC = () => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const router = useRouter();
  const params = useParams();
  const locale = (params?.locale as string) || "zh";
  const queryClient = useQueryClient();
  const scope = useAidpQueryScope();
  const demo = useAidpOntologyDemoMode();
  const { user } = useAuthorizationContext();
  const canManage = !!user && MANAGER_ROLES.has(user.role);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [viewMode, setViewMode] = useState<ListView>("table");
  const [guideExpanded, setGuideExpanded] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<AidpOntologyDomain | null>(null);
  const [deletingDomain, setDeletingDomain] =
    useState<AidpOntologyDomain | null>(null);
  const screens = Grid.useBreakpoint();
  const isNarrow = screens.md === false;

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

  const submitSearch = () => {
    const next = searchInput.trim();
    if (next === search) return;
    setSearch(next);
    setPage(1);
  };

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
          danger: true,
        },
      ]
    : [];

  const columns: TableColumnsType<AidpOntologyDomain> = [
    {
      title: t("aidpKnowledge.ontologyDomainColumnName"),
      dataIndex: "name",
      key: "name",
      width: 160,
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
    },
    {
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
    },
    {
      title: t("aidpKnowledge.ontologyDomainColumnUpdateTime"),
      dataIndex: "update_time",
      key: "update_time",
      width: 140,
      render: (value: string | number | null | undefined) =>
        formatDisplayDate(value),
    },
  ];

  if (canManage) {
    columns.push({
      title: t("aidpKnowledge.ontologyColumnActions"),
      key: "actions",
      width: 280,
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
            danger
            onClick={() => handleDelete(record)}
          >
            {t("aidpKnowledge.ontologyDelete")}
          </Button>
        </div>
      ),
    });
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
            time: formatDisplayDate(domain.update_time),
          })}
        </span>
        <span className={styles.cardCounts}>
          <Tooltip title={t("aidpKnowledge.ontologyDomainColumnMetadataCount")}>
            <span>
              <FileTextOutlined />
              {domain.metadata_count ?? "—"}
            </span>
          </Tooltip>
          <Tooltip title={t("aidpKnowledge.ontologyDomainColumnEntityCount")}>
            <span>
              <DeploymentUnitOutlined />
              {domain.entity_count ?? "—"}
            </span>
          </Tooltip>
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
      <Table<AidpOntologyDomain>
        rowKey="domain_id"
        size="middle"
        className={styles.table}
        columns={columns}
        dataSource={domains}
        pagination={false}
        tableLayout="fixed"
        scroll={{
          x: canManage ? (isNarrow ? 720 : 860) : isNarrow ? 600 : 700,
        }}
      />
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
          <AidpOntologyGapNote>
            {demo
              ? t("aidpKnowledge.ontologyListDemoUpdateTimeGap")
              : t("aidpKnowledge.ontologyListRealUpdateTimeGap")}
          </AidpOntologyGapNote>
          <div className={styles.toolbar}>
            <Input
              allowClear
              className={styles.toolbarSearch}
              placeholder={t("aidpKnowledge.ontologyDomainSearchPlaceholder")}
              prefix={<SearchOutlined />}
              value={searchInput}
              onChange={(event) => {
                setSearchInput(event.target.value);
                if (!event.target.value) {
                  setSearch("");
                  setPage(1);
                }
              }}
              onPressEnter={submitSearch}
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
                onChange={(value) => setViewMode(value as ListView)}
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
          <div className={styles.tableArea}>{renderBody()}</div>
          {domains.length > 0 && (
            <div className={styles.paginationRow}>
              <AidpPagination
                currentPage={page}
                pageSize={pageSize}
                pageSizeOptions={PAGE_SIZE_OPTIONS}
                total={total}
                totalReliable={totalReliable}
                hasMore={hasMore}
                selectedCount={0}
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
          onDeleted={(domain) => {
            setDeletingDomain(null);
            message.success(t("aidpKnowledge.ontologyDomainDeleted"));
            setPage(1);
            refresh();
            void domain;
          }}
        />
      </div>
    </ConfigProvider>
  );
};

export default AidpOntologyListPage;
