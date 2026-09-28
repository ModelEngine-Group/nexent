"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";

import {
  Button,
  Collapse,
  Divider,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Steps,
  Switch,
  Tooltip,
  Upload,
  message,
} from "antd";
import {
  ArrowLeftOutlined,
  InboxOutlined,
  QuestionCircleOutlined,
} from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import type {
  AidpGraphConfig,
  AidpModelItem,
} from "@/ext_components/aidp/services/aidpKnowledgeService";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import { USER_ROLES } from "@/const/auth";
import {
  AIDP_ACCEPT_STRING,
  AIDP_KNOWLEDGE_BASE_NAME_PATTERN,
} from "@/const/knowledgeBase";
import { collectUploadedFileIds } from "@/lib/aidpDocumentStatus";
import {
  partitionAidpFiles,
  validateAidpFiles,
} from "@/services/uploadService";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import log from "@/lib/logger";

import {
  AidpKnowledgeBaseBasicFields,
  AidpKnowledgeBasePermissionFields,
} from "./AidpKnowledgeBaseModalParts";

const { Dragger } = Upload;

/**
 * Default AIDP knowledge base configuration.
 *
 * The chunking, retrieval, embedding and caption values keep the semantics the
 * existing Nexent create call already had (1024 tokens, 128 token overlap,
 * similarity 0.0, Top K 10, embedding "default", captioning off). The graph
 * parameters use the documented AIDP defaults, which are not the prototype
 * sample values.
 */
const AIDP_CREATE_DEFAULTS = {
  chunk_token_num: 1024,
  /** Overlap as a percentage of the chunk size; 128/1024 = 12.5%. */
  chunk_overlap_percent: 12.5,
  chunk_mode: 0,
  embedding_model: "default",
  is_personal: 0,
  topk: 10,
  similarity: 0.0,
  smartsplit: 1,
  caption_enable: 0,
  is_exist_graph: false,
  graph_domain: "general" as const,
  graph_topk: 5,
  graph_hop: 2,
  /** UI switch; the submitted `no_think_mode` is its inverse. */
  graph_thinking: false,
  graph_prompt_language: "chinese" as const,
  graph_synonym_merge: false,
  graph_disambiguation: false,
  sensitive_intercept_enalbe: 0,
};

/** Editable default extraction prompt (UTF-8 length is validated on submit). */
const DEFAULT_GRAPH_PROMPT = `你作为专业知识图谱抽取引擎，仅执行输入文本中实体、关系、属性三元组的标准化提取。
严格遵循构图任务约定的输出字段与结构，输出合法、固定格式的 JSON 数组，不输出 Markdown 标记、解释、推理过程或其他冗余文本。
仅依据输入文本和其中明确的上下文提取信息，不编造实体、关系或属性，不补充原文没有提供的事实。
实体名称应保持一致；同一实体使用统一表述，不合并无法确认是同一对象的实体。
关系和属性使用明确、简洁的表述，保留原文中的否定、条件和范围限定。
没有可提取信息时输出空数组 []。`;

const GRAPH_PROMPT_MAX_BYTES = 2048;
const CHUNK_TOKEN_MIN = 256;
const CHUNK_TOKEN_MAX = 4096;
const OVERLAP_PERCENT_MAX = 50;

const byteLength = (value: string): number =>
  typeof TextEncoder === "undefined"
    ? value.length
    : new TextEncoder().encode(value).length;

/**
 * Dedicated AIDP knowledge base creation page.
 *
 * Two steps: the first collects every creation parameter (permissions included)
 * and only validates locally — no resource exists until the final submit. The
 * second step optionally uploads files after the knowledge base was created.
 * Upload failures never recreate the knowledge base; only the failed files can
 * be retried.
 */
