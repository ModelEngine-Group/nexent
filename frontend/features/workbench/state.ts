// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type {
  WorkbenchCapabilityPreview,
  WorkbenchAgentMount,
  WorkbenchMode,
  WorkbenchSessionConfig,
  WorkbenchSkillMount,
  WorkbenchBootstrap,
} from "./types";

export interface WorkbenchState {
  config: WorkbenchSessionConfig;
  configVersion: number;
  resolving: boolean;
  error?: string;
  skillNames: Record<number, string>;
}

export type WorkbenchAction =
  | { type: "restore-start" }
  | {
      type: "select-mode";
      mode: "agent_create" | "skill_create" | "generic_chat";
    }
  | { type: "replace-agents"; mounts: WorkbenchAgentMount[] }
  | { type: "resolve-agent-start"; agentId: number }
  | {
      type: "resolve-agent-success";
      modelIds?: number[];
      preview: WorkbenchCapabilityPreview;
      append?: boolean;
    }
  | { type: "resolve-agent-error"; message: string }
  | { type: "replace-skills"; mounts: WorkbenchSkillMount[] }
  | { type: "set-skill-names"; names: Record<number, string> }
  | { type: "restore"; config: WorkbenchSessionConfig; version: number }
  | { type: "set-version"; version: number };

export const initialWorkbenchState: WorkbenchState = {
  configVersion: 0,
  resolving: false,
  skillNames: {},
  config: {
    schema_version: 3,
    mode: "generic_chat",
    generation_config: { deep_thinking: false, thinking_effort: "low" },
    agent_mounts: [],
    skill_mounts: [],
  },
};

export function deriveConversationMode(
  mounts: readonly WorkbenchAgentMount[]
): WorkbenchMode {
  return mounts.length === 0
    ? "generic_chat"
    : mounts.length === 1
      ? "single_agent_chat"
      : "multi_agent_chat";
}

export function workbenchReducer(
  state: WorkbenchState,
  action: WorkbenchAction
): WorkbenchState {
  switch (action.type) {
    case "restore-start":
      return { ...state, resolving: true, error: undefined };
    case "select-mode":
      return {
        ...state,
        configVersion: 0,
        resolving: false,
        skillNames: {},
        error: undefined,
        config: {
          ...state.config,
          mode: action.mode,
          model_id:
            action.mode === "generic_chat" ? state.config.model_id : undefined,
          agent_mounts: [],
          skill_mounts: [],
          knowledge_scope: undefined,
        },
      };
    case "replace-agents":
      return {
        ...state,
        error: undefined,
        config: {
          ...state.config,
          agent_mounts: action.mounts,
          mode: deriveConversationMode(action.mounts),
        },
      };
    case "resolve-agent-start":
      return { ...state, resolving: true, error: undefined };
    case "resolve-agent-success": {
      const selectedMount = {
        agent_id: action.preview.agent_id,
        version_no: action.preview.version_no,
      };
      const mounts = action.append
        ? [
            ...state.config.agent_mounts.filter(
              (mount) => mount.agent_id !== selectedMount.agent_id
            ),
            selectedMount,
          ]
        : [selectedMount];
      if (mounts.length > 8)
        return { ...state, resolving: false, error: "最多选择 8 个智能体" };
      return {
        ...state,
        resolving: false,
        configVersion: state.configVersion,
        config: {
          ...state.config,
          mode: deriveConversationMode(mounts),
          agent_mounts: mounts,
        },
      };
    }
    case "resolve-agent-error":
      return { ...state, resolving: false, error: action.message };
    case "replace-skills":
      return {
        ...state,
        config: { ...state.config, skill_mounts: action.mounts },
      };
    case "set-skill-names":
      return { ...state, skillNames: { ...state.skillNames, ...action.names } };
    case "restore":
      return {
        config: action.config,
        configVersion: action.version,
        resolving: false,
        skillNames: state.skillNames,
      };
    case "set-version":
      return { ...state, configVersion: action.version };
  }
}

