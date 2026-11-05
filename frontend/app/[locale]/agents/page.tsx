// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { App, Empty, Modal, Spin } from "antd";
import {
  ChevronDown,
  ChevronUp,
  FileInput,
  LayoutGrid,
  List,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import AgentImportWizard from "@/components/agent/AgentImportWizard";
import CreateAgentModal from "@/components/agent/CreateAgentModal";
import { Button } from "@/components/common/Button";
import { SearchInput } from "@/components/common/SearchInput";
import { Pagination } from "@/components/common/Pagination";
import TagFilterPopover from "@/components/tag/TagFilterPopover";
import { useGuidePreference } from "@/hooks/useGuidePreference";
import { useAgentList } from "@/hooks/agent/useAgentList";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import {
  openImportWizardWithFile,
  type ImportAgentData,
} from "@/lib/agentImportUtils";
import log from "@/lib/logger";
import { getTagSearchPredicates } from "@/lib/systemTagLabels";
import { searchAgentInfo } from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";
import type { Agent } from "@/types/agentConfig";
import type { TagResourcePredicate } from "@/types/tagManagement";

import AgentConfigurationGuide from "./components/agent-configuration-guide";
import AgentListCard from "./components/agent-list-card";
import AgentListTable from "./components/agent-list-table";
import AgentVersion from "./agent-version";

export default function AgentsPage() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const pathname = usePathname();
  const router = useRouter();
  const initialize = useAgentStore((state) => state.initialize);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [tableColumnWidths, setTableColumnWidths] = useState<
    Record<string, number>
  >({});
  const [view, setView] = useState<"grid" | "list">("grid");
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [tagPredicates, setTagPredicates] = useState<TagResourcePredicate[]>(
    []
  );
  const [isVersionManageOpen, setIsVersionManageOpen] = useState(false);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [importData, setImportData] = useState<ImportAgentData | null>(null);
  const [isImportOpen, setIsImportOpen] = useState(false);
  const { dismissed, ready, dismiss, reset } = useGuidePreference(
    "agent-configuration"
  );
  const isGuideExpanded = ready && !dismissed;
  const [isGuideMounted, setIsGuideMounted] = useState(false);
  const guideCollapseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (guideCollapseTimer.current) {
        clearTimeout(guideCollapseTimer.current);
      }
    },
    []
  );

  const setGuideExpanded = (expanded: boolean) => {
    if (guideCollapseTimer.current) {
      clearTimeout(guideCollapseTimer.current);
      guideCollapseTimer.current = null;
    }

    if (expanded) {
      setIsGuideMounted(true);
      reset();
      return;
    }

    dismiss();
    guideCollapseTimer.current = setTimeout(() => {
      setIsGuideMounted(false);
      guideCollapseTimer.current = null;
    }, 300);
  };

  const loadAgent = useCallback(
    async (agentId: number) => {
      const result = await searchAgentInfo(agentId);
      if (!result.success || !result.data) {
        message.error(
          result.message || t("agentConfig.agents.detailsLoadFailed")
        );
        return null;
      }
      initialize(result.data);
      return result.data;
    },
    [initialize, message, t]
  );

  const { data: tagLibraries } = useTagLibraries();
  const defaultTagLibrary =
    tagLibraries?.find(
      (library) => library.bucket_key === "default_resource"
    ) ?? null;
  const { data: tagDefinitions } = useTagDefinitions(
    defaultTagLibrary?.bucket_id ?? null
  );
  const searchTagPredicates = useMemo(
    () => getTagSearchPredicates(tagDefinitions, search, t),
    [tagDefinitions, search, t]
  );
  const { agents, pagination, isLoading, isError, refetch } = useAgentList({
    search,
    page,
    pageSize,
    includeRepositoryInfo: true,
    ...(searchTagPredicates.length > 0 ? { searchTagPredicates } : {}),
    ...(tagPredicates.length > 0 ? { tagPredicates } : {}),
  });
  useEffect(() => {
    if (pagination && page > Math.max(1, pagination.totalPages))
      setPage(Math.max(1, pagination.totalPages));
  }, [page, pagination]);
  const isEmptyAgentList =
    !isLoading &&
    !isError &&
    !search.trim() &&
    tagPredicates.length === 0 &&
    agents.length === 0 &&
    (pagination?.total ?? 0) === 0;
  const updateUrl = useCallback(
    (agentId: number) => {
      router.push(`${pathname}/${agentId}`);
    },
    [pathname, router]
  );
  const openPublishFlow = useCallback(
    (agentId: number) => {
      router.push(`${pathname}/${agentId}?publish=1`);
    },
    [pathname, router]
  );

  const handleOpenAgent = useCallback(
    (agent: Agent) => updateUrl(Number(agent.id)),
    [updateUrl]
  );

  const handleManageVersions = useCallback(
    async (agentId: number) => {
      const loadedAgent = await loadAgent(agentId);
      if (!loadedAgent) return;
      setSelectedAgent(loadedAgent);
      setIsVersionManageOpen(true);
    },
    [loadAgent]
  );

  const refreshSelectedAgentInfo = useCallback(async () => {
    if (!selectedAgent?.id) return null;
    const loadedAgent = await loadAgent(Number(selectedAgent.id));
    if (loadedAgent) setSelectedAgent(loadedAgent);
    return loadedAgent;
  }, [loadAgent, selectedAgent]);

  const handleCreate = ({ agentId }: { agentId: number }) => {
    setIsCreateOpen(false);
    void refetch();
    router.push(`${pathname}/${agentId}?onboarding=1`);
  };

  const handleImport = async () => {
    await openImportWizardWithFile({
      onSuccess: (data) => {
        setImportData(data);
        setIsImportOpen(true);
      },
      message,
      t,
      log,
    });
  };

  const handleImportComplete = (agentId: number) => {
    setIsImportOpen(false);
    setImportData(null);
    void refetch();
    updateUrl(agentId);
  };

  return (
    <div className="[font-family:HarmonyOS_Sans_SC,Huawei_Sans,system-ui,sans-serif] [&_.ant-select]:[font-family:inherit] [&_.ant-input-number]:[font-family:inherit] flex h-full min-h-0 w-full flex-col overflow-y-auto bg-white p-6">
      <header className="flex h-12 shrink-0 items-center justify-between py-[10px]">
        <h1 className="text-[20px] font-medium leading-7 ![letter-spacing:0px] text-[#191919]">
          {t("sidebar.agentConfig")}
        </h1>
        <button
          type="button"
          className="flex h-[22px] min-w-[72px] shrink-0 items-center justify-center gap-[6px] text-[14px] font-normal leading-[22px] tracking-[0px] text-[#191919]"
          aria-expanded={isGuideExpanded}
          aria-controls="agent-configuration-guide"
          onClick={() => setGuideExpanded(!isGuideExpanded)}
        >
          <span>
            {t(
              isGuideExpanded
                ? "agentConfig.guide.collapse"
                : "agentConfig.guide.expand"
            )}
          </span>
          {isGuideExpanded ? (
            <ChevronUp className="size-2" aria-hidden="true" />
          ) : (
            <ChevronDown className="size-2" aria-hidden="true" />
          )}
        </button>
      </header>

      <section className="mt-3 flex min-h-0 w-full flex-1 flex-col">
        <div
          id="agent-configuration-guide"
          data-testid="agent-guide-background"
          className={
            isGuideExpanded
              ? "max-h-[2000px] shrink-0 overflow-hidden rounded-2xl p-6 opacity-100 transition-[max-height,opacity,padding] duration-300 ease-in-out [background:linear-gradient(180deg,rgba(236,243,255,1)_0%,rgba(255,255,255,0)_100%),rgba(255,255,255,1)]"
              : "max-h-0 shrink-0 overflow-hidden p-0 opacity-0 transition-[max-height,opacity,padding] duration-300 ease-in-out"
          }
          aria-hidden={!isGuideExpanded}
        >
          {isGuideExpanded || isGuideMounted ? (
            <AgentConfigurationGuide />
          ) : null}
        </div>

        <div className="relative mt-3 flex min-h-[300px] flex-1 flex-col pb-5">
          {isGuideExpanded ? (
            <div
              data-testid="agent-guide-divider"
              aria-hidden="true"
              className="absolute inset-x-0 top-0 h-px bg-[rgba(25,25,25,0.1)]"
            />
          ) : null}
          {isEmptyAgentList ? (
            <div className="relative flex min-h-0 flex-1 items-center justify-center">
              <Empty
                image={Empty.PRESENTED_IMAGE_DEFAULT}
                description={
                  <span className="text-[14px] leading-[22px] ![letter-spacing:0px] text-[#777777]">
                    {t("agentConfig.empty.noAgents")}
                  </span>
                }
              >
                <Button
                  variant="default"
                  onClick={() => setIsCreateOpen(true)}
                  size="sm"
                >
                  {t("agent.action.create")}
                </Button>
              </Empty>
            </div>
          ) : (
            <>
              <div className="mt-3 flex h-auto w-full shrink-0 flex-col items-start justify-between gap-3 lg:h-8 lg:flex-row lg:items-center lg:gap-4">
                <div className="flex w-full min-w-0 items-center gap-2 lg:w-1/2">
                  <SearchInput
                    placeholder={t("agentSelector.searchPlaceholder")}
                    value={search}
                    onChange={(event) => {
                      setSearch(event.target.value);
                      setPage(1);
                    }}
                    className="min-w-0 flex-1"
                  />
                  <TagFilterPopover
                    definitions={tagDefinitions ?? []}
                    value={tagPredicates}
                    onChange={(value) => {
                      setTagPredicates(value);
                      setPage(1);
                    }}
                    buttonClassName="!h-8 shrink-0"
                  />
                </div>
                <div className="flex h-auto flex-wrap items-center gap-2 lg:h-8 lg:shrink-0 lg:flex-nowrap">
                  <Button
                    icon={<FileInput className="size-4" />}
                    onClick={handleImport}
                    variant="outline"
                    size="sm"
                  >
                    {t("agentConfig.button.import")}
                  </Button>
                  <Button
                    variant="default"
                    onClick={() => setIsCreateOpen(true)}
                    size="sm"
                  >
                    {t("agentConfig.list.new")}
                  </Button>
                  <div className="flex h-8 items-center rounded-[4px] border border-solid border-[#c9c9c9]">
                    <button
                      type="button"
                      className={`flex size-[30px] items-center justify-center ${
                        view === "list"
                          ? "bg-primary text-primary-foreground hover:bg-primary-hover active:bg-primary-active"
                          : "text-[#777777]"
                      }`}
                      aria-label={t("agentConfig.list.listView")}
                      aria-pressed={view === "list"}
                      onClick={() => setView("list")}
                    >
                      <List className="size-4" aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className={`flex size-[30px] items-center justify-center ${
                        view === "grid"
                          ? "bg-primary text-primary-foreground hover:bg-primary-hover active:bg-primary-active"
                          : "text-[#777777]"
                      }`}
                      aria-label={t("agentConfig.list.gridView")}
                      aria-pressed={view === "grid"}
                      onClick={() => setView("grid")}
                    >
                      <LayoutGrid className="size-4" aria-hidden="true" />
                    </button>
                  </div>
                </div>
              </div>

              <div
                data-testid="agent-list-content"
                className={`min-h-0 flex-1 ${
                  view === "list"
                    ? "mt-3 overflow-hidden"
                    : "-mx-px mt-[11px] overflow-y-auto overflow-x-hidden px-px pb-5 pt-px"
                }`}
              >
                {isLoading ? (
                  <div className="flex min-h-40 items-center justify-center">
                    <Spin size="large" />
                  </div>
                ) : isError ? (
                  <div className="flex min-h-40 flex-col items-center justify-center gap-3">
                    <p className="text-sm text-slate-500">
                      {t("agentRepository.mine.loadError")}
                    </p>
                    <Button
                      onClick={() => refetch()}
                      variant="outline"
                      size="sm"
                    >
                      {t("repository.common.retry")}
                    </Button>
                  </div>
                ) : (
                  <div
                    className={`flex min-h-0 flex-col gap-3 ${view === "list" ? "h-full" : ""}`}
                  >
                    {agents.length > 0 ? (
                      view === "list" ? (
                        <AgentListTable
                          agents={agents}
                          columnWidths={tableColumnWidths}
                          onColumnWidthsChange={setTableColumnWidths}
                          onOpen={handleOpenAgent}
                          onConfigure={updateUrl}
                          onPublish={openPublishFlow}
                          onManageVersions={handleManageVersions}
                        />
                      ) : (
                        <div className="grid grid-cols-1 gap-x-4 gap-y-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                          {agents.map((agent) => (
                            <AgentListCard
                              key={agent.id}
                              agent={agent}
                              onOpen={handleOpenAgent}
                              onConfigure={updateUrl}
                              onPublish={openPublishFlow}
                              onManageVersions={handleManageVersions}
                            />
                          ))}
                        </div>
                      )
                    ) : (
                      <Empty className="py-12" />
                    )}
                    <Pagination
                      current={pagination?.page ?? page}
                      pageSize={pageSize}
                      total={pagination?.total ?? 0}
                      showTotal
                      showSizeChanger
                      showQuickJumper
                      pageSizeOptions={[10, 12, 20, 50]}
                      onPageSizeChange={setPageSize}
                      onPageChange={setPage}
                    />
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </section>

      <Modal
        centered
        width={900}
        open={isVersionManageOpen}
        title={t("agent.version.manage")}
        onCancel={() => setIsVersionManageOpen(false)}
        footer={null}
      >
        <AgentVersion
          currentVersionNo={selectedAgent?.current_version_no}
          onRefreshAgentInfo={refreshSelectedAgentInfo}
        />
      </Modal>
      <CreateAgentModal
        open={isCreateOpen}
        onCancel={() => setIsCreateOpen(false)}
        onCreated={handleCreate}
      />
      <AgentImportWizard
        visible={isImportOpen}
        initialData={importData}
        onCancel={() => {
          setIsImportOpen(false);
          setImportData(null);
        }}
        onImportComplete={handleImportComplete}
      />
    </div>
  );
}
