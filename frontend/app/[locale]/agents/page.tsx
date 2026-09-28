"use client";

import { useCallback, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  App,
  Button,
  Card,
  Col,
  Grid,
  Input,
  Modal,
  Pagination,
  Row,
  Spin,
  Tag,
} from "antd";
import { Bot, FileInput, Pencil, Search, Clock } from "lucide-react";
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
  const cardHeight = `calc((100% - ${(rows - 1) * 20}px) / ${rows})`;

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
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-white px-4 py-6 sm:px-6 xl:px-16">
      <Card
        className="flex h-full min-h-0 w-full flex-col"
        styles={{
          body: {
            display: "flex",
            minHeight: 0,
            flex: 1,
            flexDirection: "column",
          },
        }}
      >
        <div className="flex h-full min-h-0 w-full flex-col gap-5">
          <section className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-4">
              <span className="flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary shadow-sm">
                <Bot className="size-7" aria-hidden />
              </span>
              <div>
                <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
                  {t("agentRepository.page.tab.mine")}
                </h1>
                <p className="mt-1 text-sm text-slate-600">
                  {t(
                    "agentRepository.mine.description",
                    "选择一个智能体以查看详情或进入编辑。"
                  )}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                icon={<FileInput className="size-4" />}
                onClick={handleImport}
              >
                {t("agentConfig.button.import")}
              </Button>
            </div>
          </section>

          <Input
            allowClear
            prefix={<Search className="size-4 text-slate-400" />}
            placeholder={t("agentSelector.searchPlaceholder")}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            className="h-10"
          />

          <div className="min-h-0 flex-1 overflow-hidden">
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
                  className="min-h-0 flex-1 content-stretch overflow-hidden"
                >
                  <Col
                    xs={24}
                    sm={12}
                    xl={8}
                    xxl={6}
                    className="flex"
                    style={{ height: cardHeight }}
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
                        className="flex"
                        style={{ height: cardHeight }}
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
                                  agent.current_version_no ? "green" : "orange"
                                }
                              >
                                {agent.current_version_no
                                  ? t(
                                      "agentRepository.mine.lifecycle.published"
                                    )
                                  : t("agentRepository.mine.lifecycle.draft")}
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
                              icon={<Pencil className="size-3.5" aria-hidden />}
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
        </div>
      </Card>

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
