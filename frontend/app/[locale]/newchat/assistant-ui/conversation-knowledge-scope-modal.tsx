"use client";

import { useEffect, useMemo, useState, type FC } from "react";
import {
  Alert,
  Checkbox,
  Empty,
  Modal,
  Radio,
  Spin,
  Tabs,
  message,
} from "antd";

import knowledgeBaseService from "@/services/knowledgeBaseService";
import type { KnowledgeBase } from "@/types/knowledgeBase";
import type {
  ConversationKnowledgeScope,
  KnowledgeCapabilities,
  KnowledgeScopeMode,
} from "@/types/knowledgeScope";
import { DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE } from "@/types/knowledgeScope";

interface ConversationKnowledgeScopeModalProps {
  open: boolean;
  value: ConversationKnowledgeScope | null;
  capabilities: KnowledgeCapabilities | null;
  onCancel: () => void;
  onConfirm: (scope: ConversationKnowledgeScope) => Promise<void> | void;
  onRestoreDefault: () => Promise<void> | void;
}

const copyScope = (
  value: ConversationKnowledgeScope | null
): ConversationKnowledgeScope =>
  JSON.parse(
    JSON.stringify(value || DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE)
  ) as ConversationKnowledgeScope;

export const ConversationKnowledgeScopeModal: FC<
  ConversationKnowledgeScopeModalProps
