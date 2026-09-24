"use client";

import { ResourceSelectionGrid } from "@/features/workbench/components/ResourceSelectionGrid";
import { ResourceSelectionActions } from "./ResourceSelectionActions";
import { SelectedResourceTags } from "./SelectedResourceTags";
import { useRouter } from "next/navigation";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Input, Modal, Spin, Tabs, message } from "antd";
import type {
  AgentRepositoryListingItem,
  RepositoryImportPrecheckResponse,
} from "@/types/agentRepository";
import {
  fetchAgentRepositoryListings,
  fetchRepositoryImportPrecheck,
  importAgentFromRepository,
} from "@/services/agentRepositoryService";
import { fetchPublishedAgentList } from "@/services/agentConfigService";
import type { Agent } from "@/types/agentConfig";
import { ResourceCard } from "./ResourceCard";
import {
  ResourcePagination,
  RESOURCE_PAGE_SIZE,
  resourcePage,
} from "./ResourcePagination";
import { useTranslation } from "react-i18next";
import { getUnavailableReasonLabels } from "@/lib/agentLabelMapper";

export function AgentPicker({
  open,
  agents,
  selectedId,
  selectedIds,
  onCancel,
  onSelect,
  onConfirm,
  multiple = false,
}: {
  open: boolean;
  agents: Agent[];
  selectedId?: string;
  selectedIds?: string[];
  onCancel: () => void;
  onSelect: (agent: Agent) => void;
  onConfirm?: (agents: Agent[]) => Promise<void> | void;
  multiple?: boolean;
}) {
  const router = useRouter();
  const [draft, setDraft] = useState<Agent[]>([]);
  const [saving, setSaving] = useState(false);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open && !wasOpen.current) {
      const ids = selectedIds ?? (selectedId ? [selectedId] : []);
      setDraft(agents.filter((agent) => ids.includes(String(agent.id))));
    }
    wasOpen.current = open;
  }, [open, agents, selectedId, selectedIds]);
  const toggle = (agent: Agent) =>
    setDraft((current) =>
      current.some((item) => item.id === agent.id)
        ? current.filter((item) => item.id !== agent.id)
        : multiple
          ? [...current, agent]
          : [agent]
    );
  const [search, setSearch] = useState("");
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const [tab, setTab] = useState("mine");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [repository, setRepository] = useState<AgentRepositoryListingItem[]>(
    []
  );
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [precheck, setPrecheck] =
    useState<RepositoryImportPrecheckResponse | null>(null);
  const [skillResolutions, setSkillResolutions] = useState<
    Record<string, "rename" | "use_existing">
  >({});
  const operationRef = useRef(0);
  useEffect(() => {
    if (!open) {
      operationRef.current += 1;
      setPrecheck(null);
      setSkillResolutions({});
      setImporting(false);
      setSearch("");
      setPage(1);
    }
  }, [open]);
  useEffect(() => {
    if (!open || tab !== "repository") return;
    let cancelled = false;
    setLoading(true);
    void fetchAgentRepositoryListings({
      status: "shared",
      search,
      page,
      page_size: RESOURCE_PAGE_SIZE,
    })
      .then((result) => {
        if (!cancelled) {
          setRepository(result.items);
          setTotal(result.pagination?.total ?? result.items.length);
        }
      })
      .catch(() => {
        if (!cancelled) message.error("仓库加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, tab, search, page]);
  const check = async (item: AgentRepositoryListingItem) => {
    const operation = ++operationRef.current;
    setLoading(true);
    try {
      const result = await fetchRepositoryImportPrecheck(
        item.agent_repository_id
      );
      if (operation !== operationRef.current) return;
      setPrecheck(result);
      setSkillResolutions(
        Object.fromEntries(
          result.items
            .filter(
              (dependency) =>
                dependency.type === "skill" &&
                dependency.reason_code === "skill_duplicate"
            )
            .map((dependency) => [dependency.name, "rename"])
        )
      );
    } catch {
      if (operation === operationRef.current)
        message.error("导入预检失败，请重试");
    } finally {
      if (operation === operationRef.current) setLoading(false);
    }
  };
  const unresolvedDependencies =
    precheck?.items.filter(
      (item) =>
        !item.available &&
        !(item.type === "skill" && item.reason_code === "skill_duplicate")
    ) ?? [];
  const importAgent = async () => {
    if (!precheck || unresolvedDependencies.length > 0) return;
    const operation = ++operationRef.current;
    setImporting(true);
    try {
      const duplicateSkills = precheck.items.filter(
        (item) =>
          item.type === "skill" && item.reason_code === "skill_duplicate"
      );
      const resolutions = duplicateSkills.map((item) => ({
        skill_name: item.name,
        action: skillResolutions[item.name] ?? "rename",
        ...((skillResolutions[item.name] ?? "rename") === "rename"
          ? { new_name: item.suggested_new_name || `${item.name} 副本` }
          : {}),
      }));
      const result = duplicateSkills.length
        ? await importAgentFromRepository(
            precheck.agent_repository_id,
            resolutions
          )
        : await importAgentFromRepository(precheck.agent_repository_id);
      if (operation !== operationRef.current) return;
      if (!Number.isInteger(result.agent_id) || result.agent_id <= 0)
        throw new Error("导入响应缺少根 Agent ID，请刷新列表检查结果");
      const refreshed = await fetchPublishedAgentList();
      if (operation !== operationRef.current) return;
      if (!refreshed.success)
        throw new Error("导入成功，刷新资源失败，请重新打开选择器");
      const freshAgents = (refreshed.data ?? []) as Agent[];
      queryClient.setQueryData(["publishedAgentsList"], freshAgents);
      const imported = freshAgents.find(
        (agent) => Number(agent.id) === result.agent_id
      );
      setPrecheck(null);
      setTab("mine");
      if (
        !imported ||
        imported.is_available === false ||
        !imported.current_version_no
      ) {
        message.warning(
          "智能体已导入，但尚未发布或依赖不完整；完善后才能选择运行"
        );
        return;
      }
      setDraft((current) =>
        multiple
          ? [...current.filter((item) => item.id !== imported.id), imported]
          : [imported]
      );
    } catch (error) {
      if (operation === operationRef.current)
        message.error(error instanceof Error ? error.message : "导入失败");
    } finally {
      if (operation === operationRef.current) setImporting(false);
    }
  };
  const visible = useMemo(
    () =>
      agents.filter((agent) =>
        [agent.name, agent.display_name, agent.description].some((value) =>
          value?.toLowerCase().includes(search.trim().toLowerCase())
        )
      ),
    [agents, search]
  );
  return (
    <Modal
      open={open}
      title="选择智能体"
      okText="确定"
      cancelText="取消"
      confirmLoading={saving}
      okButtonProps={{ disabled: loading || importing, "aria-label": "确定" }}
      onOk={async () => {
        setSaving(true);
        try {
          if (onConfirm) await onConfirm(draft);
          else draft.forEach((agent) => onSelect(agent));
          onCancel();
        } catch (error) {
          message.error(error instanceof Error ? error.message : "选择失败");
        } finally {
          setSaving(false);
        }
      }}
      onCancel={() => {
        operationRef.current += 1;
        setPrecheck(null);
        setSkillResolutions({});
        setLoading(false);
        setImporting(false);
        onCancel();
      }}
      width={920}
      centered
    >
      <Tabs
        activeKey={tab}
        onChange={(value) => {
          operationRef.current += 1;
          setPrecheck(null);
          setSkillResolutions({});
          setLoading(false);
          setImporting(false);
          setTab(value);
          setPage(1);
        }}
        items={[
          { key: "mine", label: "我的" },
          { key: "repository", label: "仓库" },
        ]}
      />
      <Input.Search
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
          setPage(1);
        }}
        placeholder="搜索智能体名称或描述"
        allowClear
      />
      <Spin spinning={loading}>
        {tab === "mine" && (
          <div className="my-3 flex items-center gap-3 rounded bg-blue-50 px-4 py-3">
            <SelectedResourceTags
              items={draft.map((agent) => ({
                id: String(agent.id),
                name: agent.display_name || agent.name,
              }))}
              onRemove={(id) =>
                setDraft((current) =>
                  current.filter((agent) => String(agent.id) !== id)
                )
              }
            />
            <ResourceSelectionActions
              toggleAllDisabled={
                !multiple &&
                visible.filter((agent) => agent.is_available !== false).length >
                  1
              }
              allSelected={
                visible.filter((agent) => agent.is_available !== false).length >
                  0 &&
                visible
                  .filter((agent) => agent.is_available !== false)
                  .every((agent) => draft.some((item) => item.id === agent.id))
              }
              hasSelection={draft.length > 0}
              disabled={loading || saving}
              empty={!visible.some((agent) => agent.is_available !== false)}
              onClear={() => setDraft([])}
              onToggleAll={() => {
                const candidates = visible.filter(
                  (agent) => agent.is_available !== false
                );
                setDraft((current) =>
                  candidates.every((agent) =>
                    current.some((item) => item.id === agent.id)
                  )
                    ? current.filter(
                        (item) =>
                          !candidates.some((agent) => agent.id === item.id)
                      )
                    : [
                        ...current,
                        ...candidates.filter(
                          (agent) =>
                            !current.some((item) => item.id === agent.id)
                        ),
                      ]
                );
              }}
            />
          </div>
        )}
        <ResourceSelectionGrid
          role="listbox"
          aria-label="智能体资源"
          className="mt-4 p-1"
        >
          {tab === "mine"
            ? resourcePage(visible, page).map((agent) => (
                <ResourceCard
                  key={agent.id}
                  title={agent.display_name || agent.name}
                  description={agent.description}
                  tags={agent.tags || []}
                  selected={draft.some((item) => item.id === agent.id)}
                  disabled={agent.is_available === false}
                  disabledReason={
                    agent.is_available === false
                      ? getUnavailableReasonLabels(
                          agent.unavailable_reasons || [],
                          t
                        ).join("；") || "智能体不可用，服务端未提供具体原因"
                      : undefined
                  }
                  badges={[`v${agent.current_version_no ?? "-"}`]}
                  onClick={() => toggle(agent)}
                  actions={
                    <Button
                      size="small"
                      aria-label="编辑"
                      onClick={() =>
                        router.push(`/agents?agent_id=${agent.id}`)
                      }
                    >
                      编辑
                    </Button>
                  }
                />
              ))
            : repository.map((item) => (
                <ResourceCard
                  key={item.agent_repository_id}
                  title={item.display_name || item.name}
                  description={item.description ?? undefined}
                  tags={item.tags}
                  badges={[item.version_label ?? "仓库"]}
                  disabled={loading || importing}
                  actions={
                    <Button
                      size="small"
                      disabled={loading || importing}
                      onClick={() => void check(item)}
                    >
                      预检并导入
                    </Button>
                  }
                  onClick={() => void check(item)}
                />
              ))}
        </ResourceSelectionGrid>
      </Spin>
      <ResourcePagination
        current={page}
        total={tab === "repository" ? total : visible.length}
        onChange={setPage}
        disabled={loading || importing}
      />
      <Modal
        open={!!precheck}
        title="导入预检"
        onCancel={() => {
          operationRef.current += 1;
          setPrecheck(null);
          setSkillResolutions({});
          setLoading(false);
          setImporting(false);
        }}
        onOk={() => void importAgent()}
        confirmLoading={importing}
        okText="导入并选择"
        okButtonProps={{
          disabled: !precheck || unresolvedDependencies.length > 0,
        }}
      >
        {unresolvedDependencies.length > 0 && (
          <Alert type="warning" title="依赖不完整，暂不能导入运行" />
        )}
        <ul>
          {precheck?.items.map((item) => (
            <li key={`${item.type}:${item.key}`}>
              {item.name}：
              {item.available ? "可用" : item.reason_code || "不可用"}
              {item.type === "skill" &&
                item.reason_code === "skill_duplicate" && (
                  <span className="ml-3 inline-flex gap-3">
                    <label>
                      <input
                        type="radio"
                        name={`skill-resolution-${item.key}`}
                        checked={
                          (skillResolutions[item.name] ?? "rename") === "rename"
                        }
                        onChange={() =>
                          setSkillResolutions((current) => ({
                            ...current,
                            [item.name]: "rename",
                          }))
                        }
                      />
                      重命名为 {item.suggested_new_name || `${item.name} 副本`}
                    </label>
                    <label>
                      <input
                        type="radio"
                        name={`skill-resolution-${item.key}`}
                        checked={skillResolutions[item.name] === "use_existing"}
                        onChange={() =>
                          setSkillResolutions((current) => ({
                            ...current,
                            [item.name]: "use_existing",
                          }))
                        }
                      />
                      使用已有 Skill
                    </label>
                  </span>
                )}
            </li>
          ))}
        </ul>
      </Modal>
    </Modal>
  );
}
