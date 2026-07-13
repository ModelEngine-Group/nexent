"use client";

import { Button, Space, Tag } from "antd";
import { CalendarClock, Settings } from "lucide-react";

import type { AgentAutomationProposalData } from "@/types/agentAutomation";

interface AutomationProposalCardProps {
  proposal: AgentAutomationProposalData;
  onConfirm?: () => void;
  onEdit?: () => void;
  onConfigureAgent?: () => void;
  confirming?: boolean;
}

export default function AutomationProposalCard({
  proposal,
  onConfirm,
  onEdit,
  onConfigureAgent,
  confirming = false,
}: AutomationProposalCardProps) {
  const matched = proposal.capability_resolution?.matched_capabilities || [];
  const missing = proposal.capability_resolution?.missing_capabilities || [];

  return (
    <div className="border border-gray-200 rounded-md p-4 bg-white">
      <div className="flex items-start gap-3">
        <CalendarClock size={20} className="mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="font-medium">
            {proposal.task?.title || "自动任务提案"}
          </div>
          <div className="text-sm text-gray-600 mt-1 whitespace-pre-wrap">
            {proposal.task?.instruction}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {matched.map((capability) => (
              <Tag
                key={capability.binding_ref || capability.name}
                color="green"
              >
                {capability.display_name || capability.name}
              </Tag>
            ))}
            {missing.map((capability) => (
              <Tag key={capability.name} color="red">
                缺少 {capability.name}
              </Tag>
            ))}
          </div>
          {missing.length > 0 && (
            <div className="text-xs text-red-500 mt-2">
              当前 Agent 缺少必要能力，需要先配置工具、技能或知识库后再创建。
            </div>
          )}
          {proposal.confirmed_task_id && (
            <div className="text-xs text-green-600 mt-2">
              已创建任务 #{proposal.confirmed_task_id}
            </div>
          )}
          <Space className="mt-4">
            {proposal.executable && !proposal.confirmed_task_id ? (
              <Button
                type="primary"
                size="small"
                loading={confirming}
                onClick={onConfirm}
              >
                创建任务
              </Button>
            ) : !proposal.confirmed_task_id ? (
              <>
                <Button size="small" onClick={onEdit}>
                  修改任务要求
                </Button>
                <Button
                  size="small"
                  icon={<Settings size={14} />}
                  onClick={onConfigureAgent}
                >
                  去配置 Agent
                </Button>
              </>
            ) : null}
          </Space>
        </div>
      </div>
    </div>
  );
}
