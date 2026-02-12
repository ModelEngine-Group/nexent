"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Table,
  Button,
  App,
  Tooltip,
  Popconfirm,
  Typography,
  Tag,
  Modal,
  Form,
  Input,
  Select,
  Spin,
} from "antd";
import {
  Trash2,
  Maximize2,
  CheckCircle,
  CircleSlash,
  Clock,
  Eye,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { useAgentList } from "@/hooks/agent/useAgentList";
import { useGroupList } from "@/hooks/group/useGroupList";
import { deleteAgent, searchAgentInfo } from "@/services/agentConfigService";
import { fetchAgentVersionList } from "@/services/agentVersionService";
import { Agent } from "@/types/agentConfig";
import ExpandEditModal from "@/app/agents/components/agentInfo/ExpandEditModal";
import type { AgentVersion } from "@/services/agentVersionService";

const { Text } = Typography;
const { TextArea } = Input;

interface AgentDetail extends Agent {
  duty_prompt?: string;
  constraint_prompt?: string;
  few_shots_prompt?: string;
  group_ids?: number[];
}

type AgentListRow = Pick<
  Agent,
  "id" | "name" | "display_name" | "description" | "author" | "is_available" | "unavailable_reasons" | "group_ids"
> & {
  model_id?: number;
  model_name?: string;
  model_display_name?: string;
  is_published?: boolean;
  current_version_no?: number;
};


export default function AgentList({ tenantId }: { tenantId: string | null }) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const queryClient = useQueryClient();

  const getUnavailableReasonLabel = (reason: string) => {
    switch (reason) {
      case "duplicate_name":
        return t("agent.unavailableReasons.duplicate_name");
      case "duplicate_display_name":
        return t("agent.unavailableReasons.duplicate_display_name");
      case "tool_unavailable":
        return t("agent.unavailableReasons.tool_unavailable");
      case "model_unavailable":
        return t("agent.unavailableReasons.model_unavailable");
      default:
        return reason;
    }
  };

  // View modal state
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentListRow | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);

  // Fullscreen view modal state
  const [fullscreenEdit, setFullscreenEdit] = useState<{
    visible: boolean;
    field: "description" | "duty_prompt" | "constraint_prompt" | "few_shots_prompt" | null;
    title: string;
    value: string;
  }>({
    visible: false,
    field: null,
    title: "",
    value: "",
  });

  // Version list state for each agent
  const [agentVersions, setAgentVersions] = useState<Map<number, AgentVersion[]>>(new Map());
  const [loadingVersions, setLoadingVersions] = useState<Map<number, boolean>>(new Map());
  // Selected version for each agent (0 means current version)
  const [selectedVersions, setSelectedVersions] = useState<Map<number, number>>(new Map());

  const { agents, isLoading, refetch } = useAgentList(tenantId);

  // Fetch groups for group name mapping and selection
  const { data: groupData } = useGroupList(tenantId, 1, 100);
  const groups = groupData?.groups || [];

  // Create group name mapping
  const groupNameMap = useMemo(() => {
    const map = new Map<number, string>();
    groups.forEach((group) => {
      map.set(group.group_id, group.group_name);
    });
    return map;
  }, [groups]);

  // Get group names for agent
  const getGroupNames = (groupIds?: number[]) => {
    if (!groupIds || groupIds.length === 0) return [];
    return groupIds.map((id) => groupNameMap.get(id) || `Group ${id}`).filter(Boolean);
  };

  const handleDelete = async (agent: AgentListRow) => {
    try {
      // Agent ID is string in frontend type but number in backend service
      const res = await deleteAgent(Number(agent.id), tenantId ?? undefined);
      if (res.success) {
        message.success(t("businessLogic.config.error.agentDeleteSuccess"));
        queryClient.invalidateQueries({ queryKey: ["agents"] });
      } else {
        message.error(res.message || t("businessLogic.config.error.agentDeleteFailed"));
      }
    } catch (error) {
      message.error(t("common.unknownError"));
    }
  };

  const openEditModal = async (agent: AgentListRow) => {
    setEditingAgent(agent);
    setIsLoadingDetail(true);
    setEditModalVisible(true);

    try {
      const agentId = Number(agent.id);
      // Get selected version for this agent (default to 0 for current version)
      const selectedVersionNo = selectedVersions.get(agentId) ?? 0;
      const res = await searchAgentInfo(agentId, tenantId ?? undefined, selectedVersionNo);
      if (res.success && res.data) {
        const detail = res.data;
        setEditingAgent(agent);
        form.setFieldsValue({
          display_name: detail.display_name,
          description: detail.description,
          duty_prompt: detail.duty_prompt,
          constraint_prompt: detail.constraint_prompt,
          few_shots_prompt: detail.few_shots_prompt,
          group_ids: detail.group_ids || [],
        });
      } else {
        message.error(res.message || t("common.unknownError"));
        setEditModalVisible(false);
      }
    } catch (error) {
      message.error(t("common.unknownError"));
      setEditModalVisible(false);
    } finally {
      setIsLoadingDetail(false);
    }
  };

  const handleEditModalCancel = () => {
    setEditModalVisible(false);
    setEditingAgent(null);
    form.resetFields();
  };

  // Fullscreen view handlers
  const openFullscreenEdit = (
    field: "description" | "duty_prompt" | "constraint_prompt" | "few_shots_prompt",
    title: string
  ) => {
    const value = form.getFieldValue(field) || "";
    setFullscreenEdit({
      visible: true,
      field,
      title,
      value,
    });
  };

  const handleFullscreenSave = (value: string) => {
    // In view mode, don't save changes, just close
    setFullscreenEdit({ visible: false, field: null, title: "", value: "" });
  };

  // Load agent versions when dropdown is opened
  const handleVersionDropdownOpen = async (agentId: number, open: boolean) => {
    if (open && !agentVersions.has(agentId)) {
      setLoadingVersions(prev => new Map(prev).set(agentId, true));
      try {
        const res = await fetchAgentVersionList(agentId, tenantId ?? undefined);
        if (res.success && res.data) {
          setAgentVersions(prev => new Map(prev).set(agentId, res.data.items || []));
        } else {
          message.error(res.message || t("common.unknownError"));
        }
      } catch (error) {
        message.error(t("common.unknownError"));
      } finally {
        setLoadingVersions(prev => {
          const newMap = new Map(prev);
          newMap.delete(agentId);
          return newMap;
        });
      }
    }
  };

  const columns = [
    {
      title: t("agent.displayName"),
      dataIndex: "display_name",
      key: "display_name",
      width: "14%",
      render: (text: string) => <Text strong>{text}</Text>,
    },
    {
      title: t("agent.name"),
      dataIndex: "name",
      key: "name",
      width: "14%",
    },
    {
      title: t("agent.llmModel"),
      key: "llm_model",
      width: "18%",
      render: (_: unknown, record: AgentListRow) => {
        const primary = record.model_display_name || record.model_name || "-";
        const secondary = record.model_name || "";
        return (
          <div>
            <div className="font-medium">{primary}</div>
            {secondary ? (
              <div className="text-sm text-gray-500">{secondary}</div>
            ) : null}
          </div>
        );
      },
    },
    {
      title: t("agent.userGroup"),
      dataIndex: "group_ids",
      key: "group_names",
      width: "20%",
      render: (groupIds: number[]) => {
        const names = getGroupNames(groupIds);
        return (
          <div className="flex flex-wrap gap-1">
            {names.length > 0 ? (
              names.map((name, index) => (
                <Tag
                  key={index}
                  color="blue"
                  variant="outlined"
                >
                  {name}
                </Tag>
              ))
            ) : (
              <span className="text-gray-400">{t("agent.userGroup.empty")}</span>
            )}
          </div>
        );
      },
    },
    {
      title: t("agent.version"),
      key: "version",
      width: "10%",
      render: (_: unknown, record: AgentListRow) => {
        const agentId = Number(record.id);
        const versions = agentVersions.get(agentId) || [];
        const isLoading = loadingVersions.get(agentId) || false;
        // Default to 0 (current version) if not selected
        const selectedVersionNo = selectedVersions.has(agentId)
          ? selectedVersions.get(agentId)!
          : 0;

        // Build options: current version (0) first, then other versions
        const options = [
          {
            label: t("agent.version.current"),
            value: 0,
          },
          ...versions.map((version) => ({
            label: version.version_name,
            value: version.version_no,
          })),
        ];

        return (
          <Select
            placeholder={t("agent.version.current")}
            value={selectedVersionNo}
            loading={isLoading}
            onDropdownVisibleChange={(open) => handleVersionDropdownOpen(agentId, open)}
            onChange={(value) => {
              setSelectedVersions(prev => new Map(prev).set(agentId, value));
            }}
            style={{ width: "100%" }}
            options={options}
          />
        );
      },
    },
    {
      title: t("common.status"),
      key: "status",
      width: "10%",
      render: (_: unknown, record: AgentListRow) => {
        const isPublished = record.is_published === true;

        // If not published, only show unpublished status
        if (!isPublished) {
          return (
            <div className="flex items-center gap-2 min-w-0">
              <Tag
                color="#AEB6BF"
                className="inline-flex items-center"
                variant="solid"
              >
                <Clock className="w-3 h-3 mr-1" />
                {t("agent.status.unpublished")}
              </Tag>
            </div>
          );
        }

        // If published, show available/unavailable status
        const isAvailable = record.is_available !== false;
        const reasons = Array.isArray(record.unavailable_reasons)
          ? record.unavailable_reasons.filter((r) => Boolean(r))
          : [];
        const reasonLabels = reasons.map((r) => getUnavailableReasonLabel(String(r)));

        return (
          <div className="flex items-center gap-2 min-w-0">
            {isAvailable ? (
              <Tag
                color="#229954"
                className="inline-flex items-center"
                variant="solid"
              >
                <CheckCircle className="w-3 h-3 mr-1" />
                {t("mcpConfig.status.available")}
              </Tag>
            ) : (
              <Tooltip
                title={reasonLabels.length > 0 ? reasonLabels.join(", ") : "-"}
                placement="top"
              >
                <Tag
                  color="#E74C3C"
                  className="inline-flex items-center"
                  variant="solid"
                >
                  <CircleSlash className="w-3.5 h-3 mr-1" />
                  {t("mcpConfig.status.unavailable")}
                </Tag>
              </Tooltip>
            )}
          </div>
        );
      },
    },
    {
      title: t("common.actions"),
      key: "action",
      width: "14%",
      render: (_: any, record: AgentListRow) => (
        <div className="flex items-center space-x-2">
          <Tooltip title={t("agent.action.view")}>
            <Button
              type="text"
              icon={<Eye className="h-4 w-4" />}
              onClick={() => openEditModal(record)}
              size="small"
            />
          </Tooltip>
          <Popconfirm
            title={t("businessLogic.config.modal.deleteTitle")}
            description={t("businessLogic.config.modal.deleteContent", { name: record.display_name })}
            onConfirm={() => handleDelete(record)}
            okText={t("common.confirm")}
            cancelText={t("common.cancel")}
          >
            <Tooltip title={t("common.delete")}>
              <Button
                type="text"
                danger
                icon={<Trash2 className="h-4 w-4" />}
                size="small"
              />
            </Tooltip>
          </Popconfirm>
        </div>
      ),
    },
  ];

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="space-y-6 flex-1 overflow-auto">
        <div className="min-w-0">
          <Table
            columns={columns}
            dataSource={agents as AgentListRow[]}
            rowKey="id"
            loading={isLoading}
            size="small"
            pagination={{ pageSize: 10 }}
            locale={{ emptyText: t("space.noAgents") }}
            scroll={{ x: true }}
          />
        </div>
      </div>

      {/* View Modal */}
      <Modal
        title={t("agent.action.view")}
        open={editModalVisible}
        onCancel={handleEditModalCancel}
        footer={[
          <Button key="close" onClick={handleEditModalCancel}>
            {t("common.cancel")}
          </Button>
        ]}
        width={700}
        maskClosable={false}
      >
        <Spin spinning={isLoadingDetail}>
          <Form form={form} layout="vertical">
            <Form.Item
              name="display_name"
              label={t("agent.displayName")}
            >
              <Input placeholder={t("agent.displayNamePlaceholder")} readOnly />
            </Form.Item>

            <Form.Item
              noStyle
              shouldUpdate
            >
              {() => (
                <Form.Item
                  name="description"
                  label={t("agent.description")}
                >
                  <div style={{ position: "relative" }}>
                    <TextArea
                      value={form.getFieldValue("description")}
                      placeholder={t("agent.descriptionPlaceholder")}
                      autoSize={{ minRows: 4, maxRows: 6 }}
                      style={{ resize: "none", paddingRight: 32 }}
                      readOnly
                    />
                    <Tooltip title={t("common.fullscreen")}>
                      <Button
                        type="text"
                        icon={<Maximize2 className="h-4 w-4" />}
                        onClick={() => openFullscreenEdit("description", t("agent.description"))}
                        style={{
                          position: "absolute",
                          right: 4,
                          top: 4,
                          padding: 4,
                        }}
                      />
                    </Tooltip>
                  </div>
                </Form.Item>
              )}
            </Form.Item>

            <Form.Item
              noStyle
              shouldUpdate
            >
              {() => (
                <Form.Item
                  name="duty_prompt"
                  label={t("systemPrompt.card.duty.title")}
                >
                  <div style={{ position: "relative" }}>
                    <TextArea
                      value={form.getFieldValue("duty_prompt")}
                      placeholder={t("agent.dutyPromptPlaceholder")}
                      autoSize={{ minRows: 5, maxRows: 8 }}
                      style={{ resize: "none", paddingRight: 32 }}
                      readOnly
                    />
                    <Tooltip title={t("common.fullscreen")}>
                      <Button
                        type="text"
                        icon={<Maximize2 className="h-4 w-4" />}
                        onClick={() => openFullscreenEdit("duty_prompt", t("systemPrompt.card.duty.title"))}
                        style={{
                          position: "absolute",
                          right: 4,
                          top: 4,
                          padding: 4,
                        }}
                      />
                    </Tooltip>
                  </div>
                </Form.Item>
              )}
            </Form.Item>

            <Form.Item
              noStyle
              shouldUpdate
            >
              {() => (
                <Form.Item
                  name="constraint_prompt"
                  label={t("systemPrompt.card.constraint.title")}
                >
                  <div style={{ position: "relative" }}>
                    <TextArea
                      value={form.getFieldValue("constraint_prompt")}
                      placeholder={t("agent.constraintPromptPlaceholder")}
                      autoSize={{ minRows: 5, maxRows: 8 }}
                      style={{ resize: "none", paddingRight: 32 }}
                      readOnly
                    />
                    <Tooltip title={t("common.fullscreen")}>
                      <Button
                        type="text"
                        icon={<Maximize2 className="h-4 w-4" />}
                        onClick={() => openFullscreenEdit("constraint_prompt", t("systemPrompt.card.constraint.title"))}
                        style={{
                          position: "absolute",
                          right: 4,
                          top: 4,
                          padding: 4,
                        }}
                      />
                    </Tooltip>
                  </div>
                </Form.Item>
              )}
            </Form.Item>

            <Form.Item
              noStyle
              shouldUpdate
            >
              {() => (
                <Form.Item
                  name="few_shots_prompt"
                  label={t("systemPrompt.card.fewShots.title")}
                >
                  <div style={{ position: "relative" }}>
                    <TextArea
                      value={form.getFieldValue("few_shots_prompt")}
                      placeholder={t("agent.fewShotsPromptPlaceholder")}
                      autoSize={{ minRows: 5, maxRows: 8 }}
                      style={{ resize: "none", paddingRight: 32 }}
                      readOnly
                    />
                    <Tooltip title={t("common.fullscreen")}>
                      <Button
                        type="text"
                        icon={<Maximize2 className="h-4 w-4" />}
                        onClick={() => openFullscreenEdit("few_shots_prompt", t("systemPrompt.card.fewShots.title"))}
                        style={{
                          position: "absolute",
                          right: 4,
                          top: 4,
                          padding: 4,
                        }}
                      />
                    </Tooltip>
                  </div>
                </Form.Item>
              )}
            </Form.Item>

            <Form.Item
              name="group_ids"
              label={t("agent.userGroup")}
            >
              <Select
                mode="multiple"
                placeholder={t("agent.userGroup")}
                options={groups.map((group) => ({
                  label: group.group_name,
                  value: group.group_id,
                }))}
                open={false}
                onDropdownVisibleChange={() => false}
                onClick={(e) => e.preventDefault()}
                onFocus={(e) => e.target.blur()}
                tagRender={(props) => {
                  const { label } = props;
                  return (
                    <Tag
                      style={{
                        margin: "2px",
                        border: "1px solid #d9d9d9",
                      }}
                    >
                      {label}
                    </Tag>
                  );
                }}
              />
            </Form.Item>
          </Form>
        </Spin>
      </Modal>

      {/* Fullscreen View Modal */}
      <ExpandEditModal
        open={fullscreenEdit.visible}
        title={fullscreenEdit.title}
        content={fullscreenEdit.value}
        onClose={() => setFullscreenEdit({ visible: false, field: null, title: "", value: "" })}
        onSave={handleFullscreenSave}
        readOnly={true}
      />
    </div>
  );
}
