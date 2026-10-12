"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { DatabaseIcon, Loader2Icon, SearchIcon } from "lucide-react";
import { message, Switch } from "antd";
import { useTranslation } from "react-i18next";
import { useDeployment } from "@/components/providers/deploymentProvider";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import type { KnowledgeBase } from "@/types/knowledgeBase";
import type {
  ConversationKnowledgeScope,
  KnowledgeCapabilities,
  KnowledgeScopeEffectivePreview,
} from "@/types/knowledgeScope";
import { DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE } from "@/types/knowledgeScope";

// Content of the "知识库" toolbar Popover, replacing the former 920px scope
// Modal: search + switch-to-select list with immediate apply per toggle.
export interface KnowledgePopoverContentProps {
  value: ConversationKnowledgeScope | null;
  capabilities: KnowledgeCapabilities | null;
  onApply: (
    scope: ConversationKnowledgeScope,
    preview: KnowledgeScopeEffectivePreview
  ) => Promise<void> | void;
}

const normalizeScopeForSource = (
  value: ConversationKnowledgeScope | null,
  source: "local" | "aidp" | null
): ConversationKnowledgeScope => {
  const scope = JSON.parse(
    JSON.stringify(value || DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE)
  ) as ConversationKnowledgeScope;
  if (!source) return scope;
  if (scope.local.mode === "disabled" && scope.aidp.mode === "disabled") {
    return scope;
  }
  if (source === "local" && scope.local.mode === "inherit") {
    return {
      schema_version: 1,
      local: { mode: "inherit", knowledge_ids: [] },
      aidp: { mode: "disabled", kds_ids: [] },
    };
  }
  if (source === "aidp" && scope.aidp.mode === "inherit") {
    return {
      schema_version: 1,
      local: { mode: "disabled", knowledge_ids: [] },
      aidp: { mode: "inherit", kds_ids: [] },
    };
  }
  if (source === "local" && scope.local.mode === "override") {
    return { ...scope, aidp: { mode: "disabled", kds_ids: [] } };
  }
  if (source === "aidp" && scope.aidp.mode === "override") {
    return { ...scope, local: { mode: "disabled", knowledge_ids: [] } };
  }
  return {
    schema_version: 1,
    local: { mode: "disabled", knowledge_ids: [] },
    aidp: { mode: "disabled", kds_ids: [] },
  };
};

const sameSelection = (left: string[], right: string[]) => {
  const rightIds = new Set(right);
  return (
    left.length === right.length &&
    new Set(left).size === rightIds.size &&
    left.every((id) => rightIds.has(id))
  );
};

