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
    schema_version: 4,
    mode: "generic_chat",
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
    "创建「文档资料整理助手」，面向需要整理工作或学习资料的用户，将上传的文档、图片和截图整理为清晰、可检索的资料摘要。\n\n使用图片分析工具识别扫描件、文档照片或截图，提取标题、正文、表格和关键数据；遇到模糊、缺失或无法确认的内容时，请用户补充，不猜测内容。保留文件名和页码等来源信息，方便核对。\n\n使用知识库检索工具查找相关背景资料，按照用户指定的主题归类，提炼核心观点、关键数据和待确认事项。区分原文信息与补充说明，对不同资料中的重复或冲突内容进行标注，不编造结论。\n\n根据用户需要，使用文档生成工具制作资料摘要、对比清单或学习笔记，包含资料概览、分类要点、待办事项和来源索引。涉及个人或内部信息时，仅保留完成整理所需的内容。",
    "创建「医学简报助手」，面向医护人员和医学研究人员，围绕指定专科、疾病或研究主题，完成资料搜集、简报制作与邮件分享。\n\n使用在线搜索工具检索用户指定时间范围内的指南更新、原始研究和官方发布内容，并通过知识库检索工具对照已有指南与院内资料，筛选值得关注的变化。\n\n按“本期要点、重点研究、指南更新、与既有资料的差异、研究局限、参考来源”生成内容。标注发表日期和可核查来源，区分研究发现与临床建议，不编造文献、数据或结论。\n\n使用文档生成工具制作医学情报简报，并起草包含重点摘要的邮件。用户明确要求发送且收件人、内容和附件已确定时，使用邮件工具发送；信息不完整时先补充确认。仅在邮件工具支持附件时附上简报，否则提供可访问的文档链接。",
    "创建「活动宣传制作助手」，面向活动组织者，根据活动主题、目标人群和发布渠道，制作宣传文案与图文介绍材料。\n\n使用知识库检索工具查询已关联的活动方案、品牌介绍和往期素材，必要时通过在线搜索补充公开背景资料。先整理活动时间、地点、参与方式和主要亮点；对缺失或存在冲突的信息，请用户补充确认，不编造活动安排。\n\n使用图片生成工具制作活动封面、主题插画或宣传配图，保持视觉风格与活动主题一致。涉及品牌标识、人物肖像或指定素材时，使用用户提供并确认可用的内容；图片中的日期、地点等关键信息需核对。\n\n使用文档生成工具，将文字与配图整合为活动介绍、宣传单或社交媒体文案草稿，包含活动亮点、日程概览和参与指引。根据不同渠道调整篇幅与表达方式，交由用户确认后使用。",
  ],
} as const;
