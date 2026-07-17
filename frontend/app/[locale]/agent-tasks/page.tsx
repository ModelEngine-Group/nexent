"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  Button,
  Drawer,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TableProps } from "antd";
import type { MenuProps } from "antd";
import {
  CalendarClock,
  History,
  MessageCirclePlus,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  RefreshCw,
  Search,
  Square,
  Trash2,
} from "lucide-react";

import { agentAutomationService } from "@/services/agentAutomationService";
import { getAutomationErrorMessage } from "@/features/agentAutomation/errorMessage";
import type {
  AgentAutomationRun,
  AgentAutomationTask,
  AutomationTaskStatus,
  UpdateAutomationTaskPayload,
} from "@/types/agentAutomation";

const statusColor: Record<string, string> = {
  ACTIVE: "green",
  PAUSED: "gold",
  PAUSED_BY_SYSTEM: "red",
  COMPLETED: "blue",
};

interface TaskFormValues {
  title: string;
  instruction: string;
  mode: "ONCE" | "RECURRING";
  rule_type: "INTERVAL" | "CRON";
  start_at: string;
  cron_expr?: string;
  interval_seconds?: number;
  timeout_seconds?: number;
}

function toLocalInputValue(date: Date) {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function buildPatchPayload(
  values: TaskFormValues
): UpdateAutomationTaskPayload {
  const mode = values.mode;
  const startAt = new Date(values.start_at).toISOString();
  const timezone =
    Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
  const scheduleTrigger =
    mode === "ONCE"
      ? {
          mode: "ONCE" as const,
          rule_type: "AT" as const,
          timezone,
          start_at: startAt,
          max_fire_count: 1,
        }
      : values.rule_type === "INTERVAL"
        ? {
            mode: "RECURRING" as const,
            rule_type: "INTERVAL" as const,
            timezone,
            start_at: startAt,
            interval_seconds: values.interval_seconds,
          }
        : {
            mode: "RECURRING" as const,
            rule_type: "CRON" as const,
            timezone,
            start_at: startAt,
            cron_expr: values.cron_expr,
          };

  return {
    title: values.title,
    instruction: values.instruction,
    schedule_trigger: scheduleTrigger,
    timeout_seconds: values.timeout_seconds || 1800,
  };
}

function taskToFormValues(task: AgentAutomationTask) {
  const trigger = task.schedule_config;
  return {
    title: task.title,
    agent_id: task.agent_id,
    instruction: task.instruction,
    mode: trigger.mode,
    rule_type: trigger.rule_type === "AT" ? "CRON" : trigger.rule_type,
    start_at: toLocalInputValue(new Date(trigger.start_at)),
    cron_expr: trigger.cron_expr || "0 9 * * *",
    interval_seconds: trigger.interval_seconds || 3600,
    timeout_seconds: task.timeout_seconds || 1800,
  };
}

export default function AgentTasksPage() {
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const { t, i18n } = useTranslation("common");
  const [tasks, setTasks] = useState<AgentAutomationTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [taskNameSearch, setTaskNameSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<
    AutomationTaskStatus | undefined
  >();
  const [modalOpen, setModalOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selectedTask, setSelectedTask] = useState<AgentAutomationTask | null>(
    null
  );
  const [editingTask, setEditingTask] = useState<AgentAutomationTask | null>(
    null
  );
  const [runs, setRuns] = useState<AgentAutomationRun[]>([]);
  const [form] = Form.useForm();
  const loadRequestIdRef = useRef(0);

  const formatDateTime = (value?: string | null) =>
    value
      ? new Intl.DateTimeFormat(
          i18n.language.startsWith("zh") ? "zh-CN" : "en-US",
          {
            dateStyle: "medium",
            timeStyle: "medium",
          }
        ).format(new Date(value))
      : "-";

  const formatTaskStatus = (status: string) =>
    t(`agentAutomation.status.${status}`, { defaultValue: status });

  const formatRunStatus = (status?: string | null) =>
    status
      ? t(`agentAutomation.runStatus.${status}`, { defaultValue: status })
      : "-";

  const formatTriggerType = (triggerType: string) =>
    t(`agentAutomation.triggerType.${triggerType}`, {
      defaultValue: triggerType,
    });

  const formatScheduleDetail = (task: AgentAutomationTask) => {
    const trigger = task.schedule_config;
    if (trigger.rule_type === "AT") {
      return formatDateTime(trigger.start_at);
    }
    if (trigger.rule_type === "INTERVAL") {
      return t("agentAutomation.page.everySeconds", {
        count: trigger.interval_seconds,
      });
    }
    return t("agentAutomation.page.cronSchedule", {
      expression: trigger.cron_expr,
    });
  };

  const loadTasks = useCallback(async () => {
    const requestId = ++loadRequestIdRef.current;
    setLoading(true);
    try {
      const loadedTasks = await agentAutomationService.list({
        status: statusFilter,
        search: taskNameSearch,
      });
      if (requestId === loadRequestIdRef.current) {
        setTasks(loadedTasks);
      }
    } catch (error: unknown) {
      if (requestId === loadRequestIdRef.current) {
        message.error(
          getAutomationErrorMessage(error, t, "agentAutomation.page.loadFailed")
        );
      }
    } finally {
      if (requestId === loadRequestIdRef.current) {
        setLoading(false);
      }
    }
  }, [statusFilter, taskNameSearch, t]);

  useEffect(() => {
    void loadTasks();
  }, [loadTasks]);

  const handleTableChange: TableProps<AgentAutomationTask>["onChange"] = (
    _pagination,
    filters
  ) => {
    const nextTaskName = filters.title?.[0];
    const nextStatus = filters.status?.[0];
    setTaskNameSearch(
      typeof nextTaskName === "string" ? nextTaskName.trim() : ""
    );
    setStatusFilter(
      typeof nextStatus === "string"
        ? (nextStatus as AutomationTaskStatus)
        : undefined
    );
  };

  const openEdit = (task: AgentAutomationTask) => {
    setEditingTask(task);
    form.setFieldsValue(taskToFormValues(task));
    setModalOpen(true);
  };

  const submitTask = async () => {
    if (!editingTask) return;
    const values = (await form.validateFields()) as TaskFormValues;
    try {
      await agentAutomationService.update(
        editingTask.task_id,
        buildPatchPayload(values)
      );
      message.success(t("agentAutomation.page.updateSuccess"));
      setModalOpen(false);
      setEditingTask(null);
      await loadTasks();
    } catch (error: unknown) {
      message.error(
        getAutomationErrorMessage(error, t, "agentAutomation.page.updateFailed")
      );
    }
  };

  const openRuns = async (task: AgentAutomationTask) => {
    setSelectedTask(task);
    setHistoryOpen(true);
    try {
      setRuns(await agentAutomationService.runs(task.task_id));
    } catch (error: unknown) {
      message.error(
        getAutomationErrorMessage(
          error,
          t,
          "agentAutomation.page.historyLoadFailed"
        )
      );
    }
  };

  const cancelRun = async (run: AgentAutomationRun) => {
    try {
      await agentAutomationService.cancelRun(run.run_id);
      message.success(t("agentAutomation.page.cancelRunSuccess"));
      if (selectedTask) {
        setRuns(await agentAutomationService.runs(selectedTask.task_id));
        await loadTasks();
      }
    } catch (error: unknown) {
      message.error(
        getAutomationErrorMessage(
          error,
          t,
          "agentAutomation.page.cancelRunFailed"
        )
      );
    }
  };

  const confirmDeleteRun = (run: AgentAutomationRun) => {
    Modal.confirm({
      title: t("agentAutomation.page.deleteRunTitle"),
      content: t("agentAutomation.page.deleteRunDescription"),
      okText: t("agentAutomation.page.deleteRunConfirm"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await agentAutomationService.deleteRun(run.run_id);
          message.success(t("agentAutomation.page.deleteRunSuccess"));
          if (selectedTask) {
            setRuns(await agentAutomationService.runs(selectedTask.task_id));
            await loadTasks();
          }
        } catch (error: unknown) {
          message.error(
            getAutomationErrorMessage(
              error,
              t,
              "agentAutomation.page.deleteRunFailed"
            )
          );
        }
      },
    });
  };

  const runTask = async (task: AgentAutomationTask) => {
    try {
      await agentAutomationService.run(task.task_id);
      message.success(t("agentAutomation.page.runSuccess"));
      await loadTasks();
    } catch (error) {
      message.error(
        getAutomationErrorMessage(error, t, "agentAutomation.page.runFailed")
      );
    }
  };

  const pauseTask = async (task: AgentAutomationTask) => {
    try {
      await agentAutomationService.pause(task.task_id);
      message.success(t("agentAutomation.page.pauseSuccess"));
      await loadTasks();
    } catch (error) {
      message.error(
        getAutomationErrorMessage(error, t, "agentAutomation.page.pauseFailed")
      );
    }
  };

  const resumeTask = async (task: AgentAutomationTask) => {
    try {
      await agentAutomationService.resume(task.task_id);
      message.success(t("agentAutomation.page.resumeSuccess"));
      await loadTasks();
    } catch (error) {
      message.error(
        getAutomationErrorMessage(error, t, "agentAutomation.page.resumeFailed")
      );
    }
  };

  const deleteTask = async (task: AgentAutomationTask) => {
    try {
      await agentAutomationService.delete(task.task_id);
      message.success(t("agentAutomation.page.deleteSuccess"));
      await loadTasks();
    } catch (error) {
      message.error(
        getAutomationErrorMessage(error, t, "agentAutomation.page.deleteFailed")
      );
      throw error;
    }
  };

  const confirmDeleteTask = (task: AgentAutomationTask) => {
    Modal.confirm({
      title: t("agentAutomation.page.deleteTitle"),
      content: t("agentAutomation.page.deleteDescription"),
      okText: t("agentAutomation.page.delete"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: () => deleteTask(task),
    });
  };

  const getMoreActionItems = (
    task: AgentAutomationTask
  ): MenuProps["items"] => [
    {
      key: "history",
      icon: <History size={14} aria-hidden />,
      label: t("agentAutomation.page.history"),
      onClick: () => openRuns(task),
    },
    {
      key: "edit",
      icon: <Pencil size={14} aria-hidden />,
      label: t("agentAutomation.page.edit"),
      onClick: () => openEdit(task),
    },
    { type: "divider" },
    {
      key: "delete",
      danger: true,
      icon: <Trash2 size={14} aria-hidden />,
      label: t("agentAutomation.page.delete"),
      onClick: () => confirmDeleteTask(task),
    },
  ];

  const columns: ColumnsType<AgentAutomationTask> = [
    {
      title: t("agentAutomation.page.task"),
      dataIndex: "title",
      filteredValue: taskNameSearch ? [taskNameSearch] : null,
      filterIcon: (filtered) => (
        <Search
          size={14}
          className={filtered ? "text-blue-600" : "text-gray-500"}
        />
      ),
      filterDropdown: ({ selectedKeys, setSelectedKeys, confirm, close }) => (
        <div
          className="w-72 p-3"
          onKeyDown={(event) => event.stopPropagation()}
        >
          <Input
            autoFocus
            allowClear
            value={String(selectedKeys[0] || "")}
            placeholder={t("agentAutomation.page.taskSearchPlaceholder")}
            onChange={(event) =>
              setSelectedKeys(event.target.value ? [event.target.value] : [])
            }
            onPressEnter={() => confirm()}
          />
          <div className="mt-3 flex justify-end gap-2">
            <Button
              size="small"
              onClick={() => {
                setSelectedKeys([]);
                confirm();
              }}
            >
              {t("agentAutomation.page.reset")}
            </Button>
            <Button size="small" onClick={() => close()}>
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              size="small"
              icon={<Search size={14} />}
              onClick={() => confirm()}
            >
              {t("agentAutomation.page.search")}
            </Button>
          </div>
        </div>
      ),
      render: (_, task) => (
        <div className="min-w-0">
          <Link
            href={`/${params.locale}/chat?conversation_id=${task.conversation_id}`}
            className="block w-fit max-w-full truncate font-medium text-blue-600 hover:text-blue-700 hover:underline"
            title={t("agentAutomation.page.openConversation")}
          >
            {task.title}
          </Link>
          <div className="text-xs text-gray-500 truncate">
            {t("agentAutomation.page.agentConversation", {
              agentName:
                task.agent_name ||
                t("agentAutomation.page.agentFallback", {
                  agentId: task.agent_id,
                }),
              agentId: task.agent_id,
              conversationId: task.conversation_id,
            })}
          </div>
        </div>
      ),
    },
    {
      title: t("agentAutomation.page.status"),
      dataIndex: "status",
      width: 140,
      filters: [
        "DRAFT",
        "ACTIVE",
        "PAUSED",
        "PAUSED_BY_SYSTEM",
        "COMPLETED",
      ].map((status) => ({ text: formatTaskStatus(status), value: status })),
      filteredValue: statusFilter ? [statusFilter] : null,
      filterMultiple: false,
      render: (status) => (
        <Tag color={statusColor[status] || "default"}>
          {formatTaskStatus(status)}
        </Tag>
      ),
    },
    {
      title: t("agentAutomation.page.schedule"),
      width: 180,
      render: (_, task) => (
        <div className="text-sm">
          <div>
            {task.schedule_mode === "ONCE"
              ? t("agentAutomation.page.once")
              : t("agentAutomation.page.recurring")}
          </div>
          <div className="text-xs text-gray-500">
            {formatScheduleDetail(task)}
          </div>
        </div>
      ),
    },
    {
      title: t("agentAutomation.page.nextFireAt"),
      dataIndex: "next_fire_at",
      width: 220,
      render: (value) => formatDateTime(value),
    },
    {
      title: t("agentAutomation.page.lastResult"),
      width: 180,
      render: (_, task) => (
        <div className="text-sm">
          <div>{formatRunStatus(task.last_run_status)}</div>
          {task.last_error && (
            <div className="text-xs text-red-500 truncate">
              {task.last_error}
            </div>
          )}
        </div>
      ),
    },
    {
      title: t("agentAutomation.page.actions"),
      width: 280,
      render: (_, task) => (
        <Space>
          <Button
            size="small"
            icon={<Play size={14} />}
            onClick={() => runTask(task)}
          >
            {t("agentAutomation.page.run")}
          </Button>
          {task.status === "ACTIVE" ? (
            <Button
              size="small"
              icon={<Pause size={14} />}
              onClick={() => pauseTask(task)}
            >
              {t("agentAutomation.page.pause")}
            </Button>
          ) : ["PAUSED", "PAUSED_BY_SYSTEM"].includes(task.status) ? (
            <Button
              size="small"
              icon={<RefreshCw size={14} />}
              onClick={() => resumeTask(task)}
            >
              {t("agentAutomation.page.resume")}
            </Button>
          ) : null}
          <Dropdown
            menu={{ items: getMoreActionItems(task) }}
            trigger={["click"]}
            placement="bottomRight"
          >
            <Button
              size="small"
              icon={<MoreHorizontal size={14} />}
              title={t("agentAutomation.page.moreActions")}
              aria-label={t("agentAutomation.page.moreActions")}
            />
          </Dropdown>
        </Space>
      ),
    },
  ];

  return (
    <div className="w-full h-full p-8 bg-white overflow-auto">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <CalendarClock size={24} />
          <div>
            <h1 className="text-xl font-semibold m-0">
              {t("agentAutomation.page.title")}
            </h1>
            <p className="text-sm text-gray-500 m-0">
              {t("agentAutomation.page.subtitle")}
            </p>
          </div>
        </div>
        <Space>
          <Button icon={<RefreshCw size={16} />} onClick={loadTasks}>
            {t("common.refresh")}
          </Button>
          <Button
            type="primary"
            icon={<MessageCirclePlus size={16} />}
            onClick={() => router.push(`/${params.locale}/chat`)}
          >
            {t("agentAutomation.page.createInChat")}
          </Button>
        </Space>
      </div>

      <Table
        rowKey="task_id"
        loading={loading}
        columns={columns}
        dataSource={tasks}
        onChange={handleTableChange}
        pagination={{ pageSize: 10 }}
        locale={{ emptyText: t("agentAutomation.page.empty") }}
      />

      <Modal
        title={t("agentAutomation.page.editorTitle")}
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false);
          setEditingTask(null);
        }}
        onOk={submitTask}
        okText={t("common.save")}
        cancelText={t("common.cancel")}
        width={720}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="title"
            label={t("agentAutomation.page.taskName")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item label={t("agentAutomation.page.agent")}>
            <Input
              value={
                editingTask
                  ? t("agentAutomation.page.agentValue", {
                      agentName:
                        editingTask.agent_name ||
                        t("agentAutomation.page.agentFallback", {
                          agentId: editingTask.agent_id,
                        }),
                      agentId: editingTask.agent_id,
                    })
                  : ""
              }
              disabled
            />
          </Form.Item>
          <Form.Item
            name="instruction"
            label={t("agentAutomation.page.instruction")}
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={4} />
          </Form.Item>
          <Form.Item
            name="mode"
            label={t("agentAutomation.page.taskType")}
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { label: t("agentAutomation.page.once"), value: "ONCE" },
                {
                  label: t("agentAutomation.page.recurring"),
                  value: "RECURRING",
                },
              ]}
            />
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(prev, cur) =>
              prev.mode !== cur.mode || prev.rule_type !== cur.rule_type
            }
          >
            {({ getFieldValue }) => (
              <>
                <Form.Item
                  name="start_at"
                  label={t("agentAutomation.page.firstRunAt")}
                  rules={[{ required: true }]}
                >
                  <Input type="datetime-local" />
                </Form.Item>
                {getFieldValue("mode") === "RECURRING" && (
                  <>
                    <Form.Item
                      name="rule_type"
                      label={t("agentAutomation.page.ruleType")}
                      rules={[{ required: true }]}
                    >
                      <Select
                        options={[
                          {
                            label: t("agentAutomation.page.cron"),
                            value: "CRON",
                          },
                          {
                            label: t("agentAutomation.page.interval"),
                            value: "INTERVAL",
                          },
                        ]}
                      />
                    </Form.Item>
                    {getFieldValue("rule_type") === "INTERVAL" ? (
                      <Form.Item
                        name="interval_seconds"
                        label={t("agentAutomation.page.intervalSeconds")}
                        rules={[{ required: true }]}
                      >
                        <InputNumber min={5} className="w-full" />
                      </Form.Item>
                    ) : (
                      <Form.Item
                        name="cron_expr"
                        label={t("agentAutomation.page.cronExpression")}
                        rules={[{ required: true }]}
                      >
                        <Input placeholder="0 9 * * *" />
                      </Form.Item>
                    )}
                  </>
                )}
              </>
            )}
          </Form.Item>
          <Form.Item
            name="timeout_seconds"
            label={t("agentAutomation.page.timeoutSeconds")}
          >
            <InputNumber min={60} className="w-full" />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={
          selectedTask
            ? t("agentAutomation.page.historyTitleWithTask", {
                title: selectedTask.title,
              })
            : t("agentAutomation.page.historyTitle")
        }
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        width={720}
      >
        <Table
          rowKey="run_id"
          dataSource={runs}
          pagination={false}
          columns={[
            {
              title: t("agentAutomation.page.status"),
              dataIndex: "status",
              width: 120,
              render: (value) => formatRunStatus(value),
            },
            {
              title: t("agentAutomation.page.trigger"),
              dataIndex: "trigger_type",
              width: 120,
              render: (value) => formatTriggerType(value),
            },
            {
              title: t("agentAutomation.page.scheduledAt"),
              dataIndex: "scheduled_fire_at",
              render: (value) => formatDateTime(value),
            },
            {
              title: t("agentAutomation.page.errorLog"),
              dataIndex: "error_message",
              render: (value) => value || "-",
            },
            {
              title: t("agentAutomation.page.actions"),
              width: 130,
              render: (_, run) => {
                const isActive = ["QUEUED", "RUNNING"].includes(run.status);
                return isActive ? (
                  <Button
                    size="small"
                    icon={<Square size={14} />}
                    onClick={() => cancelRun(run)}
                  >
                    {t("agentAutomation.page.cancelRun")}
                  </Button>
                ) : (
                  <Button
                    size="small"
                    danger
                    icon={<Trash2 size={14} />}
                    onClick={() => confirmDeleteRun(run)}
                  >
                    {t("agentAutomation.page.deleteRun")}
                  </Button>
                );
              },
            },
          ]}
          locale={{ emptyText: t("agentAutomation.page.noRuns") }}
        />
      </Drawer>
    </div>
  );
}
