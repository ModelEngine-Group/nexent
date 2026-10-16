"use client";

import { WorkbenchResourceDrawer } from "./WorkbenchResourceDrawer";
import { ResourceTagFilter } from "./ResourceTagFilter";
import { useResourceTags } from "../hooks/useResourceTags";
import { ResourceSelectionActions } from "./ResourceSelectionActions";
import { SelectedResourceTags } from "./SelectedResourceTags";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Empty, Input, Modal, Spin, Tabs, message } from "antd";
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
import { ResourceSelectionRow } from "./ResourceSelectionRow";
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
  disabled = false,
}: {
  open: boolean;
  agents: Agent[];
  selectedId?: string;
  selectedIds?: string[];
  onCancel: () => void;
  onSelect: (agent: Agent) => void;
  onConfirm?: (agents: Agent[]) => Promise<void> | void;
  multiple?: boolean;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<Agent[]>(() => {
    const ids = selectedIds ?? (selectedId ? [selectedId] : []);
    return open
      ? ids
          .map((id) => agents.find((agent) => String(agent.id) === id))
          .filter((agent): agent is Agent => Boolean(agent))
      : [];
  });
  const [saving, setSaving] = useState(false);
  const [previousOpen, setPreviousOpen] = useState(open);
  const toggle = (agent: Agent) => {
    if (disabled || saving) return;
    if (
      !draft.some((item) => item.id === agent.id) &&
      multiple &&
      draft.length >= 8
    ) {
      message.warning(
        t("workbench.controls.agentLimit", "最多选择 8 个智能体")
      );
      return;
    }
    setDraft((current) =>
      current.some((item) => item.id === agent.id)
        ? current.filter((item) => item.id !== agent.id)
        : multiple
          ? [...current, agent]
          : [agent]
    );
  };
  const [search, setSearch] = useState("");
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const [tab, setTab] = useState("mine");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [repository, setRepository] = useState<AgentRepositoryListingItem[]>(
    []
  );
  const [operationLoading, setOperationLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [precheck, setPrecheck] =
    useState<RepositoryImportPrecheckResponse | null>(null);
  const [skillResolutions, setSkillResolutions] = useState<
    Record<string, "rename" | "use_existing">
  >({});
  const operationRef = useRef(0);
  const mineTags = useResourceTags(
    open,
    "agent",
    agents.map((agent) => String(agent.id)),
    tab !== "mine"
  );
  const repositoryTags = useResourceTags(open, "agent", [], true);
  const tags = tab === "mine" ? mineTags : repositoryTags;
  const repositoryRequest = useMemo(
    () => ({ open, tab, search, page, predicates: repositoryTags.predicates }),
    [open, tab, search, page, repositoryTags.predicates]
  );
  const [settledRepositoryRequest, setSettledRepositoryRequest] = useState<
    typeof repositoryRequest | null
  >(null);
  const loading =
    operationLoading ||
    (open &&
      tab === "repository" &&
      settledRepositoryRequest !== repositoryRequest);
  // Reset session state before children render, rather than after commit.
  if (previousOpen !== open) {
    setPreviousOpen(open);
    if (open) {
      const ids = selectedIds ?? (selectedId ? [selectedId] : []);
      setDraft(
        ids
          .map((id) => agents.find((agent) => String(agent.id) === id))
          .filter((agent): agent is Agent => Boolean(agent))
      );
    } else {
      setPrecheck(null);
      setSkillResolutions({});
      setImporting(false);
      setOperationLoading(false);
      setSearch("");
      setPage(1);
    }
  }
  useEffect(() => {
    if (!open) operationRef.current += 1;
  }, [open]);
  useEffect(() => {
    if (!open || tab !== "repository") return;
    let cancelled = false;
    void fetchAgentRepositoryListings({
      status: "shared",
      search: repositoryRequest.search,
      page: repositoryRequest.page,
      page_size: RESOURCE_PAGE_SIZE,
      tag_predicates: repositoryRequest.predicates,
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
        if (!cancelled) setSettledRepositoryRequest(repositoryRequest);
      });
    return () => {
      cancelled = true;
    };
  }, [open, tab, repositoryRequest]);
  const check = async (item: AgentRepositoryListingItem) => {
    const operation = ++operationRef.current;
    setOperationLoading(true);
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
      if (operation === operationRef.current) setOperationLoading(false);
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
      if (
        multiple &&
        draft.length >= 8 &&
        !draft.some((item) => item.id === imported.id)
      ) {
        message.warning(
          t("workbench.controls.agentLimit", "最多选择 8 个智能体")
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
      agents.filter(
        (agent) =>
          (!mineTags.visibleIds || mineTags.visibleIds.has(String(agent.id))) &&
          [agent.name, agent.display_name, agent.description].some((value) =>
            value?.toLowerCase().includes(search.trim().toLowerCase())
          )
      ),
    [agents, search, mineTags.visibleIds]
  );
  return (
    <WorkbenchResourceDrawer
      listContent={
        <Spin
          spinning={loading}
          className="h-full [&>.ant-spin-container]:min-h-full"
        >
          <div role="listbox" aria-label="智能体资源" className="min-h-full">
            {(tab === "mine" ? visible.length : repository.length) === 0 && (
              <Empty className="py-12" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
            {tab === "mine"
              ? resourcePage(visible, page).map((agent) => (
                  <ResourceSelectionRow
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
                    onClick={() => toggle(agent)}
                  />
                ))
              : repository.map((item) => (
                  <ResourceSelectionRow
                    key={item.agent_repository_id}
                    title={item.display_name || item.name}
                    description={item.description ?? undefined}
                    tags={item.tags}
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
          </div>
        </Spin>
      }
      pagination={
        <ResourcePagination
          current={page}
          total={tab === "repository" ? total : visible.length}
          onChange={setPage}
          disabled={loading || importing}
        />
      }
      open={open}
      title={t("workbench.controls.agents", "智能体")}
      saving={saving}
      disabled={disabled}
      confirmDisabled={
        loading || importing || (!!tags.predicates.length && tags.loading)
      }
      onCancel={() => {
        operationRef.current += 1;
        setPrecheck(null);
        setSkillResolutions({});
        setOperationLoading(false);
        setImporting(false);
        onCancel();
      }}
      onConfirm={async () => {
        if (disabled || saving || loading || importing) return;
        if (draft.length > (multiple ? 8 : 1)) {
          message.warning(
            t("workbench.controls.agentLimit", "最多选择 8 个智能体")
          );
          return;
        }
        setSaving(true);
        try {
          if (onConfirm) await onConfirm(draft);
          else draft.forEach((agent) => onSelect(agent));
          onCancel();
        } catch (error) {
          message.error(
            error instanceof Error
              ? error.message
              : t("workbench.controls.selectionFailed", "选择失败")
          );
        } finally {
          setSaving(false);
        }
      }}
    >
      <Tabs
        activeKey={tab}
        onChange={(value) => {
          operationRef.current += 1;
          setPrecheck(null);
          setSkillResolutions({});
          setOperationLoading(false);
          setImporting(false);
          setTab(value);
          setPage(1);
        }}
        items={[
          { key: "mine", label: "我的" },
          { key: "repository", label: "仓库" },
        ]}
      />
      <ResourceTagFilter
        filter={tags}
        onChange={() => setPage(1)}
        search={
          <Input.Search
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            placeholder="搜索智能体名称或描述"
            allowClear
          />
        }
      />
      <p className="text-xs text-muted-foreground">
        {t("workbench.controls.installedNotice")}
      </p>
      {
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
            pageOnly
            toggleAllDisabled={
              tab !== "mine" ||
              (!multiple &&
                resourcePage(visible, page).filter(
                  (agent) => agent.is_available !== false
                ).length > 1)
            }
            allSelected={
              resourcePage(visible, page).filter(
                (agent) => agent.is_available !== false
              ).length > 0 &&
              resourcePage(visible, page)
                .filter((agent) => agent.is_available !== false)
                .every((agent) => draft.some((item) => item.id === agent.id))
            }
            hasSelection={draft.length > 0}
            disabled={loading || saving}
            empty={!visible.some((agent) => agent.is_available !== false)}
            onClear={() => setDraft([])}
            onToggleAll={() => {
              const candidates = resourcePage(visible, page).filter(
                (agent) => agent.is_available !== false
              );
              const merged = new Set([
                ...draft.map((agent) => agent.id),
                ...candidates.map((agent) => agent.id),
              ]);
              if (
                merged.size > (multiple ? 8 : 1) &&
                !candidates.every((agent) =>
                  draft.some((item) => item.id === agent.id)
                )
              ) {
                message.warning(
                  t("workbench.controls.agentLimit", "最多选择 8 个智能体")
                );
                return;
              }
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
                        (agent) => !current.some((item) => item.id === agent.id)
                      ),
                    ]
              );
            }}
          />
        </div>
      }
      <Modal
        open={!!precheck}
        title="导入预检"
        onCancel={() => {
          operationRef.current += 1;
          setPrecheck(null);
          setSkillResolutions({});
          setOperationLoading(false);
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
    </WorkbenchResourceDrawer>
  );
}
