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
  Edit,
  Trash2,
  Maximize2,
  CircleCheck,
  CircleSlash,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { useAgentList } from "@/hooks/agent/useAgentList";
import { useGroupList } from "@/hooks/group/useGroupList";
import { deleteAgent, searchAgentInfo, updateAgentInfo } from "@/services/agentConfigService";
import { Agent } from "@/types/agentConfig";
import ExpandEditModal from "@/app/agents/components/agentInfo/ExpandEditModal";

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
};

// Fullscreen edit modal state interface
interface FullscreenEditState {
  visible: boolean;
  field: "description" | "duty_prompt" | "constraint_prompt" | "few_shots_prompt" | null;
  title: string;
  value: string;
}

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

  // Edit modal state
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentListRow | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  // Fullscreen edit modal state
  const [fullscreenEdit, setFullscreenEdit] = useState<FullscreenEditState>({
    visible: false,
    field: null,
    title: "",
    value: "",
  });

  const { agents, isLoading, refetch } = useAgentList({
    staleTime: 0, // Always fetch fresh data for admin view
  });

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
      const res = await deleteAgent(Number(agent.id));
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
      const res = await searchAgentInfo(Number(agent.id));
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

  const handleEditSubmit = async () => {
    if (!editingAgent) return;

    try {
      const values = await form.validateFields();
      setIsSaving(true);

      const groupIds = (values.group_ids || [])
        .map((id: unknown) => Number(id))
        .filter((id: number) => Number.isFinite(id));

      const res = await updateAgentInfo({
        agent_id: Number(editingAgent.id),
        name: editingAgent.name,
        display_name: values.display_name,
        description: values.description,
        duty_prompt: values.duty_prompt,
        constraint_prompt: values.constraint_prompt,
        few_shots_prompt: values.few_shots_prompt,
        group_ids: groupIds,
        author: editingAgent.author,
      });

      if (res.success) {
        message.success(t("businessLogic.config.message.agentSaveSuccess"));
        setEditModalVisible(false);
        queryClient.invalidateQueries({ queryKey: ["agents"] });
      } else {
        message.error(res.message || t("businessLogic.config.error.saveFailed"));
      }
    } catch (error) {
      message.error(t("businessLogic.config.error.saveFailed"));
    } finally {
      setIsSaving(false);
    }
  };

  const handleEditModalCancel = () => {
    setEditModalVisible(false);
    setEditingAgent(null);
    form.resetFields();
  };

  // Fullscreen edit handlers
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
    if (fullscreenEdit.field) {
      form.setFieldValue(fullscreenEdit.field, value);
    }
    setFullscreenEdit({ visible: false, field: null, title: "", value: "" });
  };

  const columns = [
    {
      title: t("agent.displayName"),
      dataIndex: "display_name",
      key: "display_name",
      width: "15%",
      render: (text: string) => <Text strong>{text}</Text>,
    },
    {
      title: t("agent.name"),
      dataIndex: "name",
      key: "name",
      width: "15%",
    },
    {
      title: t("agent.llmModel"),
      key: "llm_model",
      width: "20%",
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
      title: t("common.status"),
      key: "status",
      width: "15%",
      render: (_: unknown, record: AgentListRow) => {
        const isAvailable = record.is_available !== false;
        const reasons = Array.isArray(record.unavailable_reasons)
          ? record.unavailable_reasons.filter((r) => Boolean(r))
          : [];
        const reasonLabels = reasons.map((r) => getUnavailableReasonLabel(String(r)));

        return (
          <div className="flex items-center gap-2 min-w-0">
            {isAvailable ? (
              <Tag
                color="success"
                className="inline-flex items-center"
                variant="solid"
              >
                <CircleCheck className="mr-1" size={12} />
                {t("mcpConfig.status.available")}
              </Tag>
            ) : (
              <Tooltip
                title={reasonLabels.length > 0 ? reasonLabels.join(", ") : "-"}
                placement="top"
              >
                <Tag
                  color="error"
                  className="inline-flex items-center"
                  variant="solid"
                >
                  <CircleSlash className="mr-1" size={12} />
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
      width: "25%",
      render: (_: any, record: AgentListRow) => (
        <div className="flex items-center space-x-2">
          <Tooltip title={t("common.edit")}>
            <Button
              type="text"
              icon={<Edit className="h-4 w-4" />}
              onClick={() => openEditModal(record)}
              size="small"
            />
          </Tooltip>
          <Popconfirm
            title={t("businessLogic.config.modal.deleteTitle")}
            description={t("businessLogic.config.modal.deleteContent", { name: record.display_name })}
            onConfirm={() => handleDelete(record)}
            okText={t("common.delete")}
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
    <div className="flex flex-col">
      <div className="space-y-6">
        <div>
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

      {/* Edit Modal */}
      <Modal
        title={t("agent.action.modify")}
        open={editModalVisible}
        onOk={handleEditSubmit}
        onCancel={handleEditModalCancel}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        width={700}
        confirmLoading={isSaving}
        maskClosable={false}
      >
        <Spin spinning={isLoadingDetail}>
          <Form form={form} layout="vertical">
            <Form.Item
              name="display_name"
              label={t("agent.displayName")}
            >
              <Input placeholder={t("agent.displayNamePlaceholder")} />
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
                allowClear
              />
            </Form.Item>
          </Form>
        </Spin>
      </Modal>

      {/* Fullscreen Edit Modal */}
      <ExpandEditModal
        open={fullscreenEdit.visible}
        title={fullscreenEdit.title}
        content={fullscreenEdit.value}
        onClose={() => setFullscreenEdit({ visible: false, field: null, title: "", value: "" })}
        onSave={handleFullscreenSave}
      />
    </div>
  );
}