> = ({ open, value, capabilities, onCancel, onConfirm, onRestoreDefault }) => {
  const [draft, setDraft] = useState<ConversationKnowledgeScope>(() =>
    copyScope(value)
  );
  const [localKnowledgeBases, setLocalKnowledgeBases] = useState<
    KnowledgeBase[]
  >([]);
  const [aidpKnowledgeBases, setAidpKnowledgeBases] = useState<KnowledgeBase[]>(
    []
  );
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setDraft(copyScope(value));
    let cancelled = false;
    setLoading(true);
    Promise.all([
      capabilities?.sources.local.enabled
        ? knowledgeBaseService.getKnowledgeBasesInfo(false, false)
        : Promise.resolve({ knowledgeBases: [] }),
      capabilities?.sources.aidp.enabled
        ? knowledgeBaseService.getAidpKnowledgeBasesAll()
        : Promise.resolve({ value: [] }),
    ])
      .then(([localResult, aidpResult]) => {
        if (cancelled) return;
        setLocalKnowledgeBases(
          (localResult.knowledgeBases || []).filter(
            (kb: KnowledgeBase) =>
              kb.knowledge_id !== undefined && kb.knowledge_id !== null
          )
        );
        setAidpKnowledgeBases(
          knowledgeBaseService.mapAidpKnowledgeBasesToKnowledgeBases(
            aidpResult.value || []
          )
        );
      })
      .catch(() => {
        if (!cancelled) message.error("知识库列表加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, value, capabilities]);

  const localOptions = useMemo(
    () =>
      localKnowledgeBases
        .filter(
          (kb) => kb.knowledge_id !== undefined && kb.knowledge_id !== null
        )
        .map((kb) => ({
          label: kb.display_name || kb.name,
          value: String(kb.knowledge_id),
        })),
    [localKnowledgeBases]
  );
  const aidpOptions = useMemo(
    () =>
      aidpKnowledgeBases.map((kb) => ({
        label: kb.display_name || kb.name,
        value: kb.id,
      })),
    [aidpKnowledgeBases]
  );

  const updateMode = (source: "local" | "aidp", mode: KnowledgeScopeMode) => {
    setDraft((current) => ({
      ...current,
      [source]:
        source === "local"
          ? {
              mode,
              knowledge_ids:
                mode === "override" ? current.local.knowledge_ids : [],
            }
          : { mode, kds_ids: mode === "override" ? current.aidp.kds_ids : [] },
    }));
  };

  const validateLocalEmbeddingModels = (): boolean => {
    if (draft.local.mode !== "override") return true;
    const selected = new Set(draft.local.knowledge_ids);
    const models = new Set(
      localKnowledgeBases
        .filter(
          (kb) =>
            kb.knowledge_id !== undefined &&
            selected.has(String(kb.knowledge_id))
        )
        .map((kb) => String(kb.embeddingModelId ?? kb.embeddingModel ?? ""))
        .filter(Boolean)
    );
    if (models.size > 1) {
      message.error("本地知识库必须使用相同的向量化模型");
      return false;
    }
    return true;
  };

  const handleConfirm = async () => {
    if (
      draft.local.mode === "override" &&
      draft.local.knowledge_ids.length === 0
    ) {
      message.warning("请选择至少一个本地知识库");
      return;
    }
    if (draft.aidp.mode === "override" && draft.aidp.kds_ids.length === 0) {
      message.warning("请选择至少一个 AIDP 知识库");
      return;
    }
    if (!validateLocalEmbeddingModels()) return;
    setSaving(true);
    try {
      await onConfirm(draft);
    } finally {
      setSaving(false);
    }
  };

  const renderSource = (source: "local" | "aidp") => {
    const mode = draft[source].mode;
    const values =
      source === "local" ? draft.local.knowledge_ids : draft.aidp.kds_ids;
    const options = source === "local" ? localOptions : aidpOptions;
    return (
      <div className="space-y-4 py-2">
        <Radio.Group
          value={mode}
          onChange={(event) =>
            updateMode(source, event.target.value as KnowledgeScopeMode)
          }
          className="flex flex-col gap-2"
        >
          <Radio value="inherit">跟随智能体默认</Radio>
          <Radio value="override">指定知识库</Radio>
          <Radio value="disabled">当前对话禁用</Radio>
        </Radio.Group>

        {mode === "override" && (
          <div className="max-h-64 overflow-y-auto rounded-md border border-border p-3">
            {options.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无可用知识库"
              />
            ) : (
              <Checkbox.Group
                className="flex w-full flex-col gap-2"
                options={options}
                value={values}
                onChange={(selected) => {
                  const normalized = selected.map(String);
                  const maxSelect =
                    capabilities?.sources[source].max_select ?? 0;
                  if (maxSelect > 0 && normalized.length > maxSelect) {
                    message.warning(`最多选择 ${maxSelect} 个知识库`);
                    return;
                  }
                  setDraft((current) =>
                    source === "local"
                      ? {
                          ...current,
                          local: {
                            mode: "override",
                            knowledge_ids: normalized,
                          },
                        }
                      : {
                          ...current,
                          aidp: { mode: "override", kds_ids: normalized },
                        }
                  );
                }}
              />
            )}
          </div>
        )}

        {mode === "disabled" && (
          <Alert
            type="warning"
            showIcon
            message={`当前对话不会使用${source === "local" ? "本地" : " AIDP"}知识库`}
          />
        )}
      </div>
    );
  };

  const items = [];
  if (capabilities?.sources.local.enabled) {
    items.push({
      key: "local",
      label: "本地知识库",
      children: renderSource("local"),
    });
  }
  if (capabilities?.sources.aidp.enabled) {
    items.push({
      key: "aidp",
      label: "AIDP 知识库",
      children: renderSource("aidp"),
    });
  }

  return (
    <Modal
      title="当前对话知识库"
      open={open}
      onCancel={onCancel}
      onOk={handleConfirm}
      okText="确定"
      cancelText="取消"
      confirmLoading={saving}
      footer={(_, { OkBtn, CancelBtn }) => (
        <div className="flex items-center justify-between">
          <button
            type="button"
            className="text-sm text-muted-foreground hover:text-foreground"
            onClick={() => void onRestoreDefault()}
          >
            恢复默认
          </button>
          <div className="flex gap-2">
            <CancelBtn />
            <OkBtn />
          </div>
        </div>
      )}
    >
      <Spin spinning={loading}>
        {items.length > 0 ? (
          <Tabs items={items} />
        ) : (
          <Empty description="当前智能体未启用知识库工具" />
        )}
      </Spin>
    </Modal>
  );
};
