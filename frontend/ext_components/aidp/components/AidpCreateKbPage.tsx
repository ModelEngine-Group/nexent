"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { useParams, useRouter } from "next/navigation";

import { Alert, App, Button, Breadcrumb, Form, Space } from "antd";

import type { AidpGraphConfig } from "@/ext_components/aidp/services/aidpKnowledgeService";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { ApiError } from "@/services/api";
import { useErrorHandler } from "@/hooks/useErrorHandler";
import { useAidpGroupOptions } from "../hooks/useAidpGroupOptions";
import {
  useAidpModels,
  useAidpGraphTemplate,
  useCreateAidpKnowledgeBase,
} from "../hooks/useAidpKnowledgeQueries";
import {
  graphParameter,
  graphPrompt,
  modelOptions,
} from "@/lib/aidpGraphConfig";

import AidpCreateKbSections from "./AidpCreateKbSections";
import styles from "./AidpCreateKbSections.module.css";

/**
 * Default AIDP knowledge base configuration.
 *
 * The creation screen uses the agreed product defaults (1024 tokens, 128 token
 * overlap, similarity 0.6, Top K 10 and captioning off). Model identifiers and
 * graph defaults come from AIDP's model and graph template endpoints.
 */
const AIDP_CREATE_DEFAULTS = {
  chunk_token_num: 1024,
  /** Overlap as a percentage of the chunk size; 128/1024 = 12.5%. */
  chunk_overlap_percent: 12.5,
  chunk_mode: 0,
  is_personal: 0,
  topk: 10,
  similarity: 0.6,
  caption_enable: 0,
  is_exist_graph: false,
  graph_domain: "常规" as const,
  graph_hop: 2,
  /** UI switch; the submitted `no_think_mode` is its inverse. */
  graph_thinking: false,
  graph_prompt_language: "中文" as const,
  graph_synonym_merge: false,
  graph_disambiguation: false,
};

/**
 * Dedicated AIDP knowledge base creation page.
 *
 * Collects all creation parameters in one page and creates the knowledge base
 * directly. Files are uploaded from the knowledge base detail page.
 */
