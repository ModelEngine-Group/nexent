"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { App, Empty, InputNumber, Modal, Select, Spin } from "antd";
import {
  ChevronDown,
  ChevronUp,
  FileInput,
  LayoutGrid,
  List,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import AgentImportWizard from "@/components/agent/AgentImportWizard";
import CreateAgentModal from "@/components/agent/CreateAgentModal";
import { StandardButton } from "@/components/common/StandardButton";
import { StandardInput } from "@/components/common/StandardInput";
import { StandardPaginator } from "@/components/common/StandardPaginator";
import { useAgentList } from "@/hooks/agent/useAgentList";
import {
  openImportWizardWithFile,
  type ImportAgentData,
} from "@/lib/agentImportUtils";
import log from "@/lib/logger";
import { searchAgentInfo } from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";
import type { Agent } from "@/types/agentConfig";
import { AgentDetail } from "@/components/agent/agent-detail";
import { mapAgentInfoDetail } from "@/lib/myAgentDetail";

import AgentAvatar from "./components/agent-avatar";
import AgentListCard from "./components/agent-list-card";
import AgentListTable from "./components/agent-list-table";
import AgentVersion from "./agent-version";

function AgentConfigurationGuide({
  expanded,
  onToggle,
  showEmptyListDivider,
}: {
  expanded: boolean;
  onToggle: () => void;
  showEmptyListDivider: boolean;
}) {
  const { t } = useTranslation("common");
  const steps = [
    {
      title: t("agentConfig.guide.step.create.title"),
      description: t("agentConfig.guide.step.create.description"),
    },
    {
      title: t("agentConfig.guide.step.configure.title"),
      description: t("agentConfig.guide.step.configure.description"),
    },
    {
      title: t("agentConfig.guide.step.personalize.title"),
      description: t("agentConfig.guide.step.personalize.description"),
    },
    {
      title: t("agentConfig.guide.step.publish.title"),
      description: t("agentConfig.guide.step.publish.description"),
    },
    {
      title: t("agentConfig.guide.step.use.title"),
      description: t("agentConfig.guide.step.use.description"),
    },
  ];

  return (
    <div className="shrink-0">
      <div className="flex h-6 w-full items-center justify-between">
        <div className="text-sm font-medium text-[#191919]">
          {t("agentConfig.guide.title")}
        </div>
        {expanded ? (
          <button
            type="button"
            className="flex h-6 items-center gap-1 text-xs text-[#0067d1]"
            aria-expanded={expanded}
            onClick={onToggle}
          >
            <ChevronUp className="size-3" aria-hidden="true" />
            <span>{t("agentConfig.guide.collapse")}</span>
          </button>
        ) : null}
      </div>

      <div className="mt-2 text-sm leading-5 text-[#191919]">
        <p>{t("agentConfig.guide.description")}</p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-[#666666]">
          <li>{t("agentConfig.guide.point.one")}</li>
          <li>{t("agentConfig.guide.point.two")}</li>
        </ol>
        <div className="mt-[13px]">
          <div className="font-medium text-[#191919]">
            {t("agentConfig.guide.process.title")}
          </div>
          <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {steps.map(({ title, description }, index) => (
              <div
                key={title}
                className="relative flex h-[156px] w-full min-w-0 flex-col overflow-hidden rounded-[8px] border border-solid border-white px-[21px] py-6 [background:linear-gradient(180deg,rgba(236,243,255,1)_19.667%,rgba(252,253,253,1)_101.235%)] [box-shadow:inset_0_0_20px_0_rgba(239,239,239,0.3)]"
              >
                <div className="relative z-10">
                  <p className="h-[26px] w-full text-[18px] font-medium leading-[26px] !tracking-[0px] text-[#191919]">
                    {t("agentConfig.guide.stepLabel", { number: index + 1 })}
                    {title}
                  </p>
                  <p className="mt-4 text-[14px] text-[#777777]">
                    {description}
                  </p>
                </div>
              </div>
            ))}
          </div>
          {showEmptyListDivider ? (
            <div
              data-testid="agent-guide-divider"
              aria-hidden="true"
              className="mt-6 h-px w-full bg-[rgba(25,25,25,0.1)]"
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default function AgentsPage() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const pathname = usePathname();
  const router = useRouter();
  const initialize = useAgentStore((state) => state.initialize);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [jumpPage, setJumpPage] = useState<number | null>(null);
  const [view, setView] = useState<"grid" | "list">("grid");
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [isVersionManageOpen, setIsVersionManageOpen] = useState(false);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [importData, setImportData] = useState<ImportAgentData | null>(null);
  const [isImportOpen, setIsImportOpen] = useState(false);
  const [isGuideExpanded, setIsGuideExpanded] = useState(true);
  const [isGuideMounted, setIsGuideMounted] = useState(true);
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
      setIsGuideExpanded(true);
      return;
    }

    setIsGuideExpanded(false);
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

  const { agents, pagination, isLoading, isError, refetch } = useAgentList({
    search,
    page,
    pageSize,
  });
  const isEmptyAgentList =
    !isLoading &&
    !isError &&
    !search.trim() &&
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

  const handleOpenDetail = useCallback(
    async (agent: Agent) => {
      const loadedAgent = await loadAgent(Number(agent.id));
      if (!loadedAgent) return;
      setSelectedAgent(loadedAgent);
      setDetailOpen(true);
    },
    [loadAgent]
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
    updateUrl(agentId);
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
    <div className="flex h-full min-h-0 w-full flex-col bg-white p-6">
      <header className="flex h-12 shrink-0 items-center justify-between py-[10px]">
        <h1 className="text-[20px] font-medium leading-7 ![letter-spacing:0px] text-[#191919]">
          {t("sidebar.agentDev")}
        </h1>
        {!isGuideExpanded ? (
          <button
            type="button"
            className="flex h-6 items-center gap-1 text-xs text-[#0067d1]"
            aria-expanded={false}
            onClick={() => setGuideExpanded(true)}
          >
            <ChevronDown className="size-3" aria-hidden="true" />
            <span>{t("agentConfig.guide.expand")}</span>
          </button>
        ) : null}
      </header>

      <section className="mt-3 flex min-h-0 w-full flex-1 flex-col">
        <div
          data-testid="agent-guide-background"
          className={
            isGuideExpanded
              ? "max-h-[1000px] overflow-hidden rounded-2xl p-6 opacity-100 transition-[max-height,opacity,padding] duration-300 ease-in-out [background:linear-gradient(180deg,rgba(236,243,255,1)_0px,rgba(255,255,255,0)_418px),rgba(255,255,255,1)]"
              : "max-h-0 overflow-hidden p-0 opacity-0 transition-[max-height,opacity,padding] duration-300 ease-in-out"
          }
          aria-hidden={!isGuideExpanded}
        >
          {isGuideMounted ? (
            <AgentConfigurationGuide
              expanded={isGuideExpanded}
              onToggle={() => setGuideExpanded(false)}
              showEmptyListDivider={isEmptyAgentList}
            />
          ) : null}
        </div>

        <div className="mt-3 flex min-h-0 flex-1 flex-col pb-5">
          {isEmptyAgentList ? (
            <div className="flex min-h-0 flex-1 items-center justify-center">
              <Empty
                image={Empty.PRESENTED_IMAGE_DEFAULT}
                description={
                  <span className="text-[14px] leading-[22px] ![letter-spacing:0px] text-[#777777]">
                    {t("agentConfig.empty.noAgents")}
                  </span>
                }
              >
                <StandardButton
                  variant="primary"
                  onClick={() => setIsCreateOpen(true)}
                >
                  {t("agent.action.create")}
                </StandardButton>
              </Empty>
            </div>
          ) : (
            <>
              <div
                data-testid="agent-list-tabs"
                className="flex h-8 w-full shrink-0 items-center gap-8 border-b border-solid border-[#dfdfdf]"
              >
                <button
                  type="button"
                  className="flex h-8 shrink-0 items-center border-b-2 border-[#0067d1] text-[14px] leading-[22px] ![letter-spacing:0px] text-[#0067d1]"
                  aria-current="page"
                >
                  {t("agentConfig.list.mine")}
                </button>
                <button
                  type="button"
                  disabled
                  title={t("agentConfig.list.importedUnavailable")}
                  className="flex h-8 shrink-0 items-center text-[14px] leading-[22px] ![letter-spacing:0px] text-[#777777] disabled:cursor-not-allowed"
                >
                  {t("agentConfig.list.imported")}
                </button>
              </div>

              <div className="mt-3 flex h-auto w-full shrink-0 flex-col items-start justify-between gap-3 lg:h-8 lg:flex-row lg:items-center lg:gap-4">
                <div
                  className={`w-full max-w-full shrink-0 ${view === "list" ? "lg:w-[296px]" : "lg:w-[360px]"}`}
                >
                  <StandardInput
                    allowClear
                    prefix={<Search className="size-4 text-[#777777]" />}
                    placeholder={t("agentSelector.searchPlaceholder")}
                    value={search}
                    onChange={(event) => {
                      setSearch(event.target.value);
                      setPage(1);
                    }}
                    className="!h-8 !w-full"
                  />
                </div>
                <div className="flex h-auto flex-wrap items-center gap-2 lg:h-8 lg:shrink-0 lg:flex-nowrap">
                  <StandardButton
                    icon={<FileInput className="size-4" />}
                    onClick={handleImport}
                  >
                    {t("agentConfig.button.import")}
                  </StandardButton>
                  <StandardButton
                    variant="primary"
                    onClick={() => setIsCreateOpen(true)}
                  >
                    {t("agentConfig.list.new")}
                  </StandardButton>
                  <div className="flex h-8 items-center rounded-[4px] border border-solid border-[#c9c9c9]">
                    <button
                      type="button"
                      className={`flex size-[30px] items-center justify-center ${
                        view === "list"
                          ? "bg-[#0067d1] text-white"
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
                          ? "bg-[#0067d1] text-white"
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
                className={`mt-3 min-h-0 flex-1 ${
                  view === "list"
                    ? "overflow-hidden"
                    : "overflow-y-auto overflow-x-hidden pb-5"
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
                    <StandardButton onClick={() => refetch()}>
                      {t("repository.common.retry")}
                    </StandardButton>
                  </div>
                ) : (
                  <div
                    className={`flex min-h-0 flex-col gap-3 ${view === "list" ? "h-full" : ""}`}
                  >
                    {agents.length > 0 ? (
                      view === "list" ? (
                        <AgentListTable
                          agents={agents}
                          onOpen={(selected) => void handleOpenDetail(selected)}
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
                              onOpen={(selected) =>
                                void handleOpenDetail(selected)
                              }
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
                    <div className="flex min-h-8 w-full flex-wrap items-center justify-between gap-3">
                      <span className="text-[12px] leading-[18px] ![letter-spacing:0px] text-[#191919]">
                        {t("agentConfig.list.total", {
                          count: pagination?.total ?? 0,
                        })}
                      </span>
                      <div className="flex h-auto flex-wrap items-center justify-end gap-2 md:h-8">
                        <Select
                          aria-label={t("agentConfig.list.pageSize")}
                          value={pageSize}
                          options={[10, 20, 50].map((size) => ({
                            value: size,
                            label: t("agentConfig.list.perPage", {
                              count: size,
                            }),
                          }))}
                          onChange={(nextSize) => {
                            setPageSize(nextSize);
                            setPage(1);
                            setJumpPage(null);
                          }}
                          className="!h-8 !w-[116px] [&_.ant-select-selector]:!border-[#c9c9c9]"
                        />
                        <StandardPaginator
                          current={pagination?.page ?? page}
                          pageSize={pageSize}
                          total={pagination?.total ?? 0}
                          showSizeChanger={false}
                          onChange={setPage}
                        />
                        <InputNumber
                          aria-label={t("agentConfig.list.jumpPage")}
                          min={1}
                          max={Math.max(
                            1,
                            Math.ceil((pagination?.total ?? 0) / pageSize)
                          )}
                          controls={false}
                          value={jumpPage}
                          onChange={setJumpPage}
                          className="!h-8 !w-10 [&_.ant-input-number-input]:!h-[30px] [&_.ant-input-number-input]:!text-center"
                        />
                        <StandardButton
                          className="!px-2"
                          onClick={() => {
                            if (jumpPage !== null) {
                              setPage(
                                Math.min(
                                  jumpPage,
                                  Math.max(
                                    1,
                                    Math.ceil(
                                      (pagination?.total ?? 0) / pageSize
                                    )
                                  )
                                )
                              );
                            }
                          }}
                        >
                          {t("agentConfig.list.jump")}
                        </StandardButton>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </section>

      <AgentDetail
        detail={selectedAgent ? mapAgentInfoDetail(selectedAgent) : null}
        agentIcon={
          selectedAgent ? (
            <AgentAvatar agent={selectedAgent} size={48} iconSize={24} />
          ) : undefined
        }
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        onEdit={() => selectedAgent && updateUrl(Number(selectedAgent.id))}
        published={Boolean(selectedAgent?.current_version_no)}
      />
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
