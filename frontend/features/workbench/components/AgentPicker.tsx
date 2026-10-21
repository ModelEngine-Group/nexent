// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { WorkbenchResourceDrawer } from "./WorkbenchResourceDrawer";
import { ResourceTagFilter } from "./ResourceTagFilter";
import { useResourceTags } from "../hooks/useResourceTags";
import { Bot } from "lucide-react";
import {
  AgentSelectionCard,
  AgentSelectionGrid,
  toLocalCard,
} from "@/components/resource-picker/AgentSelectionCard";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Empty, Modal, Spin, message } from "antd";
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
import { RESOURCE_PAGE_SIZE, resourcePage } from "./ResourcePagination";
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
  const [pageSize, setPageSize] = useState(RESOURCE_PAGE_SIZE);
  const [refreshRevision, setRefreshRevision] = useState(0);
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
    () => ({
      open,
      tab,
      search,
      page,
      pageSize,
      refreshRevision,
      predicates: repositoryTags.predicates,
    }),
    [
      open,
      tab,
      search,
      page,
      pageSize,
      refreshRevision,
      repositoryTags.predicates,
    ]
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
      page_size: repositoryRequest.pageSize,
      tag_predicates: repositoryRequest.predicates,
    })
      .then((result) => {
        if (!cancelled) {
          setRepository(result.items);
          setTotal(result.pagination?.total ?? result.items.length);
        }
      })
      .catch(() => {
        if (!cancelled)
          message.error(t("workbench.controls.repositoryLoadFailed"));
      })
      .finally(() => {
        if (!cancelled) setSettledRepositoryRequest(repositoryRequest);
      });
    return () => {
      cancelled = true;
    };
  }, [open, tab, repositoryRequest, t]);
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
        message.error(t("ui.localization.importPrecheckFailed"));
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
        throw new Error(t("ui.localization.importMissingAgent"));
      const refreshed = await fetchPublishedAgentList();
      if (operation !== operationRef.current) return;
      if (!refreshed.success)
        throw new Error(t("ui.localization.importRefreshFailed"));
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
        message.warning(t("ui.localization.importAgentNotReady"));
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
        message.error(
          error instanceof Error
            ? error.message
            : t("ui.localization.importFailed")
        );
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
  const visiblePageAgents = resourcePage(visible, page, pageSize);
  const selectablePageAgents = visiblePageAgents.filter(
    (agent) => agent.is_available !== false
  );
  const allSelected =
    selectablePageAgents.length > 0 &&
    selectablePageAgents.every((agent) =>
      draft.some((item) => item.id === agent.id)
    );
  return (
    <WorkbenchResourceDrawer
      listContent={
        <Spin
          spinning={loading}
          className="h-full [&>.ant-spin-container]:min-h-full"
        >
          <AgentSelectionGrid aria-label={t("ui.localization.agentResources")}>
            {(tab === "mine" ? visible.length : repository.length) === 0 && (
              <Empty className="py-12" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
            {tab === "mine"
              ? visiblePageAgents.map((agent) => (
                  <AgentSelectionCard
                    key={agent.id}
                    item={toLocalCard(agent)}
                    icon={<Bot size={20} />}
                    assignments={[]}
                    selected={draft.some((item) => item.id === agent.id)}
                    disabled={agent.is_available === false}
                    disabledReason={
                      agent.is_available === false
                        ? getUnavailableReasonLabels(
                            agent.unavailable_reasons || [],
                            t
                          ).join("；") ||
                          t("ui.localization.agentUnavailableWithoutReason")
                        : undefined
                    }
                    onToggle={() => toggle(agent)}
                  />
                ))
              : repository.map((item) => (
                  <AgentSelectionCard
                    key={item.agent_repository_id}
                    item={{
                      id: `repository:${item.agent_repository_id}`,
                      agentId: item.agent_id,
                      name: item.display_name || item.name,
                      description: item.description || "",
                      tags: item.tags,
                      version:
                        item.version_label ||
                        (item.version_no != null
                          ? String(item.version_no)
                          : undefined),
                      iconUrl: item.icon_url || undefined,
                    }}
                    icon={<Bot size={20} />}
                    selected={false}
                    disabled={loading || importing}
                    actions={
                      <Button
                        size="small"
                        disabled={loading || importing}
                        onClick={() => void check(item)}
                      >
                        {t("ui.localization.precheckImport")}
                      </Button>
                    }
                    onToggle={() => void check(item)}
                  />
                ))}
          </AgentSelectionGrid>
        </Spin>
      }
      picker={{
        searchPlaceholder: t(
          "agent.collaborative.selector.searchPlaceholder",
          "搜索智能体名称或描述"
        ),
        keyword: search,
        onSearch: (value) => {
          setSearch(value);
          setPage(1);
        },
        tagFilter: (
          <ResourceTagFilter filter={tags} onChange={() => setPage(1)} />
        ),
        listTitle: t("resourcePicker.list.agent", "智能体列表"),
        selected: draft.map((agent) => ({
          id: String(agent.id),
          label: agent.display_name || agent.name,
        })),
        onRemoveSelected: (id) =>
          setDraft((current) =>
            current.filter((agent) => String(agent.id) !== id)
          ),
        tabs: [
          { key: "mine", label: t("workbench.controls.mineTab", "我的") },
          {
            key: "repository",
            label: t("workbench.controls.repositoryTab", "仓库"),
          },
        ],
        activeTab: tab,
        onTabChange: (value) => {
          operationRef.current += 1;
          setPrecheck(null);
          setSkillResolutions({});
          setOperationLoading(false);
          setImporting(false);
          setTab(value);
          setPage(1);
        },
        total: tab === "repository" ? total : visible.length,
        page,
        pageSize,
        onPageSizeChange: (size) => {
          setPageSize(size);
          setPage(1);
        },
        onPageChange: setPage,
        onRefresh: () => {
          tags.retry?.();
          if (tab === "mine")
            void queryClient.invalidateQueries({
              queryKey: ["publishedAgentsList"],
            });
          else setRefreshRevision((value) => value + 1);
        },
        onSelectAll: (checked) => {
          const candidates = selectablePageAgents;
          const merged = [
            ...draft,
            ...candidates.filter(
              (agent) => !draft.some((item) => item.id === agent.id)
            ),
          ];
          if (checked && merged.length > (multiple ? 8 : 1)) {
            message.warning(
              t("workbench.controls.agentLimit", "最多选择 8 个智能体")
            );
            return;
          }
          setDraft((current) =>
            checked
              ? merged
              : current.filter(
                  (item) => !candidates.some((agent) => agent.id === item.id)
                )
          );
        },
        allSelected,
        partiallySelected:
          !allSelected &&
          selectablePageAgents.some((agent) =>
            draft.some((item) => item.id === agent.id)
          ),
        selectAllDisabled:
          loading ||
          saving ||
          tab !== "mine" ||
          selectablePageAgents.length === 0 ||
          (!multiple && selectablePageAgents.length > 1),
        refreshDisabled: loading || saving,
      }}

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
      <Modal
        open={!!precheck}
        title={t("workbench.import.precheckTitle", "导入预检")}
        onCancel={() => {
          operationRef.current += 1;
          setPrecheck(null);
          setSkillResolutions({});
          setOperationLoading(false);
          setImporting(false);
        }}
        onOk={() => void importAgent()}
        confirmLoading={importing}
        cancelText={t("common.cancel", "取消")}
        okText={t("workbench.import.importAndSelect", "导入并选择")}
        okButtonProps={{
          disabled: !precheck || unresolvedDependencies.length > 0,
        }}
      >
        {unresolvedDependencies.length > 0 && (
          <Alert
            type="warning"
            title={t("ui.localization.importDependenciesMissing")}
          />
        )}
        <ul>
          {precheck?.items.map((item) => (
            <li key={`${item.type}:${item.key}`}>
              {item.name}：
              {item.available
                ? t("ui.localization.available")
                : item.reason_code || t("ui.localization.unavailable")}
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
                      {t("ui.localization.renameTo")}{" "}
                      {item.suggested_new_name || `${item.name} 副本`}
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
                      {t("ui.localization.reuseSkill")}
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
