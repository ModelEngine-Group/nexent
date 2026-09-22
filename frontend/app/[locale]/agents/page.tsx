"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
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
import {
  ArrowLeft,
  Bot,
  FileInput,
  GitBranch,
  Pencil,
  Search,
  Clock,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import AgentImportWizard from "@/components/agent/AgentImportWizard";
import CreateAgentModal from "@/components/agent/CreateAgentModal";
import CreateResourceCard from "@/components/resource/CreateResourceCard";
import ResourceCard from "@/components/resource/ResourceCard";
import { useAgentInfo } from "@/hooks/agent/useAgentInfo";
import { useAgentList } from "@/hooks/agent/useAgentList";
import {
  openImportWizardWithFile,
  type ImportAgentData,
} from "@/lib/agentImportUtils";
import log from "@/lib/logger";
import { searchAgentInfo } from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";
import type { Agent } from "@/types/agentConfig";

import AgentConfigActions from "./components/agent-config-actions";
import AgentDetail from "./agent-detail";
import Agents from "./agents";
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
  const searchParams = useSearchParams();
  const requestedAgentId = Number(searchParams.get("agent_id"));
  const isEditing = Number.isInteger(requestedAgentId) && requestedAgentId > 0;
  const { agents, isLoading, isError, refetch } = useAgentList("");
  const screens = Grid.useBreakpoint();
  const initialize = useAgentStore((state) => state.initialize);
  const currentAgentId = useAgentStore((state) => state.currentAgentId);
  const reset = useAgentStore((state) => state.reset);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [isVersionManageOpen, setIsVersionManageOpen] = useState(false);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [importData, setImportData] = useState<ImportAgentData | null>(null);
  const [isImportOpen, setIsImportOpen] = useState(false);
  const { agentInfo, refetch: refetchAgentInfo } = useAgentInfo(
    selectedAgent?.id ? Number(selectedAgent.id) : null
  );

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

  useEffect(() => {
    if (!isEditing || currentAgentId === requestedAgentId) return;
    void loadAgent(requestedAgentId);
  }, [currentAgentId, isEditing, loadAgent, requestedAgentId]);

  const visibleAgents = useMemo((): AgentCardItem[] => {
    const query = search.trim().toLowerCase();
    if (!query) return agents as AgentCardItem[];
    return (agents as AgentCardItem[]).filter((agent) =>
      [agent.display_name, agent.name, agent.description, agent.author].some(
        (value) =>
          String(value || "")
            .toLowerCase()
            .includes(query)
      )
    );
  }, [agents, search]);
  const columns = screens.xxl ? 4 : screens.xl ? 3 : screens.md ? 2 : 1;
  const rows = screens.xs ? 2 : 3;
  const itemsPerPage = Math.max(1, columns * rows - 1);
  const pageCount = Math.max(1, Math.ceil(visibleAgents.length / itemsPerPage));
  const currentPage = Math.min(page, pageCount);
  const pageItems = visibleAgents.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  );
  const cardHeight = `calc((100% - ${(rows - 1) * 20}px) / ${rows})`;

  const updateUrl = useCallback(
    (agentId?: number) => {
      const nextParams = new URLSearchParams(searchParams.toString());
      if (agentId) nextParams.set("agent_id", String(agentId));
      else nextParams.delete("agent_id");
      const query = nextParams.toString();
      router.push(query ? `${pathname}?${query}` : pathname);
    },
    [pathname, router, searchParams]
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

  if (isEditing) {
    return (
      <div className="flex h-full min-h-0 flex-col bg-white">
        <div className="flex shrink-0 items-center justify-between border-b border-gray-200 bg-white px-6 py-2">
          <Button
            icon={<ArrowLeft className="size-4" />}
            type="text"
            onClick={() => {
              reset();
              updateUrl();
            }}
          >
            {t("agentRepository.mine.backToRepository")}
          </Button>
          <div className="flex items-center gap-2">
            <AgentConfigActions />
            <Button
              icon={<GitBranch className="size-4" />}
              onClick={() => setIsVersionManageOpen(true)}
            >
              {t("agent.version.manage")}
            </Button>
          </div>
        </div>
        <div className="min-h-0 flex-1">
          <Agents />
        </div>
        <Modal
          centered
          width={900}
          open={isVersionManageOpen}
          title={t("agent.version.manage")}
          onCancel={() => setIsVersionManageOpen(false)}
          footer={null}
        >
          <AgentVersion
            currentVersionNo={agentInfo?.current_version_no}
            onRefreshAgentInfo={refetchAgentInfo}
          />
        </Modal>
      </div>
    );
  }

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
            className="h-10 max-w-md"
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
                  {pageItems.map((agent) => {
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
                          subtitle={t("agentRepository.mine.currentVersion", {
                            version:
                              agent.version_name ||
                              (agent.current_version_no
                                ? `V${agent.current_version_no}`
                                : "-"),
                          })}
                          icon={
                            <span className="flex size-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
                              <Bot className="size-5" aria-hidden />
                            </span>
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
                                variant="menu"
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
                {visibleAgents.length > itemsPerPage ? (
                  <div className="flex shrink-0 justify-end pt-5">
                    <Pagination
                      current={currentPage}
                      pageSize={itemsPerPage}
                      total={visibleAgents.length}
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
        agent={selectedAgent}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        onEdit={() => selectedAgent && updateUrl(Number(selectedAgent.id))}
        onManageVersions={() => setIsVersionManageOpen(true)}
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
          currentVersionNo={agentInfo?.current_version_no}
          onRefreshAgentInfo={refetchAgentInfo}
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
