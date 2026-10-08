"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  App,
  Button,
  Col,
  Empty,
  Grid,
  Input,
  Modal,
  Pagination,
  Row,
  Spin,
  Tag,
} from "antd";
import {
  ChevronDown,
  ChevronUp,
  Clock,
  FileInput,
  Pencil,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import AgentImportWizard from "@/components/agent/AgentImportWizard";
import CreateAgentModal from "@/components/agent/CreateAgentModal";
import CreateResourceCard from "@/components/resource/CreateResourceCard";
import ResourceCard from "@/components/resource/ResourceCard";
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

import AgentConfigActions from "./components/agent-config-actions";
import AgentAvatar from "./components/agent-avatar";
import AgentVersion from "./agent-version";

interface AgentCardItem extends Agent {
  create_time?: string;
  update_time?: string;
}

function getAgentTitle(agent: AgentCardItem) {
  return agent.display_name || agent.name;
}

function formatAgentDate(agent: AgentCardItem) {
  const source = agent.update_time || agent.create_time;
  if (!source) return null;
  const date = new Date(source);
  return Number.isNaN(date.getTime()) ? source : date.toLocaleDateString();
}

function AgentConfigurationGuide({
  expanded,
  onToggle,
}: {
  expanded: boolean;
  onToggle: () => void;
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

      <div className="mt-4 text-sm leading-5 text-[#191919]">
        <p>{t("agentConfig.guide.description")}</p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-[#666666]">
          <li>{t("agentConfig.guide.point.one")}</li>
          <li>{t("agentConfig.guide.point.two")}</li>
        </ol>
        <div className="mt-5">
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
          <div
            aria-hidden="true"
            className="mt-6 h-px w-full bg-[rgba(25,25,25,0.1)]"
          />
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
  const screens = Grid.useBreakpoint();
  const initialize = useAgentStore((state) => state.initialize);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
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

  const columns = screens.xxl ? 4 : screens.xl ? 3 : screens.md ? 2 : 1;
  const rows = screens.xs ? 2 : 3;
  const itemsPerPage = Math.max(1, columns * rows - 1);
  const { agents, pagination, isLoading, isError, refetch } = useAgentList({
    search,
    page,
    pageSize: itemsPerPage,
  });
  const isEmptyAgentList =
    !isLoading && !isError && !search.trim() && agents.length === 0;
  const updateUrl = useCallback(
    (agentId: number) => {
      router.push(`${pathname}/${agentId}`);
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
    <div className="flex min-h-full w-full flex-col bg-white p-6">
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

      <section className="mt-3 w-full shrink-0">
        <div
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
            />
          ) : null}
        </div>

        <div
          className={`mt-4 flex min-h-0 flex-1 flex-col pb-5 ${
            isGuideExpanded ? "px-6" : "px-0"
          }`}
        >
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
                <Button
                  type="primary"
                  onClick={() => setIsCreateOpen(true)}
                  className="!h-8 !min-h-8 !rounded-[4px] !border-0 !bg-[#0067d1] !px-4 !py-[5px] !text-[14px] !font-normal !leading-[22px] !text-white ![letter-spacing:0px]"
                >
                  {t("agent.action.create")}
                </Button>
              </Empty>
            </div>
          ) : (
            <>
              <div className="flex shrink-0 items-center gap-2">
                <Input
                  allowClear
                  prefix={<Search className="size-4 text-slate-400" />}
                  placeholder={t("agentSelector.searchPlaceholder")}
                  value={search}
                  onChange={(event) => {
                    setSearch(event.target.value);
                    setPage(1);
                  }}
                  className="!h-8 !w-[400px] max-w-full flex-none !rounded-[4px] !border-[#c9c9c9]"
                />
                <Button
                  icon={<FileInput className="size-4" />}
                  onClick={handleImport}
                  className="!h-8 !min-h-8 !rounded-[4px] !border-[#c9c9c9] !bg-white !px-4 !py-[5px] !text-[14px] !font-normal !leading-[22px] !text-[#191919] ![letter-spacing:0px]"
                >
                  {t("agentConfig.button.import")}
                </Button>
              </div>

              <div className="mt-2 min-h-0 flex-1 overflow-y-auto overflow-x-hidden pb-5">
                {isLoading ? (
                  <div className="flex h-full items-center justify-center">
                    <Spin size="large" />
                  </div>
                ) : isError ? (
                  <div className="flex h-full flex-col items-center justify-center gap-3">
                    <p className="text-sm text-slate-500">
                      {t("agentRepository.mine.loadError")}
                    </p>
                    <Button onClick={() => refetch()}>
                      {t("repository.common.retry")}
                    </Button>
                  </div>
                ) : (
                  <div className="flex h-full min-h-0 flex-col">
                    <Row
                      gutter={[20, 20]}
                      className="min-h-0 content-start overflow-visible"
                    >
                      <Col
                        xs={24}
                        sm={12}
                        xl={8}
                        xxl={6}
                        className="flex min-h-[136px]"
                      >
                        <CreateResourceCard
                          title={t("agentConfig.button.new")}
                          onClick={() => setIsCreateOpen(true)}
                          className="min-h-0"
                        />
                      </Col>
                      {(agents as AgentCardItem[]).map((agent) => {
                        const date = formatAgentDate(agent);
                        return (
                          <Col
                            key={agent.id}
                            xs={24}
                            sm={12}
                            xl={8}
                            xxl={6}
                            className="flex min-h-[136px]"
                          >
                            <ResourceCard
                              className="h-full min-h-0"
                              title={getAgentTitle(agent)}
                              subtitle={
                                agent.current_version_no
                                  ? t("agentRepository.mine.currentVersion", {
                                      version:
                                        agent.version_name ||
                                        `V${agent.current_version_no}`,
                                    })
                                  : undefined
                              }
                              icon={
                                <AgentAvatar
                                  agent={agent}
                                  size={44}
                                  iconSize={20}
                                />
                              }
                              description={
                                agent.description ||
                                t("agentRepository.card.noDescription")
                              }
                              descriptionLines={2}
                              actions={
                                <div className="flex flex-col items-end gap-1.5">
                                  <AgentConfigActions
                                    agentId={Number(agent.id)}
                                    readOnly={agent.permission === "READ_ONLY"}
                                    variant="menu"
                                    onManageVersions={handleManageVersions}
                                  />
                                  <Tag
                                    color={
                                      agent.current_version_no
                                        ? "green"
                                        : "orange"
                                    }
                                  >
                                    {agent.current_version_no
                                      ? t(
                                          "agentRepository.mine.lifecycle.published"
                                        )
                                      : t(
                                          "agentRepository.mine.lifecycle.draft"
                                        )}
                                  </Tag>
                                </div>
                              }
                              meta={
                                <span className="inline-flex items-center gap-1">
                                  <Clock className="size-3.5" aria-hidden />
                                  {date || "-"}
                                </span>
                              }
                              footerLayout="inline"
                              footer={
                                <Button
                                  type="text"
                                  size="small"
                                  className="!text-slate-600 hover:!bg-transparent hover:!text-blue-500"
                                  icon={
                                    <Pencil className="size-3.5" aria-hidden />
                                  }
                                  onClick={() => updateUrl(Number(agent.id))}
                                >
                                  {t("agentRepository.mine.edit")}
                                </Button>
                              }
                              onClick={() => void handleOpenDetail(agent)}
                            />
                          </Col>
                        );
                      })}
                    </Row>
                    {(pagination?.total ?? 0) > itemsPerPage ? (
                      <div className="flex shrink-0 justify-end pt-5">
                        <Pagination
                          current={pagination?.page ?? page}
                          pageSize={itemsPerPage}
                          total={pagination?.total ?? 0}
                          showSizeChanger={false}
                          onChange={setPage}
                        />
                      </div>
                    ) : null}
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