const AidpCreateKbPage: React.FC = () => {
  const { t, i18n } = useTranslation();
  const router = useRouter();
  const params = useParams();
  const locale = (params?.locale as string) || "zh";
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();

  const [form] = Form.useForm();
  const [current, setCurrent] = useState(0);
  const [loading, setLoading] = useState(false);
  const [fileList, setFileList] = useState<File[]>([]);
  const fileListRef = useRef<File[]>([]);
  const pendingFilesRef = useRef<File[]>([]);
  const rafIdRef = useRef<number | null>(null);
  /** Guards against a second create while one submission is in flight. */
  const submittingRef = useRef(false);
  /** Knowledge base created by the current submission, if any. */
  const createdKbIdRef = useRef<string | null>(null);

  useEffect(() => {
    fileListRef.current = fileList;
  }, [fileList]);

  // The entry only serves AIDP; an ES deployment has no creation entry here,
  // so a direct visit goes back to the knowledge base page.
  useEffect(() => {
    if (!isDeploymentReady) return;
    if (!enableAidpKnowledge) {
      router.replace(`/${locale}/knowledges`);
    }
  }, [enableAidpKnowledge, isDeploymentReady, locale, router]);

  // ---- Permissions and groups ----
  const { user } = useAuthorizationContext();
  const isUser = user?.role === USER_ROLES.USER;
  const canConfigureGroupPermissions = !!user && !isUser;
  const tenantId = user?.tenantId ?? null;
  const { data: groupListData } = useGroupList(
    canConfigureGroupPermissions ? tenantId : null
  );
  const groupOptions = useMemo(
    () =>
      (groupListData?.groups ?? []).map((g) => ({
        value: g.group_id,
        label: g.group_name,
      })),
    [groupListData]
  );
  const ingroupPermission = Form.useWatch("ingroup_permission", form);

  // ---- Model queries: one category per control, independent caches ----
  const { data: llmModelsData, isLoading: llmModelsLoading } = useQuery({
    queryKey: ["aidp-models", "llm", "KnowledgeBase"],
    queryFn: () => aidpKnowledgeService.listModels("llm", "KnowledgeBase"),
    staleTime: 5 * 60 * 1000,
  });
  const { data: vlmModelsData, isLoading: vlmModelsLoading } = useQuery({
    queryKey: ["aidp-models", "vlm", "KnowledgeBase"],
    queryFn: () => aidpKnowledgeService.listModels("vlm", "KnowledgeBase"),
    staleTime: 5 * 60 * 1000,
  });
  const { data: embeddingModelsData, isLoading: embeddingModelsLoading } =
    useQuery({
      queryKey: ["aidp-models", "embedding", "KnowledgeBase"],
      queryFn: () =>
        aidpKnowledgeService.listModels("embedding", "KnowledgeBase"),
      staleTime: 5 * 60 * 1000,
    });

  const modelNames = useCallback(
    (data: { models?: AidpModelItem[] } | undefined) => {
      const models: AidpModelItem[] = data?.models ?? [];
      return models
        .map((m) => m.model_name)
        .filter(
          (name): name is string => typeof name === "string" && name.length > 0
        );
    },
    []
  );

  const llmModelOptions = useMemo(
    () => modelNames(llmModelsData),
    [llmModelsData, modelNames]
  );
  const vlmModelOptions = useMemo(
    () => modelNames(vlmModelsData),
    [vlmModelsData, modelNames]
  );
  // `default` keeps the established semantics of the existing create call, so
  // it stays selectable even when AIDP advertises other embedding models.
  const embeddingModelOptions = useMemo(() => {
    const advertised = modelNames(embeddingModelsData);
    return advertised.includes(AIDP_CREATE_DEFAULTS.embedding_model)
      ? advertised
      : [AIDP_CREATE_DEFAULTS.embedding_model, ...advertised];
  }, [embeddingModelsData, modelNames]);

  // ---- Conditional sections ----
  const graphEnabled = Form.useWatch("is_exist_graph", form);
  const captionEnabled = Form.useWatch("caption_enable", form);

  // ---- Defaults ----
  useEffect(() => {
    form.setFieldsValue({
      chunk_token_num: AIDP_CREATE_DEFAULTS.chunk_token_num,
      chunk_overlap_percent: AIDP_CREATE_DEFAULTS.chunk_overlap_percent,
      chunk_mode: AIDP_CREATE_DEFAULTS.chunk_mode,
      topk: AIDP_CREATE_DEFAULTS.topk,
      similarity: AIDP_CREATE_DEFAULTS.similarity,
      embedding_model: AIDP_CREATE_DEFAULTS.embedding_model,
      caption_enable: AIDP_CREATE_DEFAULTS.caption_enable === 1,
      is_exist_graph: AIDP_CREATE_DEFAULTS.is_exist_graph,
      graph_domain: AIDP_CREATE_DEFAULTS.graph_domain,
      graph_topk: AIDP_CREATE_DEFAULTS.graph_topk,
      graph_hop: AIDP_CREATE_DEFAULTS.graph_hop,
      graph_thinking: AIDP_CREATE_DEFAULTS.graph_thinking,
      graph_prompt_language: AIDP_CREATE_DEFAULTS.graph_prompt_language,
      graph_synonym_merge: AIDP_CREATE_DEFAULTS.graph_synonym_merge,
      graph_disambiguation: AIDP_CREATE_DEFAULTS.graph_disambiguation,
      graph_prompt_text: DEFAULT_GRAPH_PROMPT,
      sensitive_intercept_enalbe:
        AIDP_CREATE_DEFAULTS.sensitive_intercept_enalbe === 1,
      ingroup_permission: isUser ? "PRIVATE" : "READ_ONLY",
      group_ids: [],
    });
  }, [form, isUser]);

  const steps = [
    { title: t("aidpKnowledge.createStepInfo") },
    { title: t("aidpKnowledge.createStepUpload") },
  ];

  const goBackToList = () => router.push(`/${locale}/knowledges`);

  /** Validate the first step; nothing is created here. */
  const handleNext = async () => {
    try {
      await form.validateFields();
      setCurrent(1);
    } catch {
      // Validation errors are rendered next to the fields.
    }
  };

  const handleBack = () => setCurrent(0);

  /** Jump to the created knowledge base file view. */
  const openCreatedKb = (kbId: string) => {
    router.push(`/${locale}/knowledges?kb=${encodeURIComponent(kbId)}`);
  };

  const handleSubmit = async (skipUpload: boolean) => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    let createdId: string | null = createdKbIdRef.current;
    setLoading(true);
    try {
      const values = await form.validateFields();
      const permission = isUser
        ? "PRIVATE"
        : values.ingroup_permission || "READ_ONLY";
      const groupIds =
        isUser || permission === "PRIVATE"
          ? []
          : Array.isArray(values.group_ids)
            ? values.group_ids
            : [];

      // Defense in depth: re-validate every selected file in case the drop
      // handler was bypassed.
      if (createdId === null && !skipUpload && fileList.length > 0) {
        const validation = validateAidpFiles(fileList);
        if (validation.valid.length !== fileList.length) {
          partitionAidpFiles(fileList, t, message);
          return;
        }
      }

      if (createdId === null) {
        const chunkTokens =
          values.chunk_token_num ?? AIDP_CREATE_DEFAULTS.chunk_token_num;
        const overlapPercent =
          values.chunk_overlap_percent ??
          AIDP_CREATE_DEFAULTS.chunk_overlap_percent;
        const overlapTokens = Math.floor(
          (chunkTokens * Number(overlapPercent)) / 100
        );

        const graphConfig: AidpGraphConfig | undefined = values.is_exist_graph
          ? {
              domain: values.graph_domain || AIDP_CREATE_DEFAULTS.graph_domain,
              retrieve_default_topk:
                values.graph_topk ?? AIDP_CREATE_DEFAULTS.graph_topk,
              retrieve_subgraph_hop:
                values.graph_hop ?? AIDP_CREATE_DEFAULTS.graph_hop,
              // The UI switch is the inverse of the submitted thinking mode.
              no_think_mode: !values.graph_thinking,
              prompt_language:
                values.graph_prompt_language ||
                AIDP_CREATE_DEFAULTS.graph_prompt_language,
              prompt_text: values.graph_prompt_text || DEFAULT_GRAPH_PROMPT,
              synonym_merge_enable: !!values.graph_synonym_merge,
              disambiguation_enable: !!values.graph_disambiguation,
            }
          : undefined;

        const created = await aidpKnowledgeService.createKb({
          name: values.name.trim(),
          description: values.description?.trim() || "",
          chunk_token_num: chunkTokens,
          chunk_overlap_num: overlapTokens,
          chunk_mode: values.chunk_mode ?? AIDP_CREATE_DEFAULTS.chunk_mode,
          embedding_model:
            values.embedding_model || AIDP_CREATE_DEFAULTS.embedding_model,
          topk: values.topk ?? AIDP_CREATE_DEFAULTS.topk,
          similarity: values.similarity ?? AIDP_CREATE_DEFAULTS.similarity,
          smartsplit: AIDP_CREATE_DEFAULTS.smartsplit,
          is_personal: AIDP_CREATE_DEFAULTS.is_personal,
          caption_enable: values.caption_enable ? 1 : 0,
          vlm_model: values.caption_enable ? values.vlm_model || "" : "",
          is_exist_graph: !!values.is_exist_graph,
          graph_config: graphConfig,
          llm_model_name: values.is_exist_graph
            ? values.llm_model_name || ""
            : "",
          sensitive_intercept_enalbe: values.sensitive_intercept_enalbe ? 1 : 0,
          ingroup_permission: permission,
          group_ids: groupIds,
        });
        createdId = String(created.kds_id || "");
        createdKbIdRef.current = createdId;
      }

      // Upload only after a successful create; a failure here never creates
      // another knowledge base.
      if (createdId && !skipUpload && fileList.length > 0) {
        const result = await aidpKnowledgeService.uploadDocs(
          createdId,
          fileList
        );
        const failureDetails = result.failed_list.map((item) => {
          const reason = i18n.language.startsWith("zh")
            ? item.reason_zh || item.reason_en
            : item.reason_en || item.reason_zh;
          return `${item.file_name}: ${reason || t("aidpKnowledge.uploadFailed")}`;
        });
        const failureLines = failureDetails.map((detail, index) => (
          <div key={`${index}-${detail}`}>{detail}</div>
        ));

        if (result.summary.failed > 0 && result.summary.success === 0) {
          message.warning(
            <div className="text-left">
              <div>{t("aidpKnowledge.createKbSuccess")}</div>
              {failureLines.length > 0 ? (
                failureLines
              ) : (
                <div>{t("aidpKnowledge.uploadFailed")}</div>
              )}
            </div>
          );
        } else if (result.summary.failed > 0) {
          message.info(
            <div className="text-left">
              <div>{t("aidpKnowledge.createKbSuccess")}</div>
              <div>
                {t("aidpKnowledge.uploadPartial", {
                  success: result.summary.success,
                  failed: result.summary.failed,
                })}
              </div>
              {failureLines}
            </div>
          );
        } else {
          message.success(
            `${t("aidpKnowledge.createKbSuccess")} | ${t(
              "aidpKnowledge.uploadSuccess",
              { count: result.summary.success }
            )}`
          );
        }
        void collectUploadedFileIds(result.success_list);
      } else {
        message.success(t("aidpKnowledge.createKbSuccess"));
      }

      if (createdId) openCreatedKb(createdId);
    } catch (error) {
      log.error("Failed to submit AIDP knowledge base creation:", error);
      const reason =
        error instanceof Error && error.message.trim()
          ? error.message
          : createdId
            ? t("aidpKnowledge.uploadFailed")
            : t("aidpKnowledge.createKbFailed");
      message.error(
        createdId ? `${t("aidpKnowledge.createKbSuccess")} | ${reason}` : reason
      );
      // The knowledge base exists even though a later step failed: take the
      // user to it instead of leaving a form that would create a duplicate.
      if (createdId) openCreatedKb(createdId);
    } finally {
      setLoading(false);
      submittingRef.current = false;
    }
  };

  const renderStep0 = () => (
    <Form form={form} layout="vertical" className="mt-4">
      <h4 className="text-sm font-semibold text-gray-800 mb-2">
        {t("aidpKnowledge.createSectionBasic")}
      </h4>
      <AidpKnowledgeBaseBasicFields t={t} />

      {canConfigureGroupPermissions && (
        <>
          <Divider className="my-3" />
          <h4 className="text-sm font-semibold text-gray-800 mb-2">
            {t("aidpKnowledge.createSectionPermission")}
          </h4>
          <AidpKnowledgeBasePermissionFields
            t={t}
            groupOptions={groupOptions}
            ingroupPermission={ingroupPermission}
          />
        </>
      )}

      <Divider className="my-3" />
      <h4 className="text-sm font-semibold text-gray-800 mb-2">
        {t("aidpKnowledge.createSectionSafety")}
      </h4>
      <Form.Item
        name="sensitive_intercept_enalbe"
        valuePropName="checked"
        label={
          <Space>
            <span>{t("aidpKnowledge.createSafetyGuard")}</span>
            <Tooltip title={t("aidpKnowledge.createSafetyGuardHint")}>
              <QuestionCircleOutlined className="text-gray-400 cursor-help" />
            </Tooltip>
          </Space>
        }
      >
        <Switch />
      </Form.Item>

      <Divider className="my-3" />
      <h4 className="text-sm font-semibold text-gray-800 mb-2">
        {t("aidpKnowledge.createSectionGraph")}
      </h4>
      <Form.Item
        name="is_exist_graph"
        valuePropName="checked"
        label={
          <Space>
            <span>{t("aidpKnowledge.createGraphEnable")}</span>
            <Tooltip title={t("aidpKnowledge.createGraphEnableHint")}>
              <QuestionCircleOutlined className="text-gray-400 cursor-help" />
            </Tooltip>
          </Space>
        }
      >
        <Switch />
      </Form.Item>

      {graphEnabled && (
        <>
          <Form.Item
            name="graph_domain"
            label={t("aidpKnowledge.createGraphDomain")}
          >
            <Select
              options={[
                {
                  value: "general",
                  label: t("aidpKnowledge.createGraphDomainGeneral"),
                },
                {
                  value: "medical",
                  label: t("aidpKnowledge.createGraphDomainMedical"),
                },
                {
                  value: "finance",
                  label: t("aidpKnowledge.createGraphDomainFinance"),
                },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="graph_topk"
            label={t("aidpKnowledge.createGraphTopk")}
            rules={[{ type: "number", min: 1, max: 100 }]}
          >
            <InputNumber style={{ width: "100%" }} min={1} max={100} />
          </Form.Item>
          <Form.Item
            name="graph_hop"
            label={t("aidpKnowledge.createGraphHop")}
            rules={[{ type: "number", min: 1, max: 3 }]}
          >
            <InputNumber style={{ width: "100%" }} min={1} max={3} />
          </Form.Item>
          <Form.Item
            name="llm_model_name"
            label={
              <Space>
                <span>{t("aidpKnowledge.createGraphModel")}</span>
                <Tooltip title={t("aidpKnowledge.createGraphModelHint")}>
                  <QuestionCircleOutlined className="text-gray-400 cursor-help" />
                </Tooltip>
              </Space>
            }
            rules={[
              {
                required: true,
                message: t("aidpKnowledge.createGraphModelRequired"),
              },
            ]}
          >
            <Select
              showSearch
              allowClear
              loading={llmModelsLoading}
              notFoundContent={
                llmModelsLoading
                  ? t("aidpKnowledge.createModelLoading")
                  : t("aidpKnowledge.createModelNone")
              }
              placeholder={t("aidpKnowledge.createModelSearch")}
              options={llmModelOptions.map((name) => ({
                label: name,
                value: name,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="graph_thinking"
            valuePropName="checked"
            label={
              <Space>
                <span>{t("aidpKnowledge.createGraphThinking")}</span>
                <Tooltip title={t("aidpKnowledge.createGraphThinkingHint")}>
                  <QuestionCircleOutlined className="text-gray-400 cursor-help" />
                </Tooltip>
              </Space>
            }
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="graph_prompt_language"
            label={t("aidpKnowledge.createGraphPromptLanguage")}
          >
            <Select
              options={[
                {
                  value: "chinese",
                  label: t("aidpKnowledge.createGraphPromptZh"),
                },
                {
                  value: "english",
                  label: t("aidpKnowledge.createGraphPromptEn"),
                },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="graph_prompt_text"
            label={
              <Space>
                <span>{t("aidpKnowledge.createGraphPromptText")}</span>
                <Tooltip title={t("aidpKnowledge.createGraphPromptHint")}>
                  <QuestionCircleOutlined className="text-gray-400 cursor-help" />
                </Tooltip>
              </Space>
            }
            rules={[
              {
                validator: (_rule, value: string) => {
                  if (byteLength(value || "") <= GRAPH_PROMPT_MAX_BYTES) {
                    return Promise.resolve();
                  }
                  return Promise.reject(
                    new Error(t("aidpKnowledge.createGraphPromptTooLong"))
                  );
                },
              },
            ]}
          >
            <Input.TextArea rows={8} />
          </Form.Item>
          <Form.Item
            name="graph_synonym_merge"
            valuePropName="checked"
            label={t("aidpKnowledge.createGraphSynonymMerge")}
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="graph_disambiguation"
            valuePropName="checked"
            label={t("aidpKnowledge.createGraphDisambiguation")}
          >
            <Switch />
          </Form.Item>
        </>
      )}

      <Divider className="my-3" />
      <h4 className="text-sm font-semibold text-gray-800 mb-2">
        {t("aidpKnowledge.createSectionChunk")}
      </h4>
      <Form.Item
        name="chunk_mode"
        label={t("aidpKnowledge.createChunkMode")}
        rules={[{ required: true }]}
      >
        <Select
          options={[
            {
              value: 0,
              label: t("aidpKnowledge.createChunkModeSmart"),
            },
            {
              value: 1,
              label: t("aidpKnowledge.createChunkModeLegal"),
            },
          ]}
        />
      </Form.Item>
      <Form.Item
        name="chunk_token_num"
        label={t("aidpKnowledge.createChunkTokenNum")}
        dependencies={["chunk_overlap_percent"]}
        rules={[
          {
            required: true,
            message: t("aidpKnowledge.createChunkTokenNumRequired"),
          },
          {
            type: "number",
            min: CHUNK_TOKEN_MIN,
            max: CHUNK_TOKEN_MAX,
            message: t("aidpKnowledge.createChunkTokenNumRange", {
              min: CHUNK_TOKEN_MIN,
              max: CHUNK_TOKEN_MAX,
            }),
          },
        ]}
      >
        <InputNumber
          style={{ width: "100%" }}
          min={CHUNK_TOKEN_MIN}
          max={CHUNK_TOKEN_MAX}
        />
      </Form.Item>
      <Form.Item
        name="chunk_overlap_percent"
        label={
          <Space>
            <span>{t("aidpKnowledge.createOverlapPercent")}</span>
            <Tooltip title={t("aidpKnowledge.createOverlapPercentHint")}>
              <QuestionCircleOutlined className="text-gray-400 cursor-help" />
            </Tooltip>
          </Space>
        }
        rules={[
          {
            required: true,
            message: t("aidpKnowledge.createOverlapPercentRequired"),
          },
          {
            type: "number",
            min: 0,
            max: OVERLAP_PERCENT_MAX,
            message: t("aidpKnowledge.createOverlapPercentRange", {
              max: OVERLAP_PERCENT_MAX,
            }),
          },
        ]}
      >
        <InputNumber
          style={{ width: "100%" }}
          min={0}
          max={OVERLAP_PERCENT_MAX}
          step={0.5}
          addonAfter="%"
        />
      </Form.Item>

      <Collapse
        ghost
        size="small"
        items={[
          {
            key: "vector_and_retrieval",
            label: t("aidpKnowledge.createAdvancedOptions"),
            children: (
              <>
                <Form.Item
                  name="embedding_model"
                  label={t("aidpKnowledge.createEmbeddingModel")}
                  rules={[{ required: true }]}
                >
                  <Select
                    showSearch
                    loading={embeddingModelsLoading}
                    notFoundContent={
                      embeddingModelsLoading
                        ? t("aidpKnowledge.createModelLoading")
                        : t("aidpKnowledge.createModelNone")
                    }
                    options={embeddingModelOptions.map((name) => ({
                      label: name,
                      value: name,
                    }))}
                  />
                </Form.Item>
                <Form.Item
                  name="caption_enable"
                  valuePropName="checked"
                  label={
                    <Space>
                      <span>{t("aidpKnowledge.createCaptionEnable")}</span>
                      <Tooltip
                        title={t("aidpKnowledge.createCaptionEnableHint")}
                      >
                        <QuestionCircleOutlined className="text-gray-400 cursor-help" />
                      </Tooltip>
                    </Space>
                  }
                >
                  <Switch />
                </Form.Item>
                {captionEnabled && (
                  <Form.Item
                    name="vlm_model"
                    label={t("aidpKnowledge.createVlmModel")}
                  >
                    <Select
                      showSearch
                      allowClear
                      loading={vlmModelsLoading}
                      notFoundContent={
                        vlmModelsLoading
                          ? t("aidpKnowledge.createModelLoading")
                          : t("aidpKnowledge.createModelNone")
                      }
                      placeholder={t("aidpKnowledge.createModelSearch")}
                      options={vlmModelOptions.map((name) => ({
                        label: name,
                        value: name,
                      }))}
                    />
                  </Form.Item>
                )}
                <Form.Item
                  name="similarity"
                  label={t("aidpKnowledge.createSimilarity")}
                  rules={[{ type: "number", min: 0, max: 1 }]}
                >
                  <InputNumber
                    style={{ width: "100%" }}
                    min={0}
                    max={1}
                    step={0.01}
                  />
                </Form.Item>
                <Form.Item
                  name="topk"
                  label={t("aidpKnowledge.createTopk")}
                  rules={[{ type: "number", min: 1, max: 100 }]}
                >
                  <InputNumber style={{ width: "100%" }} min={1} max={100} />
                </Form.Item>
              </>
            ),
          },
        ]}
      />
    </Form>
  );

  const renderStep1 = () => (
    <div className="mt-4">
      <Dragger
        accept={AIDP_ACCEPT_STRING}
        multiple
        fileList={fileList.map((f, i) => ({
          uid: `${i}-${f.name}`,
          name: f.name,
          size: f.size,
          status: "done" as const,
          originFileObj: f as unknown as File & {
            uid: string;
            lastModifiedDate: Date;
          },
        }))}
        beforeUpload={(_file) => {
          // Antd fires beforeUpload once per file in a batch; queue them and
          // flush validation plus state once per frame.
          pendingFilesRef.current.push(_file);
          if (rafIdRef.current === null) {
            rafIdRef.current = requestAnimationFrame(() => {
              const batch = pendingFilesRef.current;
              pendingFilesRef.current = [];
              rafIdRef.current = null;

              const currentFiles = fileListRef.current;
              const existing = new Set(currentFiles.map((file) => file.name));
              const uniqueBatch = batch.filter(
                (file) => !existing.has(file.name)
              );
              const { valid } = partitionAidpFiles(
                uniqueBatch,
                t,
                message,
                currentFiles.length
              );
              if (valid.length > 0) {
                setFileList([...currentFiles, ...valid]);
              }
            });
          }
          return false;
        }}
        onRemove={(file) => {
          setFileList((prev) =>
            prev.filter((f) => f.name !== (file as { name?: string }).name)
          );
        }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">{t("aidpKnowledge.uploadHint")}</p>
        <div className="ant-upload-hint mt-2 w-full min-w-0 max-w-full space-y-1 overflow-hidden px-4 whitespace-normal">
          <div>{t("aidpKnowledge.uploadHintCount")}</div>
          <div>{t("aidpKnowledge.uploadHintSize")}</div>
          <div className="w-full min-w-0 break-all leading-5 whitespace-normal">
            {t("aidpKnowledge.uploadHintFormats")}
          </div>
        </div>
      </Dragger>

      {fileList.length === 0 && (
        <div className="mt-3 text-gray-400 text-xs text-center">
          {t("aidpKnowledge.createNoFiles")}
        </div>
      )}
    </div>
  );

  return (
    <div className="w-full h-full mx-auto relative flex flex-col max-w-3xl px-4">
      <div className="flex-1 min-h-0 w-full mt-4 overflow-y-auto pb-4">
        <div className="mb-3 flex items-center gap-2">
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={goBackToList}
            size="small"
            disabled={loading}
          >
            {t("aidpKnowledge.createBackToList")}
          </Button>
          <h2 className="text-base font-semibold text-gray-800">
            {t("aidpKnowledge.createPageTitle")}
          </h2>
        </div>

        <div className="bg-white border border-gray-200 rounded-md p-4">
          <Steps current={current} items={steps} size="small" />
          <Divider className="my-3" />
          {/* Keep the first step mounted: its field values must survive moving
              back and forth between the two steps. */}
          <div className={current === 0 ? "" : "hidden"}>{renderStep0()}</div>
          {current === 1 && renderStep1()}
        </div>

        <div className="mt-3 flex items-center justify-between gap-2">
          <div>
            {current === 1 && (
              <Button onClick={handleBack} disabled={loading}>
                {t("aidpKnowledge.createBack")}
              </Button>
            )}
          </div>
          <Space>
            <Button onClick={goBackToList} disabled={loading}>
              {t("common.cancel")}
            </Button>
            {current === 0 && (
              <Button type="primary" onClick={handleNext}>
                {t("aidpKnowledge.createNext")}
              </Button>
            )}
            {current === 1 && (
              <Button
                type={fileList.length === 0 ? "primary" : "default"}
                loading={loading}
                onClick={() => void handleSubmit(true)}
              >
                {t("aidpKnowledge.createSkipUpload")}
              </Button>
            )}
            {current === 1 && fileList.length > 0 && (
              <Button
                type="primary"
                loading={loading}
                onClick={() => void handleSubmit(false)}
              >
                {t("aidpKnowledge.createSubmit")}
              </Button>
            )}
          </Space>
        </div>
        {loading && (
          <div className="mt-2 text-xs text-gray-400 text-center">
            {t("aidpKnowledge.createSubmitting")}
          </div>
        )}
      </div>
    </div>
  );
};

export default AidpCreateKbPage;