const AidpCreateKbPage: React.FC = () => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { handleError, getI18nErrorMessage } = useErrorHandler();
  const router = useRouter();
  const params = useParams();
  const locale = (params?.locale as string) || "zh";
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();

  const [form] = Form.useForm();
  const [validating, setValidating] = useState(false);
  const createMutation = useCreateAidpKnowledgeBase();
  const loading = validating || createMutation.isPending;
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
  const { isUser, canConfigureGroupPermissions, groupOptions } =
    useAidpGroupOptions();
  const ingroupPermission = Form.useWatch("ingroup_permission", form);

  const modelsQuery = useAidpModels();
  const llmModelOptions = useMemo(
    () => modelOptions(modelsQuery.data?.models ?? [], "llm"),
    [modelsQuery.data]
  );
  const vlmModelOptions = useMemo(
    () => modelOptions(modelsQuery.data?.models ?? [], "vlm"),
    [modelsQuery.data]
  );
  const embeddingModelOptions = useMemo(
    () => modelOptions(modelsQuery.data?.models ?? [], "embedding"),
    [modelsQuery.data]
  );
  const graphEnabled = Form.useWatch("is_exist_graph", form) === true;
  const promptLanguage = Form.useWatch("graph_prompt_language", form) || "中文";
  const graphDomain = Form.useWatch("graph_domain", form) || "常规";
  const templateQuery = useAidpGraphTemplate(
    promptLanguage === "英文" ? "english" : "chinese",
    graphEnabled
  );
  const configurationError =
    modelsQuery.error || (graphEnabled ? templateQuery.error : null);
  const configurationErrorMessage =
    configurationError instanceof ApiError
      ? getI18nErrorMessage(configurationError.code)
      : configurationError?.message ||
        t("aidpKnowledge.createConfigurationLoadFailed");
  const initializedGraph = useRef(false);
  const previousDefaultPrompt = useRef("");
  useEffect(() => {
    const data = templateQuery.data;
    if (!data || !graphEnabled) return;
    if (!initializedGraph.current) {
      const value = (key: string) => graphParameter(data, key)?.param_value;
      const defaults: Record<string, unknown> = {
        graph_domain: value("domain"),
        graph_hop: Number(value("retrieve_subgraph_hop")),
        graph_thinking: value("no_think_mode") === "否",
        graph_synonym_merge: value("synonym_merge_enable") === "是",
        graph_disambiguation: value("disambiguation_enable") === "是",
      };
      Object.entries(defaults).forEach(([field, initial]) => {
        if (!form.isFieldTouched(field)) form.setFieldValue(field, initial);
      });
      initializedGraph.current = true;
    }
    const nextPrompt = graphPrompt(
      data,
      form.getFieldValue("graph_domain") || graphDomain
    );
    const currentPrompt = form.getFieldValue("graph_prompt_text") || "";
    if (
      !form.isFieldTouched("graph_prompt_text") ||
      currentPrompt === previousDefaultPrompt.current
    ) {
      form.setFieldValue("graph_prompt_text", nextPrompt);
    }
    previousDefaultPrompt.current = nextPrompt;
  }, [form, graphDomain, graphEnabled, templateQuery.data]);
  const restoreDefaultPrompt = useCallback(() => {
    const prompt = graphPrompt(templateQuery.data, graphDomain);
    form.setFieldValue("graph_prompt_text", prompt);
    previousDefaultPrompt.current = prompt;
  }, [form, graphDomain, templateQuery.data]);
  useEffect(() => {
    for (const [field, options] of [
      ["embedding_model", embeddingModelOptions],
      ["llm_model_name", llmModelOptions],
      ["vlm_model", vlmModelOptions],
    ] as const) {
      if (
        options.length &&
        !form.isFieldTouched(field) &&
        !options.some((option) => option.value === form.getFieldValue(field))
      ) {
        form.setFieldValue(field, options[0].value);
      }
    }
  }, [embeddingModelOptions, form, llmModelOptions, vlmModelOptions]);

  // ---- Defaults ----
  useEffect(() => {
    form.setFieldsValue({
      chunk_token_num: AIDP_CREATE_DEFAULTS.chunk_token_num,
      chunk_overlap_percent: AIDP_CREATE_DEFAULTS.chunk_overlap_percent,
      chunk_mode: AIDP_CREATE_DEFAULTS.chunk_mode,
      topk: AIDP_CREATE_DEFAULTS.topk,
      similarity: AIDP_CREATE_DEFAULTS.similarity,
      caption_enable: AIDP_CREATE_DEFAULTS.caption_enable === 1,
      is_exist_graph: AIDP_CREATE_DEFAULTS.is_exist_graph,
      graph_domain: AIDP_CREATE_DEFAULTS.graph_domain,
      graph_hop: AIDP_CREATE_DEFAULTS.graph_hop,
      graph_thinking: AIDP_CREATE_DEFAULTS.graph_thinking,
      graph_prompt_language: AIDP_CREATE_DEFAULTS.graph_prompt_language,
      graph_synonym_merge: AIDP_CREATE_DEFAULTS.graph_synonym_merge,
      graph_disambiguation: AIDP_CREATE_DEFAULTS.graph_disambiguation,
      graph_prompt_text: "",
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
    setValidating(true);
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
            retrieve_subgraph_hop: String(
              values.graph_hop ?? AIDP_CREATE_DEFAULTS.graph_hop
            ),
            // The UI switch is the inverse of the submitted thinking mode.
            no_think_mode: values.graph_thinking ? "否" : "是",
            prompt_language:
              values.graph_prompt_language ||
              AIDP_CREATE_DEFAULTS.graph_prompt_language,
            prompt_text: values.graph_prompt_text,
            synonym_merge_enable: values.graph_synonym_merge ? "是" : "否",
            disambiguation_enable: values.graph_disambiguation ? "是" : "否",
            llm_model_name: values.llm_model_name,
          }
        : undefined;

      setValidating(false);
      const created = await createMutation.mutateAsync({
        name: values.name.trim(),
        description: values.description?.trim() || "",
        chunk_token_num: chunkTokens,
        chunk_overlap_num: overlapTokens,
        chunk_mode: values.chunk_mode ?? AIDP_CREATE_DEFAULTS.chunk_mode,
        embedding_model: values.embedding_model,
        topk: values.topk ?? AIDP_CREATE_DEFAULTS.topk,
        similarity: values.similarity ?? AIDP_CREATE_DEFAULTS.similarity,
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
      const result = handleError(error, {
        showMessage: false,
        handleSession: false,
      });
      message.error(result.message);
    } finally {
      setValidating(false);
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
        {(modelsQuery.isError || (graphEnabled && templateQuery.isError)) && (
          <Alert
            type="error"
            showIcon
            title={configurationErrorMessage}
            action={
              <Button
                onClick={() => {
                  void modelsQuery.refetch();
                  if (graphEnabled) void templateQuery.refetch();
                }}
              >
                {t("common.retry")}
              </Button>
            }
          />
        )}
        <AidpCreateKbSections
          form={form}
          t={t}
          canConfigureGroupPermissions={canConfigureGroupPermissions}
          groupOptions={groupOptions}
          ingroupPermission={ingroupPermission}
          llmModelOptions={llmModelOptions}
          llmModelsLoading={modelsQuery.isLoading}
          vlmModelOptions={vlmModelOptions}
          vlmModelsLoading={modelsQuery.isLoading}
          embeddingModelOptions={embeddingModelOptions}
          embeddingModelsLoading={modelsQuery.isLoading}
          graphTemplate={templateQuery.data}
          onRestorePrompt={restoreDefaultPrompt}
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
            disabled={
              modelsQuery.isPending ||
              modelsQuery.isError ||
              (graphEnabled &&
                (templateQuery.isPending || templateQuery.isError))
            }
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
