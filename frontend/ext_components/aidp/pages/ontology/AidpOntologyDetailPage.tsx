// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, ConfigProvider, Dropdown, Skeleton, Tabs } from "antd";
import {
  ApartmentOutlined,
  ArrowLeftOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  EditOutlined,
  EllipsisOutlined,
  FileTextOutlined,
  LinkOutlined,
  TeamOutlined,
} from "@ant-design/icons";

import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { useAidpOntologyDemoMode } from "@/ext_components/aidp/shared/hooks/useAidpOntologyDemoMode";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import { aidpKnowledgeVisualTheme } from "@/ext_components/aidp/shared/styles/aidpKnowledgeVisualTheme";
import typography from "@/ext_components/aidp/shared/styles/aidpKnowledgeTypography.module.css";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type { AidpOntologyDomain } from "@/ext_components/aidp/shared/types/ontology";
import AidpOntologyDomainDrawer from "./components/AidpOntologyDomainDrawer";
import AidpOntologyEntityTab from "./components/AidpOntologyEntityTab";
import AidpOntologyBindingsTab from "./components/AidpOntologyBindingsTab";
import AidpOntologyMetadataTab from "./components/AidpOntologyMetadataTab";
import AidpOntologyImportDrawer from "./components/AidpOntologyImportDrawer";
import AidpOntologyExportModal from "./components/AidpOntologyExportModal";
import AidpOntologyDeleteModal from "./components/AidpOntologyDeleteModal";
import AidpOntologyRulesTab from "./components/AidpOntologyRulesTab";
import AidpOntologyTasksTab from "./components/AidpOntologyTasksTab";
import styles from "./AidpOntologyDetailPage.module.css";

type DetailTab = "metadata" | "entities" | "rules" | "bindings" | "tasks";

/** Format an AIDP audit value with minutes without inventing a timestamp. */
const formatDisplayDateTime = (value?: string | number | null): string => {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number" && Number.isFinite(value)) {
    const milliseconds = value < 1_000_000_000_000 ? value * 1000 : value;
    const date = new Date(milliseconds);
    return Number.isNaN(date.getTime())
      ? String(value)
      : date.toISOString().slice(0, 16).replace("T", " ");
  }
  const text = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(text)) {
    return text.slice(0, 16).replace("T", " ");
  }
  return text || "—";
};

type DetailCreateAction = "entity" | "metadata";

interface AidpOntologyDetailPageProps {
  domainId: string;
  createAction?: DetailCreateAction;
}