export function KnowledgePopoverContent({
  value,
  capabilities,
  onApply,
}: KnowledgePopoverContentProps) {
  const { t } = useTranslation();
  const router = useRouter();
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();
  const configuredSource: "local" | "aidp" | null = !isDeploymentReady
    ? null
    : enableAidpKnowledge
      ? "aidp"
      : "local";
  const [localKnowledgeBases, setLocalKnowledgeBases] = useState<
    KnowledgeBase[]
  >([]);
  const [aidpKnowledgeBases, setAidpKnowledgeBases] = useState<KnowledgeBase[]>(
    []
  );
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [applyingId, setApplyingId] = useState<string | null>(null);

  useEffect(() => {
    if (!configuredSource) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.all([
      configuredSource === "local"
        ? knowledgeBaseService.getKnowledgeBasesInfo(
            false,
            false,
            null,
            null,
            undefined,
            { strict: true }
          )
        : Promise.resolve({ knowledgeBases: [] }),
      configuredSource === "aidp"
        ? knowledgeBaseService.getAidpKnowledgeBasesAll()
        : Promise.resolve({ value: [] }),
    ])
      .then(([localResult, aidpResult]) => {
        if (cancelled) return;
        const localItems = (localResult.knowledgeBases || []).filter(
          (kb: KnowledgeBase) =>
            kb.knowledge_id !== undefined && kb.knowledge_id !== null
        );
        const aidpItems =
          knowledgeBaseService.mapAidpKnowledgeBasesToKnowledgeBases(
            aidpResult.value || []
          );
        setLocalKnowledgeBases(localItems);
        setAidpKnowledgeBases(aidpItems);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configuredSource]);

  const allKnowledgeBases =
    configuredSource === "aidp" ? aidpKnowledgeBases : localKnowledgeBases;

  const getKnowledgeBaseId = (knowledgeBase: KnowledgeBase) =>
    configuredSource === "local"
      ? String(knowledgeBase.knowledge_id)
      : String(knowledgeBase.id);

  const getEmbeddingIdentity = (knowledgeBase: KnowledgeBase) =>
    String(
      knowledgeBase.embeddingModelId ?? knowledgeBase.embeddingModel ?? ""
    );

  const defaultSelectedIds = useMemo(
    () =>
      (configuredSource
        ? capabilities?.sources[configuredSource].default_knowledge_ids
        : []
      )?.map(String) ?? [],
    [capabilities, configuredSource]
  );

  const selectedIds = useMemo(() => {
    if (!configuredSource) return [];
    const normalized = normalizeScopeForSource(value, configuredSource);
    if (configuredSource === "local") {
      if (normalized.local.mode === "override")
        return normalized.local.knowledge_ids.map(String);
      if (normalized.local.mode === "inherit") return defaultSelectedIds;
      return [];
    }
    if (normalized.aidp.mode === "override")
      return normalized.aidp.kds_ids.map(String);
    if (normalized.aidp.mode === "inherit") return defaultSelectedIds;
    return [];
  }, [value, configuredSource, defaultSelectedIds]);

  const filtered = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return allKnowledgeBases;
    return allKnowledgeBases.filter((kb) =>
      [kb.name, kb.display_name, kb.description].some((field) =>
        field?.toLowerCase().includes(keyword)
      )
    );
  }, [search, allKnowledgeBases]);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  const selectedKnowledgeBases = useMemo(
    () =>
      allKnowledgeBases.filter((kb) => selectedSet.has(getKnowledgeBaseId(kb))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [allKnowledgeBases, selectedSet]
  );
  const selectedLocalModel =
    configuredSource === "local" && selectedKnowledgeBases[0]
      ? getEmbeddingIdentity(selectedKnowledgeBases[0])
      : "";

  const applySelection = async (nextIds: string[]) => {
    if (!configuredSource) return;
    let nextScope: ConversationKnowledgeScope;
    if (nextIds.length === 0) {
      nextScope = {
        schema_version: 1,
        local: { mode: "disabled", knowledge_ids: [] },
        aidp: { mode: "disabled", kds_ids: [] },
      };
    } else if (sameSelection(nextIds, defaultSelectedIds)) {
      nextScope =
        configuredSource === "local"
          ? {
              schema_version: 1,
              local: { mode: "inherit", knowledge_ids: [] },
              aidp: { mode: "disabled", kds_ids: [] },
            }
          : {
              schema_version: 1,
              local: { mode: "disabled", knowledge_ids: [] },
              aidp: { mode: "inherit", kds_ids: [] },
            };
    } else {
      nextScope =
        configuredSource === "local"
          ? {
              schema_version: 1,
              local: { mode: "override", knowledge_ids: nextIds },
              aidp: { mode: "disabled", kds_ids: [] },
            }
          : {
              schema_version: 1,
              local: { mode: "disabled", knowledge_ids: [] },
              aidp: { mode: "override", kds_ids: nextIds },
            };
    }
    const namesById = new Map(
      allKnowledgeBases.map((kb) => [
        getKnowledgeBaseId(kb),
        kb.display_name || kb.name,
      ])
    );
    const preview: KnowledgeScopeEffectivePreview = {
      local: {
        disabled: nextScope.local.mode === "disabled",
        knowledge_ids:
          nextScope.local.mode === "override"
            ? nextScope.local.knowledge_ids
            : [],
        display_names:
          nextScope.local.mode === "override"
            ? nextScope.local.knowledge_ids.map((id) => namesById.get(id) ?? id)
            : [],
      },
      aidp: {
        disabled: nextScope.aidp.mode === "disabled",
        kds_ids:
          nextScope.aidp.mode === "override" ? nextScope.aidp.kds_ids : [],
        display_names:
          nextScope.aidp.mode === "override"
            ? nextScope.aidp.kds_ids.map((id) => namesById.get(id) ?? id)
            : [],
      },
    };
    setApplyingId(null);
    await onApply(nextScope, preview);
  };

  const toggle = async (knowledgeBase: KnowledgeBase, next: boolean) => {
    if (!configuredSource || loading) return;
    const id = getKnowledgeBaseId(knowledgeBase);
    if (!next) {
      setApplyingId(id);
      try {
        await applySelection(selectedIds.filter((value) => value !== id));
      } finally {
        setApplyingId(null);
      }
      return;
    }
    if (
      configuredSource === "local" &&
      selectedLocalModel &&
      getEmbeddingIdentity(knowledgeBase) &&
      getEmbeddingIdentity(knowledgeBase) !== selectedLocalModel
    ) {
      message.warning(t("chat.knowledgeScope.embeddingMismatch"));
      return;
    }
    const maxSelect =
      capabilities?.sources[configuredSource].max_select ??
      (configuredSource === "local" ? 50 : 10);
    if (maxSelect > 0 && selectedIds.length >= maxSelect) {
      message.warning(t("chat.knowledgeScope.maxSelect", { count: maxSelect }));
      return;
    }
    setApplyingId(id);
    try {
      await applySelection([...selectedIds, id]);
    } finally {
      setApplyingId(null);
    }
  };

  return (
    <div className="flex flex-col">
      <div className="px-3 pt-3 text-base leading-6 text-[#191919]">
        {t("chat.knowledgePopover.title")}
      </div>
      <div className="px-3 pt-2 pb-1">
        <div className="flex h-9 items-center gap-2 rounded-lg border border-border px-2">
          <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("chat.knowledgePopover.searchPlaceholder")}
            aria-label={t("chat.knowledgePopover.searchPlaceholder")}
            className="h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
        </div>
      </div>
      <div className="max-h-64 overflow-y-auto px-1.5 pb-1">
        {!configuredSource ? (
          <div className="flex h-20 items-center justify-center text-sm text-muted-foreground">
            {t("chat.knowledgeScope.noTool")}
          </div>
        ) : loading ? (
          <div className="flex h-20 items-center justify-center">
            <Loader2Icon
              className="size-4 animate-spin text-muted-foreground"
              aria-hidden
            />
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-20 items-center justify-center text-sm text-muted-foreground">
            {t("chat.knowledgeScope.empty")}
          </div>
        ) : (
          filtered.map((knowledgeBase) => {
            const id = getKnowledgeBaseId(knowledgeBase);
            const checked = selectedSet.has(id);
            const incompatible =
              configuredSource === "local" &&
              !checked &&
              Boolean(selectedLocalModel) &&
              Boolean(getEmbeddingIdentity(knowledgeBase)) &&
              getEmbeddingIdentity(knowledgeBase) !== selectedLocalModel;
            return (
              <div
                key={id}
                className="flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-[rgba(25,25,25,0.03)]"
              >
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-[#197BD51A] text-[#197BD5]">
                  <DatabaseIcon className="size-4" aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-base leading-6 text-[#191919]">
                    {knowledgeBase.display_name || knowledgeBase.name}
                  </div>
                  <div className="truncate text-sm leading-[22px] text-[rgba(25,25,25,0.5)]">
                    {incompatible
                      ? t("chat.knowledgeScope.embeddingMismatch")
                      : `${knowledgeBase.documentCount ?? 0} ${t("knowledgeBase.document", "篇文档")}`}
                  </div>
                </div>
                <Switch
                  size="small"
                  checked={checked}
                  disabled={incompatible || applyingId !== null}
                  onChange={(next) => void toggle(knowledgeBase, next)}
                />
              </div>
            );
          })
        )}
      </div>
      <div className="border-t px-3 py-2">
        <button
          type="button"
          className="text-sm leading-[22px] text-[#191919] hover:text-[#197BD5]"
          onClick={() => router.push("/knowledges")}
        >
          {t("chat.knowledgePopover.manageKnowledge")}
        </button>
      </div>
    </div>
  );
}
