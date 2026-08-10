"use client";

import { useEffect, useMemo, useState, type FC } from "react";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/navigation";
import {
  Alert,
  Button,
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
  const { t } = useTranslation();
  const router = useRouter();
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
        if (!cancelled) message.error(t("chat.knowledgeScope.listLoadFailed"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, value, capabilities, t]);

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
      message.error(t("chat.knowledgeScope.embeddingMismatch"));
      return false;
    }
    return true;
  };

  const handleConfirm = async () => {
    if (
      draft.local.mode === "override" &&
      draft.local.knowledge_ids.length === 0
    ) {
      message.warning(t("chat.knowledgeScope.selectLocal"));
      return;
    }
    if (draft.aidp.mode === "override" && draft.aidp.kds_ids.length === 0) {
      message.warning(t("chat.knowledgeScope.selectAidp"));
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
          <Radio value="inherit">{t("chat.knowledgeScope.modeInherit")}</Radio>
          <Radio value="override">
            {t("chat.knowledgeScope.modeOverride")}
          </Radio>
          <Radio value="disabled">
            {t("chat.knowledgeScope.modeDisabled")}
          </Radio>
        </Radio.Group>

        {mode === "override" && (
          <div className="max-h-64 overflow-y-auto rounded-md border border-border p-3">
            {options.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("chat.knowledgeScope.empty")}
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
                    message.warning(
                      t("chat.knowledgeScope.maxSelect", { count: maxSelect })
                    );
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
            message={t("chat.knowledgeScope.disabledMessage", {
              source:
                source === "local" ? t("chat.knowledgeScope.local") : "AIDP",
            })}
          />
        )}
      </div>
    );
  };

  const items = [];
  if (capabilities?.sources.local.enabled) {
    items.push({
      key: "local",
      label: t("chat.knowledgeScope.localTab"),
      children: renderSource("local"),
    });
  }
  if (capabilities?.sources.aidp.enabled) {
    items.push({
      key: "aidp",
      label: t("chat.knowledgeScope.aidpTab"),
      children: renderSource("aidp"),
    });
  }

  return (
    <Modal
      title={t("chat.knowledgeScope.title")}
      open={open}
      onCancel={onCancel}
      onOk={handleConfirm}
      okText={t("chat.knowledgeScope.confirm")}
      cancelText={t("chat.knowledgeScope.cancel")}
      confirmLoading={saving}
      footer={(_, { OkBtn, CancelBtn }) => (
        <div className="flex items-center justify-between">
          <button
            type="button"
            className="text-sm text-muted-foreground hover:text-foreground"
            onClick={() => void onRestoreDefault()}
          >
            {t("chat.knowledgeScope.restoreDefault")}
          </button>
          <div className="flex gap-2">
            <CancelBtn />
            <OkBtn />
          </div>
        </div>
      )}
    >
      {value &&
        ((value.local.mode === "override" &&
          !capabilities?.sources.local.enabled) ||
          (value.aidp.mode === "override" &&
            !capabilities?.sources.aidp.enabled)) && (
          <Alert
            className="mb-3"
            type="warning"
            showIcon
            message={t("chat.knowledgeScope.incompatible")}
          />
        )}
      {capabilities?.legacy_prompt_warning?.detected && (
        <Alert
          className="mb-3"
          type="warning"
          showIcon
          message={t("chat.knowledgeScope.legacyPromptWarning")}
          description={t("chat.knowledgeScope.affectedAgents", {
            ids: capabilities.legacy_prompt_warning.affected_agent_ids.join(
              ", "
            ),
          })}
          action={
            <Button
              size="small"
              onClick={() => {
                onCancel();
                router.push("/agents");
              }}
            >
              {t("chat.knowledgeScope.goToAgentConfig")}
            </Button>
          }
        />
      )}
      <Spin spinning={loading}>
        {items.length > 0 ? (
          <Tabs items={items} />
        ) : (
          <Empty description={t("chat.knowledgeScope.noTool")} />
        )}
      </Spin>
    </Modal>
  );
};
