"use client";

import React, { useEffect, useState, useCallback, useMemo } from "react";
import {
  Drawer,
  Button,
  Spin,
  Select,
  Tag,
  App as AntdApp,
  Collapse,
  Alert,
  type CollapseProps,
} from "antd";
import {
  Bot,
  Wrench,
  Puzzle,
  Settings2,
  ArrowRight,
  BookOpen,
  Plug,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { SolutionCardData } from "./SolutionMarketCard";
import {
  searchAgentInfo,
  searchToolConfig,
  updateToolConfig,
  updateAgentInfo,
  fetchSkills,
  fetchSkillInstances,
  saveSkillInstance,
  type UpdateAgentInfoPayload,
} from "@/services/agentConfigService";
import { getMcpServerList, updateMcpServer } from "@/services/mcpService";
import { useModelList } from "@/hooks/model/useModelList";
import { useKnowledgeBasesForToolConfig } from "@/hooks/useKnowledgeBaseSelector";
import type { Agent, ToolParam, McpServer, Skill } from "@/types/agentConfig";
import type { ModelOption } from "@/types/modelConfig";
import OfficialBadge from "./OfficialBadge";
import log from "@/lib/logger";

interface SolutionConfigDrawerProps {
  open: boolean;
  solution: SolutionCardData | null;
  onClose: () => void;
  onChat?: (solution: SolutionCardData) => void;
}

export function SolutionConfigDrawer({
  open,
  solution,
  onClose,
  onChat,
}: SolutionConfigDrawerProps) {
  const { i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";
  const { message } = AntdApp.useApp();

  const [agentDetail, setAgentDetail] = useState<Agent | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState<string>("");

  const { availableLlmModels } = useModelList();
  const [selectedModelIds, setSelectedModelIds] = useState<number[]>([]);

  // MCP server list for the MCP config section
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [loadingMcp, setLoadingMcp] = useState(false);
  const [mcpEdits, setMcpEdits] = useState<
    Record<number, { url?: string; token?: string | null }>
  >({});

  const kbTool = useMemo(() => {
    if (!agentDetail?.tools) return null;
    return (
      agentDetail.tools.find(
        (t) =>
          t.origin_name === "knowledge_base_search" ||
          t.name === "knowledge_base_search"
      ) || null
    );
  }, [agentDetail]);

  const kbToolId = kbTool ? Number(kbTool.id) : null;
  const agentId = agentDetail ? Number(agentDetail.id) : null;

  const { data: knowledgeBases, isLoading: loadingKbs } =
    useKnowledgeBasesForToolConfig(kbTool ? "knowledge_base_search" : null);

  const [toolConfigs, setToolConfigs] = useState<
    Record<
      number,
      { params: Record<string, unknown>; enabled: boolean; loading: boolean }
    >
  >({});

  const [saving, setSaving] = useState(false);

  // Skill state
  const [allSkills, setAllSkills] = useState<Skill[]>([]);
  const [skillInstances, setSkillInstances] = useState<
    Record<
      string,
      { enabled: boolean; config_values?: Record<string, unknown> | null }
    >
  >({});
  const [loadingSkills, setLoadingSkills] = useState(false);

  // Load agent detail
  useEffect(() => {
    if (!open || !solution?.agent_id) {
      setAgentDetail(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    setDetailError("");
    searchAgentInfo(solution.agent_id)
      .then((res) => {
        if (cancelled) return;
        if (res.success && res.data) {
          setAgentDetail(res.data);
          setSelectedModelIds(res.data.model_ids || []);
        } else {
          setDetailError(res.message || "Failed to load");
        }
      })
      .catch((err) => {
        log.error("SolutionConfigDrawer: load agent detail failed", err);
        if (!cancelled) setDetailError(String(err?.message || err));
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, solution?.agent_id]);

  // Load tool configs
  useEffect(() => {
    if (!agentDetail || !agentId) return;
    const toolsWithParams = (agentDetail.tools || []).filter(
      (t) => t.initParams && t.initParams.length > 0
    );
    if (toolsWithParams.length === 0) return;

    let cancelled = false;
    toolsWithParams.forEach(async (tool) => {
      const tid = Number(tool.id);
      setToolConfigs((prev) => ({
        ...prev,
        [tid]: { params: {}, enabled: true, loading: true },
      }));
      try {
        const res = await searchToolConfig(tid, agentId);
        if (cancelled) return;
        setToolConfigs((prev) => ({
          ...prev,
          [tid]: {
            params: res.data?.params || {},
            enabled: res.data?.enabled ?? true,
            loading: false,
          },
        }));
      } catch (err) {
        log.error("SolutionConfigDrawer: load tool config failed", err);
        if (cancelled) return;
        setToolConfigs((prev) => ({
          ...prev,
          [tid]: { params: {}, enabled: true, loading: false },
        }));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [agentDetail, agentId]);

  // Load MCP server list
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadingMcp(true);
    getMcpServerList()
      .then((res) => {
        if (cancelled) return;
        if (res?.success) {
          setMcpServers((res.data ?? []) as McpServer[]);
        }
      })
      .catch((err) => {
        log.error("SolutionConfigDrawer: load MCP servers failed", err);
      })
      .finally(() => {
        if (!cancelled) setLoadingMcp(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  // Load skills (global list + agent instances)
  useEffect(() => {
    if (!open || !agentId) return;
    let cancelled = false;
    setLoadingSkills(true);
    Promise.all([fetchSkills(), fetchSkillInstances(agentId)])
      .then(([skillsRes, instancesRes]) => {
        if (cancelled) return;
        if (skillsRes?.success) setAllSkills(skillsRes.data ?? []);
        if (instancesRes?.success) {
          const map: Record<
            string,
            { enabled: boolean; config_values?: Record<string, unknown> | null }
          > = {};
          (instancesRes.data ?? []).forEach(
            (inst: {
              skill_id: string;
              enabled: boolean;
              config_values: Record<string, unknown> | null;
            }) => {
              map[String(inst.skill_id)] = {
                enabled: inst.enabled ?? true,
                config_values: inst.config_values ?? null,
              };
            }
          );
          setSkillInstances(map);
        }
      })
      .catch((err) => {
        log.error("SolutionConfigDrawer: load skills failed", err);
      })
      .finally(() => {
        if (!cancelled) setLoadingSkills(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, agentId]);

  // Agent's skills: match agentDetail.skills (or skill_names) to global skill list
  const agentSkillIds = useMemo(() => {
    if (!agentDetail) return [];
    // agentDetail.skills is Skill[] with skill_id
    if (Array.isArray(agentDetail.skills) && agentDetail.skills.length > 0) {
      return agentDetail.skills.map((s) => String(s.skill_id));
    }
    return [];
  }, [agentDetail]);

  const agentSkills = useMemo(() => {
    if (agentSkillIds.length === 0) return [];
    return allSkills.filter((s) => agentSkillIds.includes(String(s.skill_id)));
  }, [allSkills, agentSkillIds]);

  // Derived: separate local tools from MCP tools
  const localTools = useMemo(() => {
    if (!agentDetail?.tools) return [];
    return agentDetail.tools.filter((t) => t.source !== "mcp");
  }, [agentDetail]);

  // Tools that actually have user-configurable params (the ones rendered in
  // the Tool Configuration list). Kept in sync with the badge count.
  const toolsWithParams = useMemo(() => {
    return localTools.filter(
      (t) =>
        t.initParams &&
        t.initParams.length > 0 &&
        t.origin_name !== "knowledge_base_search"
    );
  }, [localTools]);

  const mcpToolsFromAgent = useMemo(() => {
    if (!agentDetail?.tools) return [];
    return agentDetail.tools.filter((t) => t.source === "mcp");
  }, [agentDetail]);

  // Match agent's MCP tools to MCP server records
  const agentMcpServers = useMemo(() => {
    if (mcpToolsFromAgent.length === 0 || mcpServers.length === 0) return [];
    return mcpServers.filter((srv) =>
      mcpToolsFromAgent.some((t) => {
        const tName = t.origin_name || t.name || "";
        const sName = srv.service_name || "";
        return (
          tName === sName || tName.includes(sName) || sName.includes(tName)
        );
      })
    );
  }, [mcpToolsFromAgent, mcpServers]);

  const handleSave = useCallback(async () => {
    if (!agentDetail || !agentId) return;
    setSaving(true);
    try {
      // 1. Save LLM model selection
      const payload: UpdateAgentInfoPayload = { agent_id: agentId };
      if (selectedModelIds.length > 0) {
        payload.model_ids = selectedModelIds;
      }
      await updateAgentInfo(payload);

      // 2. Save local tool configs
      const toolUpdatePromises = Object.entries(toolConfigs).map(
        async ([tidStr, cfg]) => {
          const tid = Number(tidStr);
          if (!tid) return;
          if (Object.keys(cfg.params).length === 0) return;
          return updateToolConfig(tid, agentId, cfg.params, cfg.enabled);
        }
      );
      await Promise.all(toolUpdatePromises);

      // 3. Save MCP server edits (url/token)
      const mcpUpdatePromises = Object.entries(mcpEdits).map(
        async ([mcpIdStr, edit]) => {
          const mcpId = Number(mcpIdStr);
          if (!mcpId) return;
          const srv = mcpServers.find((s) => s.mcp_id === mcpId);
          if (!srv) return;
          return updateMcpServer(
            mcpId,
            srv.service_name,
            edit.url ?? srv.mcp_url,
            edit.token ?? srv.authorization_token ?? null,
            srv.custom_headers ?? null,
            null,
            undefined
          );
        }
      );
      await Promise.all(mcpUpdatePromises);

      // 4. Save skill instances (enable/disable + config values)
      const skillUpdatePromises = Object.entries(skillInstances).map(
        async ([skillIdStr, cfg]) => {
          const skillId = Number(skillIdStr);
          if (!skillId || !agentId) return;
          return saveSkillInstance(
            skillId,
            agentId,
            cfg.enabled,
            0,
            cfg.config_values ?? undefined
          );
        }
      );
      await Promise.all(skillUpdatePromises);

      message.success(isZh ? "配置已保存" : "Configuration saved");
    } catch (err: unknown) {
      log.error("SolutionConfigDrawer: save failed", err);
      message.error(
        isZh
          ? `保存失败：${(err as Error)?.message || "未知错误"}`
          : `Save failed: ${(err as Error)?.message || "unknown"}`
      );
    } finally {
      setSaving(false);
    }
  }, [
    agentDetail,
    agentId,
    selectedModelIds,
    toolConfigs,
    mcpEdits,
    mcpServers,
    skillInstances,
    message,
    isZh,
  ]);

  const handleStartChat = useCallback(() => {
    if (!solution) return;
    onChat?.(solution);
    onClose();
  }, [solution, onChat, onClose]);

  // ---- Section renderers ----

  const renderOverview = () => {
    if (!solution) return null;
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
            {solution.display_name}
          </h2>
          {solution.source === "official" && (
            <OfficialBadge text={isZh ? "官方" : "Official"} />
          )}
        </div>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          {solution.description}
        </p>
        <div className="flex flex-wrap gap-1.5">
          {solution.tags?.map((tag) => (
            <Tag key={tag.id} className="text-xs">
              {tag.display_name}
            </Tag>
          ))}
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
          <span className="inline-flex items-center gap-1">
            <Bot className="h-3.5 w-3.5" />
            {solution.agent_count || 1} {isZh ? "Agent" : "Agent"}
          </span>
          {(solution.skill_count || 0) > 0 && (
            <span className="inline-flex items-center gap-1">
              <Puzzle className="h-3.5 w-3.5" />
              {solution.skill_count} {isZh ? "Skill" : "Skill"}
            </span>
          )}
          {(solution.mcp_count || 0) > 0 && (
            <span className="inline-flex items-center gap-1">
              <Wrench className="h-3.5 w-3.5" />
              {solution.mcp_count} MCP
            </span>
          )}
        </div>
      </div>
    );
  };

  // ---- LLM Config Panel ----

  const renderLlmConfig = () => {
    if (!agentDetail) return null;
    return (
      <div className="space-y-3 px-1">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-slate-500 dark:text-slate-400 flex items-center gap-1">
            <Bot className="h-3.5 w-3.5" />
            {isZh ? "LLM 模型" : "LLM Model"}
          </label>
          <Select
            mode="multiple"
            value={selectedModelIds}
            onChange={setSelectedModelIds}
            className="w-full"
            placeholder={isZh ? "选择模型..." : "Select models..."}
            options={availableLlmModels.map((m: ModelOption) => ({
              value: m.id,
              label: m.displayName || m.name,
            }))}
            notFoundContent={isZh ? "暂无可用模型" : "No models available"}
          />
        </div>
        {kbTool && renderKnowledgeBaseSelector()}
      </div>
    );
  };

  const renderKnowledgeBaseSelector = () => {
    if (!kbTool) return null;
    const cfg = kbToolId ? toolConfigs[kbToolId] : null;
    const selectedKbIds: string[] = Array.isArray(
      cfg?.params?.knowledge_base_ids
    )
      ? (cfg!.params!.knowledge_base_ids as string[])
      : Array.isArray(cfg?.params?.index_names)
        ? (cfg!.params!.index_names as string[])
        : [];

    const handleKbChange = (ids: string[]) => {
      if (!kbToolId) return;
      setToolConfigs((prev) => ({
        ...prev,
        [kbToolId]: {
          ...(prev[kbToolId] || { params: {}, enabled: true, loading: false }),
          params: {
            ...(prev[kbToolId]?.params || {}),
            knowledge_base_ids: ids,
          },
          enabled: true,
          loading: false,
        },
      }));
    };

    return (
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-slate-500 dark:text-slate-400 flex items-center gap-1">
          <BookOpen className="h-3.5 w-3.5" />
          {isZh ? "知识库" : "Knowledge Base"}
        </label>
        {loadingKbs ? (
          <Spin size="small" />
        ) : (
          <Select
            mode="multiple"
            value={selectedKbIds}
            onChange={handleKbChange}
            className="w-full"
            placeholder={isZh ? "选择知识库..." : "Select knowledge bases..."}
            options={(knowledgeBases || []).map((kb) => ({
              value: kb.id,
              label: kb.display_name || kb.name,
            }))}
            notFoundContent={isZh ? "暂无知识库" : "No knowledge bases"}
          />
        )}
      </div>
    );
  };

  // ---- Tool Config Panel ----

  const renderToolConfig = () => {
    if (!agentDetail?.tools) {
      return (
        <p className="text-xs text-slate-400 px-1">
          {isZh ? "无本地工具" : "No local tools"}
        </p>
      );
    }
    const toolsWithParamsList = toolsWithParams;
    if (toolsWithParamsList.length === 0) {
      return (
        <p className="text-xs text-slate-400 px-1">
          {isZh ? "无可配置的工具参数" : "No tool parameters to configure"}
        </p>
      );
    }

    return (
      <Collapse
        ghost
        items={toolsWithParamsList.map((tool) => {
          const tid = Number(tool.id);
          const cfg = toolConfigs[tid];
          return {
            key: String(tid),
            label: (
              <div className="flex items-center gap-2">
                <Wrench className="h-3.5 w-3.5 text-slate-400" />
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {tool.name}
                </span>
                {cfg?.loading && <Spin size="small" />}
              </div>
            ),
            children: (
              <div className="space-y-3 px-2">
                {(tool.initParams || []).map((param: ToolParam) => (
                  <ToolParamInput
                    key={param.name}
                    param={param}
                    value={cfg?.params?.[param.name]}
                    onChange={(val) => {
                      setToolConfigs((prev) => ({
                        ...prev,
                        [tid]: {
                          ...(prev[tid] || {
                            params: {},
                            enabled: true,
                            loading: false,
                          }),
                          params: {
                            ...(prev[tid]?.params || {}),
                            [param.name]: val,
                          },
                          enabled: true,
                          loading: false,
                        },
                      }));
                    }}
                  />
                ))}
              </div>
            ),
          };
        })}
      />
    );
  };

  // ---- MCP Config Panel ----

  // ---- Skill Config Panel ----

  const renderSkillConfig = () => {
    if (loadingSkills) {
      return (
        <div className="flex items-center justify-center py-4">
          <Spin size="small" />
        </div>
      );
    }

    if (agentSkills.length === 0) {
      return (
        <p className="text-xs text-slate-400 px-1">
          {isZh ? "无 Skill" : "No skills"}
        </p>
      );
    }

    return (
      <div className="space-y-2 px-1">
        {agentSkills.map((skill) => {
          const sid = String(skill.skill_id);
          const cfg = skillInstances[sid];
          const enabled = cfg?.enabled ?? true;
          return (
            <div
              key={sid}
              className="flex items-center justify-between p-2 rounded-md border border-slate-200 dark:border-slate-600"
            >
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <Puzzle className="h-3.5 w-3.5 text-slate-400 shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate">
                    {skill.name}
                  </p>
                  <p className="text-xs text-slate-400 dark:text-slate-500 truncate">
                    {skill.description}
                  </p>
                </div>
              </div>
              <Select
                size="small"
                value={enabled ? "enabled" : "disabled"}
                onChange={(v) => {
                  const newEnabled = v === "enabled";
                  setSkillInstances((prev) => ({
                    ...prev,
                    [sid]: {
                      ...(prev[sid] || {}),
                      enabled: newEnabled,
                      config_values: prev[sid]?.config_values ?? null,
                    },
                  }));
                }}
                className="w-20 shrink-0"
                options={[
                  { value: "enabled", label: isZh ? "启用" : "On" },
                  { value: "disabled", label: isZh ? "停用" : "Off" },
                ]}
              />
            </div>
          );
        })}
      </div>
    );
  };

  const renderMcpConfig = () => {
    if (loadingMcp) {
      return (
        <div className="flex items-center justify-center py-4">
          <Spin size="small" />
        </div>
      );
    }

    if (agentMcpServers.length === 0) {
      return (
        <p className="text-xs text-slate-400 px-1">
          {isZh ? "无 MCP 连接器" : "No MCP connectors"}
        </p>
      );
    }

    return (
      <Collapse
        ghost
        items={agentMcpServers.map((srv) => {
          const edit = mcpEdits[srv.mcp_id] || {};
          const url = edit.url ?? srv.mcp_url ?? "";
          const token = edit.token ?? srv.authorization_token ?? "";
          return {
            key: String(srv.mcp_id),
            label: (
              <div className="flex items-center gap-2">
                <Plug
                  className={`h-3.5 w-3.5 ${srv.status ? "text-green-500" : "text-slate-400"}`}
                />
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {srv.service_name}
                </span>
                <Tag
                  className={`text-xs ${srv.status ? "text-green-600" : "text-slate-400"}`}
                >
                  {srv.status
                    ? isZh
                      ? "已连接"
                      : "Connected"
                    : isZh
                      ? "未连接"
                      : "Offline"}
                </Tag>
              </div>
            ),
            children: (
              <div className="space-y-3 px-2">
                <div className="space-y-1">
                  <label className="text-xs text-slate-600 dark:text-slate-300">
                    {isZh ? "服务地址" : "Server URL"}
                  </label>
                  <input
                    type="text"
                    value={url}
                    onChange={(e) =>
                      setMcpEdits((prev) => ({
                        ...prev,
                        [srv.mcp_id]: {
                          ...prev[srv.mcp_id],
                          url: e.target.value,
                        },
                      }))
                    }
                    className="w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-600 rounded dark:bg-slate-800 dark:text-slate-100"
                    placeholder="https://..."
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-slate-600 dark:text-slate-300">
                    {isZh ? "认证 Token" : "Auth Token"}
                  </label>
                  <input
                    type="password"
                    value={token || ""}
                    onChange={(e) =>
                      setMcpEdits((prev) => ({
                        ...prev,
                        [srv.mcp_id]: {
                          ...prev[srv.mcp_id],
                          token: e.target.value,
                        },
                      }))
                    }
                    className="w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-600 rounded dark:bg-slate-800 dark:text-slate-100"
                    placeholder={isZh ? "可选" : "Optional"}
                  />
                </div>
              </div>
            ),
          };
        })}
      />
    );
  };

  // ---- Collapse panels ----

  const collapseItems: CollapseProps["items"] = [
    {
      key: "llm",
      label: (
        <div className="flex items-center gap-2">
          <Bot className="h-4 w-4 text-slate-500" />
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            {isZh ? "LLM 配置" : "LLM Configuration"}
          </span>
        </div>
      ),
      children: renderLlmConfig(),
    },
    {
      key: "tools",
      label: (
        <div className="flex items-center gap-2">
          <Wrench className="h-4 w-4 text-slate-500" />
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            {isZh ? "工具配置" : "Tool Configuration"}
          </span>
          {toolsWithParams.length > 0 && (
            <Tag className="text-xs">{toolsWithParams.length}</Tag>
          )}
        </div>
      ),
      children: renderToolConfig(),
    },
    {
      key: "skills",
      label: (
        <div className="flex items-center gap-2">
          <Puzzle className="h-4 w-4 text-slate-500" />
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            {isZh ? "Skill 配置" : "Skill Configuration"}
          </span>
          {agentSkills.length > 0 && (
            <Tag className="text-xs">{agentSkills.length}</Tag>
          )}
        </div>
      ),
      children: renderSkillConfig(),
    },
    {
      key: "mcp",
      label: (
        <div className="flex items-center gap-2">
          <Plug className="h-4 w-4 text-slate-500" />
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            {isZh ? "MCP 配置" : "MCP Configuration"}
          </span>
          {agentMcpServers.length > 0 && (
            <Tag className="text-xs">{agentMcpServers.length}</Tag>
          )}
        </div>
      ),
      children: renderMcpConfig(),
    },
  ];

  return (
    <Drawer
      title={
        <div className="flex items-center gap-2">
          <Settings2 className="h-4 w-4 text-slate-600 dark:text-slate-300" />
          <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {isZh ? "方案配置" : "Solution Configuration"}
          </span>
        </div>
      }
      open={open}
      onClose={onClose}
      width={480}
      footer={
        <div className="flex items-center gap-2">
          <Button onClick={onClose} className="flex-1">
            {isZh ? "取消" : "Cancel"}
          </Button>
          <Button onClick={handleSave} loading={saving} className="flex-1">
            {isZh ? "保存配置" : "Save"}
          </Button>
          <Button
            onClick={handleStartChat}
            type="primary"
            className="flex-1"
            icon={<ArrowRight className="h-3.5 w-3.5" />}
            iconPosition="end"
          >
            {isZh ? "开始对话" : "Start chat"}
          </Button>
        </div>
      }
    >
      {loadingDetail ? (
        <div className="flex items-center justify-center py-20">
          <Spin size="large" />
        </div>
      ) : detailError ? (
        <Alert
          type="error"
          message={isZh ? "加载失败" : "Failed to load"}
          description={detailError}
          showIcon
        />
      ) : solution ? (
        <div className="space-y-5">
          {renderOverview()}
          <Collapse
            items={collapseItems}
            defaultActiveKey={["llm"]}
            className="solution-config-collapse"
          />
        </div>
      ) : null}
    </Drawer>
  );
}

function ToolParamInput({
  param,
  value,
  onChange,
}: {
  param: ToolParam;
  value: unknown;
  onChange: (val: unknown) => void;
}) {
  const { i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";
  const label = (isZh ? param.description_zh : param.description) || param.name;

  if (param.type === "boolean") {
    return (
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-600 dark:text-slate-300">
          {label}
        </span>
        <Select
          size="small"
          value={
            value === true ? "true" : value === false ? "false" : undefined
          }
          onChange={(v) => onChange(v === "true")}
          className="w-24"
          options={[
            { value: "true", label: isZh ? "是" : "true" },
            { value: "false", label: isZh ? "否" : "false" },
          ]}
          placeholder={isZh ? "选择..." : "Select..."}
        />
      </div>
    );
  }

  if (param.type === "number") {
    return (
      <div className="space-y-1">
        <label className="text-xs text-slate-600 dark:text-slate-300">
          {label}
          {param.required && <span className="text-red-500"> *</span>}
        </label>
        <input
          type="number"
          value={value as number | string | undefined}
          onChange={(e) => onChange(e.target.valueAsNumber)}
          className="w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-600 rounded dark:bg-slate-800 dark:text-slate-100"
          placeholder={param.default || ""}
        />
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <label className="text-xs text-slate-600 dark:text-slate-300">
        {label}
        {param.required && <span className="text-red-500"> *</span>}
      </label>
      <input
        type="text"
        value={
          typeof value === "string" ? value : value ? JSON.stringify(value) : ""
        }
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-600 rounded dark:bg-slate-800 dark:text-slate-100"
        placeholder={param.default || ""}
      />
    </div>
  );
}

export default SolutionConfigDrawer;
