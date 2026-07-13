"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Button,
  Drawer,
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
import {
  CalendarClock,
  MessageCirclePlus,
  Pause,
  Pencil,
  Play,
  RefreshCw,
  Square,
  Trash2,
} from "lucide-react";

import { agentAutomationService } from "@/services/agentAutomationService";
import type {
  AgentAutomationRun,
  AgentAutomationTask,
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

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
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
  const [tasks, setTasks] = useState<AgentAutomationTask[]>([]);
  const [loading, setLoading] = useState(false);
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

  const loadTasks = async () => {
    setLoading(true);
    try {
      setTasks(await agentAutomationService.list());
    } catch (error: unknown) {
      message.error(errorMessage(error, "加载自动任务失败"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTasks();
  }, []);

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
      message.success("自动任务已更新");
      setModalOpen(false);
      setEditingTask(null);
      await loadTasks();
    } catch (error: unknown) {
      message.error(errorMessage(error, "更新自动任务失败"));
    }
  };

  const openRuns = async (task: AgentAutomationTask) => {
    setSelectedTask(task);
    setHistoryOpen(true);
    try {
      setRuns(await agentAutomationService.runs(task.task_id));
    } catch (error: unknown) {
      message.error(errorMessage(error, "加载运行历史失败"));
    }
  };

  const cancelRun = async (run: AgentAutomationRun) => {
    try {
      await agentAutomationService.cancelRun(run.run_id);
      message.success("运行已取消");
      if (selectedTask) {
        setRuns(await agentAutomationService.runs(selectedTask.task_id));
        await loadTasks();
      }
    } catch (error: unknown) {
      message.error(errorMessage(error, "取消运行失败"));
    }
  };

  const columns: ColumnsType<AgentAutomationTask> = [
    {
      title: "任务",
      dataIndex: "title",
      render: (_, task) => (
        <div className="min-w-0">
          <div className="font-medium truncate">{task.title}</div>
          <div className="text-xs text-gray-500 truncate">
            Agent #{task.agent_id} · 会话 #{task.conversation_id}
          </div>
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 140,
      render: (status) => (
        <Tag color={statusColor[status] || "default"}>{status}</Tag>
      ),
    },
    {
      title: "计划",
      width: 180,
      render: (_, task) => (
        <div className="text-sm">
          <div>{task.schedule_mode === "ONCE" ? "一次性" : "周期性"}</div>
          <div className="text-xs text-gray-500">
            {task.schedule_expr || task.schedule_rule_type}
          </div>
        </div>
      ),
    },
    {
      title: "下次执行",
      dataIndex: "next_fire_at",
      width: 220,
      render: (value) => (value ? new Date(value).toLocaleString() : "-"),
    },
    {
      title: "最近结果",
      width: 180,
      render: (_, task) => (
        <div className="text-sm">
          <div>{task.last_run_status || "-"}</div>
          {task.last_error && (
            <div className="text-xs text-red-500 truncate">
              {task.last_error}
            </div>
          )}
        </div>
      ),
    },
    {
      title: "操作",
      width: 260,
      render: (_, task) => (
        <Space>
          <Button
            size="small"
            icon={<Play size={14} />}
            onClick={() =>
              agentAutomationService.run(task.task_id).then(loadTasks)
            }
          >
            运行
          </Button>
          {task.status === "ACTIVE" ? (
            <Button
              size="small"
              icon={<Pause size={14} />}
              onClick={() =>
                agentAutomationService.pause(task.task_id).then(loadTasks)
              }
            />
          ) : ["PAUSED", "PAUSED_BY_SYSTEM"].includes(task.status) ? (
            <Button
              size="small"
              icon={<RefreshCw size={14} />}
              onClick={() =>
                agentAutomationService.resume(task.task_id).then(loadTasks)
              }
            />
          ) : null}
          <Button size="small" onClick={() => openRuns(task)}>
            历史
          </Button>
          <Button
            size="small"
            icon={<Pencil size={14} />}
            onClick={() => openEdit(task)}
          />
          <Button
            size="small"
            danger
            icon={<Trash2 size={14} />}
            onClick={() => {
              Modal.confirm({
                title: "删除自动任务",
                content: "删除任务不会删除绑定会话，但后续不会再自动执行。",
                onOk: async () => {
                  await agentAutomationService.delete(task.task_id);
                  await loadTasks();
                },
              });
            }}
          />
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
            <h1 className="text-xl font-semibold m-0">自动任务</h1>
            <p className="text-sm text-gray-500 m-0">
              任务由会话创建，并始终绑定创建它的会话
            </p>
          </div>
        </div>
        <Space>
          <Button icon={<RefreshCw size={16} />} onClick={loadTasks}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<MessageCirclePlus size={16} />}
            onClick={() => router.push(`/${params.locale}/chat`)}
          >
            通过会话创建
          </Button>
        </Space>
      </div>

      <Table
        rowKey="task_id"
        loading={loading}
        columns={columns}
        dataSource={tasks}
        pagination={{ pageSize: 10 }}
      />

      <Modal
        title="编辑自动任务"
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false);
          setEditingTask(null);
        }}
        onOk={submitTask}
        okText="保存"
        width={720}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="任务名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="Agent">
            <Input
              value={editingTask ? `Agent #${editingTask.agent_id}` : ""}
              disabled
            />
          </Form.Item>
          <Form.Item
            name="instruction"
            label="执行指令"
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={4} />
          </Form.Item>
          <Form.Item name="mode" label="任务类型" rules={[{ required: true }]}>
            <Select
              options={[
                { label: "一次性", value: "ONCE" },
                { label: "周期性", value: "RECURRING" },
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
                  label="首次执行时间"
                  rules={[{ required: true }]}
                >
                  <Input type="datetime-local" />
                </Form.Item>
                {getFieldValue("mode") === "RECURRING" && (
                  <>
                    <Form.Item
                      name="rule_type"
                      label="周期规则"
                      rules={[{ required: true }]}
                    >
                      <Select
                        options={[
                          { label: "Cron 表达式", value: "CRON" },
                          { label: "固定间隔", value: "INTERVAL" },
                        ]}
                      />
                    </Form.Item>
                    {getFieldValue("rule_type") === "INTERVAL" ? (
                      <Form.Item
                        name="interval_seconds"
                        label="间隔秒数"
                        rules={[{ required: true }]}
                      >
                        <InputNumber min={300} className="w-full" />
                      </Form.Item>
                    ) : (
                      <Form.Item
                        name="cron_expr"
                        label="Cron 表达式"
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
          <Form.Item name="timeout_seconds" label="超时时间（秒）">
            <InputNumber min={60} className="w-full" />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={selectedTask ? `运行历史：${selectedTask.title}` : "运行历史"}
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        width={720}
      >
        <Table
          rowKey="run_id"
          dataSource={runs}
          pagination={false}
          columns={[
            { title: "状态", dataIndex: "status", width: 120 },
            { title: "触发", dataIndex: "trigger_type", width: 120 },
            {
              title: "计划时间",
              dataIndex: "scheduled_fire_at",
              render: (value) =>
                value ? new Date(value).toLocaleString() : "-",
            },
            { title: "错误", dataIndex: "error_message" },
            {
              title: "操作",
              width: 100,
              render: (_, run) =>
                ["QUEUED", "RUNNING"].includes(run.status) ? (
                  <Button
                    size="small"
                    icon={<Square size={14} />}
                    onClick={() => cancelRun(run)}
                  >
                    取消
                  </Button>
                ) : null,
            },
          ]}
        />
      </Drawer>
    </div>
  );
}