export function getWorkbenchSendability(
  state: WorkbenchState,
  capabilities?: WorkbenchBootstrap
): {
  canSend: boolean;
  reason?: string;
} {
  if (state.resolving) return { canSend: false, reason: "正在解析资源" };
  if (state.error) return { canSend: false, reason: state.error };
  if (
    state.config.mode === "generic_chat" &&
    !capabilities?.modes.generic_chat.enabled
  ) {
    return {
      canSend: false,
      reason: "通用对话服务暂未接入，可添加智能体开始对话",
    };
  }
  if (
    state.config.mode === "single_agent_chat" &&
    state.config.agent_mounts.length !== 1
  ) {
    return { canSend: false, reason: "请选择一个智能体" };
  }
  if (
    state.config.mode === "multi_agent_chat" &&
    !capabilities?.modes.multi_agent_chat.enabled
  ) {
    return { canSend: false, reason: "多智能体模式暂未开放" };
  }
  if (
    state.config.mode === "agent_create" ||
    state.config.mode === "skill_create"
  ) {
    return { canSend: true };
  }
  return { canSend: true };
}

export const CREATION_PROMPTS = {
  skill_create: [
    "帮我创建一个「发票信息提取」Skill：上传发票图片或 PDF，自动识别发票代码、发票号码、开票日期、购买方、销售方、金额、税额。支持增值税普通发票和专用发票，输出为结构化 JSON，支持批量上传。",
    "帮我创建一个「合同关键信息审查」Skill：上传合同 PDF 或 Word，提取合同主体、金额、履约期限、付款条件、违约责任和争议解决条款，标记缺失项与高风险条款，并输出结构化审查结果。",
    "帮我创建一个「会议纪要整理」Skill：上传会议录音或文字记录，识别议题、关键结论、待办事项、负责人和截止时间，生成结构化会议纪要，并支持导出 Markdown。",
  ],
  agent_create: [
    "创建「体检报告解读助手」，面向体检人群，帮助用户看懂体检报告并整理就医沟通材料。\n\n使用图片分析工具识别用户上传的体检报告照片或截图，提取检查项目、结果、单位及报告中的参考范围；遇到模糊、缺失或无法确认的内容时，请用户补充，不猜测数值。不根据医学影像图片直接判断病灶或作出诊断。\n\n使用知识库检索工具查找相关指标的解释和健康教育资料，必要时通过在线搜索补充权威来源。按“报告概览、异常指标说明、需要向医生确认的问题、参考资料”组织内容，明确单项指标不能独立确诊。\n\n根据用户需要，使用文档生成工具制作便于保存和就诊时携带的报告解读文档，区分报告原始数据与解释内容，不自行开具处方或调整用药。",
    "创建「医学情报简报助手」，面向医护人员和医学研究人员，围绕指定专科、疾病或研究主题，完成资料搜集、简报制作与邮件分享。\n\n使用在线搜索工具检索用户指定时间范围内的指南更新、原始研究和官方发布内容，并通过知识库检索工具对照已有指南与院内资料，筛选值得关注的变化。\n\n按“本期要点、重点研究、指南更新、与既有资料的差异、研究局限、参考来源”生成内容。标注发表日期和可核查来源，区分研究发现与临床建议，不编造文献、数据或结论。\n\n使用文档生成工具制作医学情报简报，并起草包含重点摘要的邮件。用户明确要求发送且收件人、内容和附件已确定时，使用邮件工具发送；信息不完整时先补充确认。仅在邮件工具支持附件时附上简报，否则提供可访问的文档链接。",
    "创建「患者宣教制作助手」，面向医护人员，根据疾病主题、目标人群和使用场景，制作适合患者阅读的宣教材料。\n\n使用知识库检索工具查询已关联的健康教育资料、护理规范与出院指导，必要时通过在线搜索补充权威科普。将专业内容改写为通俗、简洁、可执行的说明，并保留资料来源。\n\n使用图片生成工具制作适合宣教的生活场景插画、步骤示意配图或封面。配图避免包含患者身份信息，不生成用来证明病情的医学影像；精确的医学结构和操作细节应采用经核验的素材。\n\n使用文档生成工具，将文字与配图整合为宣教单、健康手册或出院指导草稿，包含主题说明、日常注意事项、观察记录和寻求医疗帮助的提示。涉及个体治疗安排时，以医护人员提供并确认的信息为准，不自行添加用药剂量或治疗方案。",
  ],
} as const;