const AidpOntologyDetailPage: React.FC<AidpOntologyDetailPageProps> = ({
  domainId,
  createAction,
}) => {
  const { t } = useTranslation();
  const params = useParams();
  const router = useRouter();
  const locale = (params?.locale as string) || "zh";
  const queryClient = useQueryClient();
  const scope = useAidpQueryScope();
  const demo = useAidpOntologyDemoMode();
  const [activeTab, setActiveTab] = useState<DetailTab>(
    createAction === "entity" ? "entities" : "metadata"
  );
  const [pendingCreate, setPendingCreate] = useState<DetailCreateAction | null>(
    createAction ?? null
  );
  const [editOpen, setEditOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const queryKey = useMemo(
    () => [...scope.key, "ontology-domain", domainId],
    [domainId, scope.key]
  );
  const query = useQuery({
    queryKey,
    queryFn: () => aidpOntologyService.getDomain(domainId),
    enabled: scope.enabled && !!domainId,
    staleTime: 30_000,
    retry: false,
  });
  const ruleCountQuery = useQuery({
    queryKey: [...scope.key, "ontology-rule-count", domainId],
    queryFn: () => aidpOntologyService.countRules(domainId),
    enabled: scope.enabled && !!domainId,
    staleTime: 30_000,
    retry: false,
  });

  const refreshDetail = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey });
  }, [queryClient, queryKey]);

  const refreshEntities = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "ontology-entities", domainId],
    });
    refreshDetail();
  }, [domainId, queryClient, refreshDetail, scope.key]);

  const refreshBindings = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "ontology-bindings", domainId],
    });
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "ontology-entities", domainId],
    });
    refreshDetail();
  }, [domainId, queryClient, refreshDetail, scope.key]);

  const domain: AidpOntologyDomain | undefined = query.data;

  useEffect(() => {
    // Wait for the domain payload: the tab body (and therefore the target
    // drawer) is not mounted until the query resolves, so clearing the intent
    // any earlier would lose the quick action.
    if (!pendingCreate || !domain) return;
    const timer = window.setTimeout(() => setPendingCreate(null), 0);
    return () => window.clearTimeout(timer);
  }, [domain, pendingCreate]);

  const errorMessage = query.error
    ? getAidpErrorMessage(
        query.error,
        t,
        t("aidpKnowledge.ontologyDetailLoadFailed")
      )
    : undefined;

  return (
    <ConfigProvider theme={aidpKnowledgeVisualTheme}>
      <div
        className={`${typography.page} ${styles.page} flex h-full min-h-0 w-full flex-col overflow-y-auto`}
      >
        {query.isLoading && <Skeleton active paragraph={{ rows: 2 }} />}
        {query.isError && (
          <Alert
            type="error"
            showIcon
            className={styles.errorAlert}
            title={errorMessage}
            action={
              <Button size="small" onClick={() => void query.refetch()}>
                {t("aidpKnowledge.retry")}
              </Button>
            }
          />
        )}
        {domain && (
          <>
            <header className={styles.hero}>
              <div className={styles.heroTop}>
                <span className={styles.heroIcon} aria-hidden="true">
                  <ApartmentOutlined />
                </span>
                <div className={styles.heroText}>
                  <div className={styles.titleRow}>
                    <Link
                      href={`/${locale}/knowledges/ontology`}
                      className={styles.backButton}
                      aria-label={t("aidpKnowledge.ontologyBackToList")}
                    >
                      <ArrowLeftOutlined />
                    </Link>
                    <h1 className={typography.pageTitle}>{domain.name}</h1>
                    <Button
                      type="text"
                      size="small"
                      className={styles.titleEdit}
                      aria-label={t("aidpKnowledge.ontologyEdit")}
                      icon={<EditOutlined />}
                      onClick={() => setEditOpen(true)}
                    />
                  </div>
                  <div className={styles.descriptionRow}>
                    <p className={styles.description}>
                      {domain.description || "—"}
                    </p>
                    <Button
                      type="text"
                      size="small"
                      className={styles.titleEdit}
                      aria-label={t("aidpKnowledge.ontologyEdit")}
                      icon={<EditOutlined />}
                      onClick={() => setEditOpen(true)}
                    />
                  </div>
                </div>
                <div className={styles.heroActions}>
                  <Button onClick={() => setDeleteOpen(true)}>
                    {t("aidpKnowledge.ontologyDelete")}
                  </Button>
                  <Dropdown
                    trigger={["click"]}
                    menu={{
                      items: [
                        {
                          key: "import",
                          label: t("aidpKnowledge.ontologyImportJson"),
                          onClick: () => setImportOpen(true),
                        },
                        // AIDP's export endpoint answers 500/code1001 in the
                        // confirmed environment; keep it demo-only until fixed.
                        ...(demo
                          ? [
                              {
                                key: "export",
                                label: t("aidpKnowledge.ontologyExportJson"),
                                onClick: () => setExportOpen(true),
                              },
                            ]
                          : []),
                      ],
                    }}
                  >
                    <Button
                      aria-label={t("aidpKnowledge.ontologyMoreActions")}
                      icon={<EllipsisOutlined />}
                    />
                  </Dropdown>
                </div>
              </div>
              <div className={styles.overviewStats}>
                <div className={styles.statItem}>
                  <DatabaseOutlined className={styles.statIcon} />
                  <span className={styles.statText}>
                    <span className={styles.statLabel}>
                      {t("aidpKnowledge.ontologyDomainColumnMetadataCount")}
                    </span>
                    <span className={styles.statValue}>
                      {domain.metadata_count ?? "—"}
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
                      {domain.entity_count ?? "—"}
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
                  <LinkOutlined className={styles.statIcon} />
                  <span className={styles.statText}>
                    <span className={styles.statLabel}>
                      {t("aidpKnowledge.ontologyTabBindings")}
                    </span>
                    <span className={styles.statValue}>
                      {domain.bound_kb_count ?? "—"}
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
                      {formatDisplayDateTime(domain.update_time)}
                    </span>
                  </span>
                </div>
              </div>
              <AidpOntologyGapNote className={styles.overviewNote}>
                {demo
                  ? t("aidpKnowledge.ontologyDetailDemoStatsGap")
                  : t("aidpKnowledge.ontologyDetailRealStatsGap")}
              </AidpOntologyGapNote>
            </header>

            <Tabs
              className={styles.tabs}
              activeKey={activeTab}
              onChange={(key) => setActiveTab(key as DetailTab)}
              items={[
                {
                  key: "metadata",
                  label: t("aidpKnowledge.ontologyTabMetadata"),
                },
                {
                  key: "entities",
                  label: t("aidpKnowledge.ontologyTabEntities"),
                },
                {
                  key: "rules",
                  label: t("aidpKnowledge.ontologyTabRules"),
                },
                {
                  key: "bindings",
                  label: t("aidpKnowledge.ontologyTabBindings"),
                },
                {
                  key: "tasks",
                  label: t("aidpKnowledge.ontologyTabAsyncTasks"),
                },
              ]}
            />

            <section className={styles.contentPanel}>
              {activeTab === "entities" && (
                <AidpOntologyEntityTab
                  domainId={domainId}
                  autoOpenCreate={pendingCreate === "entity"}
                />
              )}
              {activeTab === "metadata" && (
                <AidpOntologyMetadataTab
                  domainId={domainId}
                  autoOpenCreate={pendingCreate === "metadata"}
                />
              )}
              {activeTab === "rules" && (
                <AidpOntologyRulesTab domainId={domainId} />
              )}
              {activeTab === "bindings" && (
                <AidpOntologyBindingsTab
                  domainId={domainId}
                  boundKbCount={domain.bound_kb_count}
                  onChanged={refreshBindings}
                />
              )}
              {activeTab === "tasks" && <AidpOntologyTasksTab />}
            </section>
          </>
        )}

        {domain && (
          <AidpOntologyDomainDrawer
            open={editOpen}
            domain={domain}
            onClose={() => setEditOpen(false)}
            onSaved={() => {
              setEditOpen(false);
              refreshDetail();
              void queryClient.invalidateQueries({
                queryKey: [...scope.key, "ontology-domains"],
              });
            }}
          />
        )}
        <AidpOntologyImportDrawer
          open={importOpen}
          domainId={domainId}
          domainName={domain?.name ?? ""}
          onClose={() => setImportOpen(false)}
          onImported={() => {
            refreshEntities();
          }}
        />
        <AidpOntologyExportModal
          open={exportOpen}
          domainId={domainId}
          domainName={domain?.name ?? ""}
          onClose={() => setExportOpen(false)}
        />
        <AidpOntologyDeleteModal
          open={deleteOpen}
          domain={domain ?? null}
          onClose={() => setDeleteOpen(false)}
          onDeleted={() => {
            setDeleteOpen(false);
            void queryClient.invalidateQueries({
              queryKey: [...scope.key, "ontology-domains"],
            });
            router.push(`/${locale}/knowledges/ontology`);
          }}
        />
      </div>
    </ConfigProvider>
  );
};

export default AidpOntologyDetailPage;
