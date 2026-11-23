// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { UserIdentity } from "@/components/auth/UserIdentity";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Alert, Breadcrumb, Button, Tabs, Tooltip } from "antd";
import {
  ClockCircleOutlined,
  DatabaseOutlined,
  EditOutlined,
  FileTextOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/ext_components/aidp/shared/types/knowledge";
import type { AidpKbDetail } from "@/ext_components/aidp/shared/types/management";
import {
  AIDP_UNKNOWN_VALUE,
  formatAidpCreator,
  formatAidpDocumentCount,
} from "@/ext_components/aidp/shared/utils/aidpKnowledgeDisplay";
import { useAidpGroupOptions } from "@/ext_components/aidp/shared/hooks/useAidpGroupOptions";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { usePermission } from "@/hooks/permission/usePermission";
import { useAidpKnowledgeDetail } from "./hooks/useAidpKnowledgeDetail";
import AidpUpdateKbModal from "@/ext_components/aidp/pages/knowledge-files/AidpUpdateKbModal";
import AidpGroupNamesDisplay from "@/ext_components/aidp/shared/components/AidpGroupNamesDisplay";
import { AidpDetailField } from "@/ext_components/aidp/pages/knowledge-files/AidpKnowledgeDetailInformation";
import AidpKnowledgeTasksTab from "@/ext_components/aidp/pages/knowledge-files/AidpKnowledgeTasksTab";
import AidpKnowledgeInformationTab from "@/ext_components/aidp/pages/knowledge-files/AidpKnowledgeInformationTab";
import AidpKnowledgeOntologyTab from "./components/AidpKnowledgeOntologyTab";
import AidpSensitiveWordsPage from "@/ext_components/aidp/pages/sensitive-words/AidpSensitiveWordsPage";
import AidpKnowledgeFilesPanel from "@/ext_components/aidp/pages/knowledge-files/components/AidpKnowledgeFilesPanel";
import { formatDetailDateTime } from "@/ext_components/aidp/pages/knowledge-files/utils/aidpKnowledgeDetailUtils";

interface AidpKnowledgeFilesPageProps {
  knowledgeBase: AidpKnowledgeBaseItem;
  onBack: () => void;
  onDelete: (knowledgeBase: AidpKnowledgeBaseItem) => void;
  onUpdated: (knowledgeBase: AidpKnowledgeBaseItem) => void;
  pollingPaused?: boolean;
  initialTab?: DetailTab;
}

type DetailTab =
  "files" | "tasks" | "information" | "ontology" | "sensitive-words";

const UNKNOWN = AIDP_UNKNOWN_VALUE;

const AidpKnowledgeFilesPage: React.FC<AidpKnowledgeFilesPageProps> = ({
  knowledgeBase,
  onBack,
  onDelete,
  onUpdated,
  pollingPaused = false,
  initialTab = "files",
}) => {
  const { t } = useTranslation();
  const {
    groupOptions,
    canReadGroups,
    canConfigureGroupPermissions,
    groupsError,
  } = useAidpGroupOptions();
  const { can } = usePermission();
  const detailQuery = useAidpKnowledgeDetail(knowledgeBase.kds_id);
  const detail = useMemo<AidpKbDetail>(
    () => ({ ...knowledgeBase, ...detailQuery.data }),
    [knowledgeBase, detailQuery.data]
  );
  const [activeTab, setActiveTab] = useState<DetailTab>(initialTab);
  const [editingKbMode, setEditingKbMode] = useState<
    "metadata" | "permissions" | null
  >(null);

  const groupNames = useMemo(() => {
    const names = new Map(
      groupOptions.map((option) => [option.value, option.label])
    );
    return (detail.group_ids || []).map((id) => names.get(id) || UNKNOWN);
  }, [detail.group_ids, groupOptions]);
  const canEdit = detail.permission === "EDIT";
  const canDeleteKb = canEdit && can("kb:delete");
  const isAvailable =
    detail.resource_status !== "UNAVAILABLE" &&
    detail.resource_status !== "ORPHANED";
  const privateScope = detail.ingroup_permission === "PRIVATE";

  return (
    <div className="flex h-full min-h-0 w-full flex-col gap-3 overflow-y-auto pb-4">
      <Breadcrumb
        className="shrink-0"
        items={[
          {
            title: (
              <button
                type="button"
                onClick={onBack}
                className="!text-lg !leading-7 text-gray-500 hover:text-blue-600"
              >
                {t("aidpKnowledge.breadcrumbKnowledgeBase")}
              </button>
            ),
          },
          {
            title: (
              <span className="!text-lg !font-semibold !leading-7 text-gray-800">
                {t("aidpKnowledge.detailBreadcrumb")}
              </span>
            ),
          },
        ]}
      />

      <section className="@container shrink-0 rounded-xl border border-violet-100 bg-gradient-to-r from-violet-50 via-white to-blue-50 px-6 py-3">
        <div className="flex items-start gap-4">
          <span className="flex h-24 w-24 shrink-0 items-center justify-center rounded-xl bg-violet-100 text-6xl text-violet-600">
            <DatabaseOutlined />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-4 gap-y-2">
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2">
                  <Tooltip title={detail.kds_name}>
                    <h1 className="truncate text-lg font-semibold text-gray-800">
                      {detail.kds_name}
                    </h1>
                  </Tooltip>
                  {canEdit && (
                    <Tooltip
                      title={t("aidpKnowledge.detailEditNameDescription")}
                    >
                      <Button
                        type="text"
                        size="small"
                        icon={<EditOutlined />}
                        onClick={() => setEditingKbMode("metadata")}
                      />
                    </Tooltip>
                  )}
                </div>
                <Tooltip
                  title={detail.description}
                  styles={{ root: { maxWidth: 480 } }}
                >
                  <p className="mt-1 truncate text-sm leading-6 text-gray-600">
                    {detail.description || t("aidpKnowledge.noDescription")}
                  </p>
                </Tooltip>
              </div>
              {canDeleteKb && (
                <Button onClick={() => onDelete(detail)}>
                  {t("common.delete")}
                </Button>
              )}
            </div>
            <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 @min-[600px]:grid-cols-2 @min-[900px]:grid-cols-3 @min-[1200px]:grid-cols-5">
              <div className="flex min-w-0 items-center gap-3">
                <FileTextOutlined className="rounded-lg bg-violet-100 p-2 text-lg text-violet-600" />
                <AidpDetailField label={t("aidpKnowledge.detailTabFiles")}>
                  {formatAidpDocumentCount(detail.document_count)}
                </AidpDetailField>
              </div>
              <div className="flex min-w-0 items-center gap-3">
                <DatabaseOutlined className="rounded-lg bg-violet-100 p-2 text-lg text-violet-600" />
                <AidpDetailField label={t("aidpKnowledge.detailPermissions")}>
                  {privateScope
                    ? t("aidpKnowledge.scopePrivate")
                    : t("aidpKnowledge.scopeShared")}
                </AidpDetailField>
              </div>
              <div className="flex min-w-0 items-center gap-3">
                <TeamOutlined className="rounded-lg bg-violet-100 p-2 text-lg text-violet-600" />
                <AidpDetailField label={t("aidpKnowledge.detailAllowedGroups")}>
                  {privateScope ? (
                    t("aidpKnowledge.detailOwnerOnly")
                  ) : canReadGroups && !groupsError && groupNames.length > 0 ? (
                    <AidpGroupNamesDisplay groupNames={groupNames} />
                  ) : (
                    UNKNOWN
                  )}
                </AidpDetailField>
              </div>
              <div className="flex min-w-0 items-center gap-3">
                <ClockCircleOutlined className="rounded-lg bg-violet-100 p-2 text-lg text-violet-600" />
                <AidpDetailField label={t("aidpKnowledge.detailCreatedAt")}>
                  {formatDetailDateTime(detail.created_at)}
                </AidpDetailField>
              </div>
              <div className="flex min-w-0 items-center gap-3">
                <UserOutlined className="rounded-lg bg-violet-100 p-2 text-lg text-violet-600" />
                <AidpDetailField label={t("aidpKnowledge.detailCreator")}>
                  <UserIdentity
                    casUsername={detail.creator_cas_username}
                    fallback={formatAidpCreator(detail.creator_name)}
                  />
                </AidpDetailField>
              </div>
            </dl>
          </div>
        </div>
      </section>

      {detailQuery.isError && (
        <Alert
          type="error"
          showIcon
          title={getAidpErrorMessage(
            detailQuery.error,
            t,
            t("aidpKnowledge.detailLoadFailed")
          )}
        />
      )}
      {groupsError && (
        <Alert
          type="error"
          showIcon
          title={getAidpErrorMessage(
            groupsError,
            t,
            t("aidpKnowledge.groupsLoadFailed")
          )}
        />
      )}
      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as DetailTab)}
        className="shrink-0 [&>.ant-tabs-nav]:mb-0 [&>.ant-tabs-content-holder]:hidden"
        tabBarStyle={{ marginBottom: 0 }}
        items={[
          { key: "files", label: t("aidpKnowledge.detailTabFiles") },
          { key: "tasks", label: t("aidpKnowledge.detailTabTasks") },
          {
            key: "information",
            label: t("aidpKnowledge.detailTabInformation"),
          },
          {
            key: "ontology",
            label: t("aidpKnowledge.detailTabOntology"),
          },
          {
            key: "sensitive-words",
            label: t("aidpKnowledge.detailTabSensitiveWords"),
          },
        ]}
      />

      {activeTab === "files" && (
        <AidpKnowledgeFilesPanel
          knowledgeBase={detail}
          canEdit={canEdit}
          isAvailable={isAvailable}
          pollingPaused={pollingPaused || editingKbMode !== null}
          onFilesChanged={() => void detailQuery.refetch()}
        />
      )}

      {activeTab === "tasks" && (
        <AidpKnowledgeTasksTab
          knowledgeBaseId={knowledgeBase.kds_id}
          canEdit={canEdit}
          // Tab-level dialogs mask the tab bar, so only the page-level edit
          // modal can be open while the tasks tab is mounted.
          pollingPaused={pollingPaused || editingKbMode !== null}
        />
      )}

      {activeTab === "information" && (
        <AidpKnowledgeInformationTab
          detail={detail}
          groupNames={groupNames}
          canConfigureGroupPermissions={canConfigureGroupPermissions}
          detailFetching={detailQuery.isFetching}
          onEditPermissions={() => setEditingKbMode("permissions")}
          onRefreshDetail={() => detailQuery.refetch()}
        />
      )}

      {activeTab === "ontology" && (
        <AidpKnowledgeOntologyTab kdsId={knowledgeBase.kds_id} />
      )}

      {activeTab === "sensitive-words" && (
        <section className="flex min-h-0 flex-1 flex-col bg-white">
          <AidpSensitiveWordsPage
            key={detail.kds_id}
            knowledgeBaseId={detail.kds_id}
            canManage={canEdit}
          />
        </section>
      )}

      <AidpUpdateKbModal
        open={editingKbMode !== null}
        mode={editingKbMode || "metadata"}
        knowledgeBase={detail}
        onCancel={() => setEditingKbMode(null)}
        onSuccess={(updated) => {
          setEditingKbMode(null);
          onUpdated(updated);
          void detailQuery.refetch();
        }}
      />
    </div>
  );
};

export default AidpKnowledgeFilesPage;
