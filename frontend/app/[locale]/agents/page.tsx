"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { App, Button, Input, Modal, Spin, Tag } from "antd";
import {
  ArrowLeft,
  Bot,
  FileInput,
  GitBranch,
  Plus,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import AgentImportWizard from "@/components/agent/AgentImportWizard";
import CreateAgentModal from "@/components/agent/CreateAgentModal";
import ResourceCard from "@/components/resource/ResourceCard";
import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
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

function getAgentTitle(agent: Agent) {
  return agent.display_name || agent.name;
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
        return false;
      }
      initialize(result.data);
      return true;
    },
    [initialize, message, t]
  );

  useEffect(() => {
    if (!isEditing || currentAgentId === requestedAgentId) return;
    void loadAgent(requestedAgentId);
  }, [currentAgentId, isEditing, loadAgent, requestedAgentId]);

  const visibleAgents = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return agents as Agent[];
    return (agents as Agent[]).filter((agent) =>
      [agent.display_name, agent.name, agent.description, agent.author].some(
        (value) =>
          String(value || "")
            .toLowerCase()
            .includes(query)
      )
    );
  }, [agents, search]);

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
      const loaded = await loadAgent(Number(agent.id));
      if (!loaded) return;
      setSelectedAgent(agent);
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
      <div className="flex h-full min-h-0 flex-col bg-gray-50">
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
    <div className="min-h-0 overflow-y-auto bg-gray-50 px-4 py-8 sm:px-6 xl:px-16">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-6">
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
            <Button
              type="primary"
              icon={<Plus className="size-4" />}
              onClick={() => setIsCreateOpen(true)}
            >
              {t("agentConfig.button.new")}
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

        {isLoading ? (
          <div className="flex justify-center py-20">
            <Spin size="large" />
          </div>
        ) : isError ? (
          <div className="flex flex-col items-center gap-3 py-20">
            <p className="text-sm text-slate-500">
              {t("agentRepository.mine.loadError")}
            </p>
            <Button onClick={() => refetch()}>
              {t("repository.common.retry")}
            </Button>
          </div>
        ) : (
          <ResourceCardGrid
            items={visibleAgents}
            page={page}
            onPageChange={setPage}
            search={search}
            showToolbar={false}
            renderItem={(agent) => (
              <ResourceCard
                key={agent.id}
                title={getAgentTitle(agent)}
                subtitle={agent.author}
                description={
                  agent.description || t("agentRepository.card.noDescription")
                }
                badge={
                  <Tag color={agent.current_version_no ? "green" : "orange"}>
                    {agent.current_version_no
                      ? t("agentRepository.mine.lifecycle.published")
                      : t("agentRepository.mine.lifecycle.draft")}
                  </Tag>
                }
                meta={
                  <span>
                    {agent.version_name ||
                      (agent.current_version_no
                        ? `V${agent.current_version_no}`
                        : "-")}
                  </span>
                }
                onClick={() => void handleOpenDetail(agent)}
              />
            )}
          />
        )}
      </div>

      <AgentDetail
        agent={selectedAgent}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        onEdit={() => selectedAgent && updateUrl(Number(selectedAgent.id))}
        actions={<AgentConfigActions />}
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
