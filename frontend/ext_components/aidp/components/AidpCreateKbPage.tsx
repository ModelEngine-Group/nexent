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

import { Button, Breadcrumb, Form, Space, message } from "antd";

import type {
  AidpGraphConfig,
  AidpModelItem,
} from "@/ext_components/aidp/services/aidpKnowledgeService";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import { USER_ROLES } from "@/const/auth";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import log from "@/lib/logger";

import AidpCreateKbSections from "./AidpCreateKbSections";
import styles from "./AidpCreateKbSections.module.css";

/**
 * Default AIDP knowledge base configuration.
 *
 * The creation screen uses the agreed product defaults (1024 tokens, 128 token
 * overlap, similarity 0.6, Top K 10, embedding "default", captioning off). The
 * graph parameters use the documented AIDP defaults, which are not the
 * prototype sample values.
 */
const AIDP_CREATE_DEFAULTS = {
  chunk_token_num: 1024,
  /** Overlap as a percentage of the chunk size; 128/1024 = 12.5%. */
  chunk_overlap_percent: 12.5,
  chunk_mode: 0,
  embedding_model: "default",
  is_personal: 0,
  topk: 10,
  similarity: 0.6,
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
};

/** Editable default extraction prompt (UTF-8 length is validated on submit). */
const DEFAULT_GRAPH_PROMPT = `你作为专业知识图谱抽取引擎，仅执行输入文本中实体、关系、属性三元组的标准化提取。
严格遵循构图任务约定的输出字段与结构，输出合法、固定格式的 JSON 数组，不输出 Markdown 标记、解释、推理过程或其他冗余文本。
仅依据输入文本和其中明确的上下文提取信息，不编造实体、关系或属性，不补充原文没有提供的事实。
实体名称应保持一致；同一实体使用统一表述，不合并无法确认是同一对象的实体。
关系和属性使用明确、简洁的表述，保留原文中的否定、条件和范围限定。
没有可提取信息时输出空数组 []。`;

/**
 * Dedicated AIDP knowledge base creation page.
 *
 * Collects all creation parameters in one page and creates the knowledge base
 * directly. Files are uploaded from the knowledge base detail page.
 */
const AidpCreateKbPage: React.FC = () => {
  const { t } = useTranslation();
  const router = useRouter();
  const params = useParams();
  const locale = (params?.locale as string) || "zh";
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();

  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  /** Guards against a second create while one submission is in flight. */
  const submittingRef = useRef(false);

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
      ingroup_permission: isUser ? "PRIVATE" : "READ_ONLY",
      group_ids: [],
    });
  }, [form, isUser]);

  const goBackToList = () => router.push(`/${locale}/knowledges`);

  /** Jump to the created knowledge base file view. */
  const openCreatedKb = (kbId: string) => {
    router.push(`/${locale}/knowledges?kb=${encodeURIComponent(kbId)}`);
  };

  const handleSubmit = async () => {
    if (submittingRef.current) return;
    submittingRef.current = true;
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
            llm_model_name: values.llm_model_name,
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
        ingroup_permission: permission,
        group_ids: groupIds,
      });

      message.success(t("aidpKnowledge.createKbSuccess"));
      const createdId = String(created.kds_id || "");
      if (createdId) openCreatedKb(createdId);
    } catch (error) {
      if (
        typeof error === "object" &&
        error !== null &&
        "errorFields" in error
      ) {
        return;
      }
      log.error("Failed to submit AIDP knowledge base creation:", error);
      const reason =
        error instanceof Error && error.message.trim()
          ? error.message
          : t("aidpKnowledge.createKbFailed");
      message.error(reason);
    } finally {
      setLoading(false);
      submittingRef.current = false;
    }
  };

  return (
    <div className="relative flex h-full min-h-0 w-full flex-col">
      <header className="shrink-0 px-6 pt-4">
        <Breadcrumb
          items={[
            {
              title: (
                <button
                  type="button"
                  disabled={loading}
                  onClick={goBackToList}
                  className="!text-lg !leading-7 text-gray-500 hover:text-blue-500 disabled:cursor-not-allowed"
                >
                  {t("aidpKnowledge.breadcrumbKnowledgeBase")}
                </button>
              ),
            },
            {
              title: (
                <span className="!text-lg !font-semibold !leading-7 text-gray-800">
                  {t("aidpKnowledge.createPageTitle")}
                </span>
              ),
            },
          ]}
        />
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6 pt-4">
        <AidpCreateKbSections
          form={form}
          t={t}
          canConfigureGroupPermissions={canConfigureGroupPermissions}
          groupOptions={groupOptions}
          ingroupPermission={ingroupPermission}
          llmModelOptions={llmModelOptions}
          llmModelsLoading={llmModelsLoading}
          vlmModelOptions={vlmModelOptions}
          vlmModelsLoading={vlmModelsLoading}
          embeddingModelOptions={embeddingModelOptions}
          embeddingModelsLoading={embeddingModelsLoading}
        />
      </div>

      <footer className={styles.createFooter}>
        <div />
        <Space size={10} wrap>
          <Button onClick={goBackToList} disabled={loading}>
            {t("common.cancel")}
          </Button>
          <Button
            type="primary"
            loading={loading}
            onClick={() => void handleSubmit()}
          >
            {t("aidpKnowledge.createSubmit")}
          </Button>
        </Space>
      </footer>
      {loading && (
        <div className="absolute bottom-[4.5rem] left-1/2 -translate-x-1/2 rounded bg-white px-3 py-1 text-xs text-gray-500 shadow">
          {t("aidpKnowledge.createSubmitting")}
        </div>
      )}
    </div>
  );
};

export default AidpCreateKbPage;
