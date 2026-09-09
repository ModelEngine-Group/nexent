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
    generation_config: { deep_thinking: false },
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
        configVersion: 0,
        config: {
          ...state.config,
          mode: deriveConversationMode(mounts),
          agent_mounts: mounts,
          model_id:
            mounts.length === 1 && action.modelIds !== undefined
              ? action.modelIds.includes(state.config.model_id ?? -1)
                ? state.config.model_id
                : action.modelIds[0]
              : state.config.model_id,
          skill_mounts:
            mounts.length === 1
              ? action.preview.default_skill_mounts
              : state.config.skill_mounts,
        },
        skillNames: Object.fromEntries(
          (action.preview.default_skill_resources || []).map((skill) => [
            skill.skill_id,
            skill.name,
          ])
        ),
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
    return { canSend: false, reason: "创建运行适配器尚未接入，当前可编辑草稿" };
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
    "帮我创建一个企业知识问答助手的应用，满足员工自然语言提问、智能检索多源知识库、整合分散信息生成准确答案、支持知识溯源的需求。",
    "帮我创建一个智能客服应用，能够识别用户问题意图，结合产品知识库回答售前和售后问题，信息不足时主动追问，无法解决时转人工，并保留引用来源。",
    "帮我创建一个经营数据分析助手的应用，支持上传 Excel 或 CSV，用自然语言查询核心指标、同比环比和异常波动，生成分析结论与可视化建议，并说明数据口径。",
  ],
} as const;
