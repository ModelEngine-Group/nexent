// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useRef } from "react";
import { Globe } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  AgentDrawer,
  toLocalCard,
  toExternalCard,
} from "@/components/resource-picker/AgentDrawer";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { useExternalAgents } from "@/hooks/agent/useExternalAgents";
import { useAgentStore } from "@/stores/agentStore";
import { synchronizeExternalAgentRelations } from "@/lib/externalAgentRelations";
import { a2aClientService } from "@/services/a2aService";

/** Configuration-specific persistence, including partial-success retry bookkeeping. */
export function AgentConfigurationDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation("common");
  const agentId = useAgentStore((state) => state.agentId);
  const editedAgent = useAgentStore((state) => state.editedAgent);
  const internal = usePublishedAgentList();
  const external = useExternalAgents();
  const synchronizedIds = useRef<number[]>([]);
  const session = useRef<{ open: boolean; agentId: number | null }>({
    open: false,
    agentId: null,
  });
  useEffect(() => {
    if (
      open &&
      (!session.current.open || session.current.agentId !== agentId)
    ) {
      synchronizedIds.current = [
        ...(editedAgent?.external_sub_agent_id_list ?? []),
      ];
    }
    session.current = { open, agentId };
  }, [open, agentId, editedAgent]);
  const internalAgents = internal.availableAgents.filter(
    (agent) => Number(agent.id) !== agentId
  );
  const selected = [
    ...(editedAgent?.sub_agent_id_list ?? []).map((id) => ({
      id: `internal-${id}`,
      label:
        internal.availableAgents.find((agent) => Number(agent.id) === id)
          ?.display_name ||
        internal.availableAgents.find((agent) => Number(agent.id) === id)
          ?.name ||
        String(id),
    })),
    ...(editedAgent?.external_sub_agent_id_list ?? []).map((id) => ({
      id: `external-${id}`,
      label:
        external.availableAgents.find((agent) => Number(agent.id) === id)
          ?.name || String(id),
    })),
  ];
  return (
    <AgentDrawer
      key={agentId ?? "new"}
      open={open}
      onClose={onClose}
      selected={selected}
      categories={[
        {
          key: "internal",
          label: t("resourcePicker.tab.localAgent", "本地智能体"),
          loading: internal.isLoading,
          error: internal.error?.message,
          items: internalAgents.map((agent) => ({
            ...toLocalCard(agent),
            id: `internal-${agent.id}`,
          })),
        },
        {
          key: "external",
          supportsTagFilter: false,
          label: t("resourcePicker.tab.externalAgent", "外部智能体"),
          loading: external.isLoading,
          error: external.error?.message,
          icon: <Globe size={20} />,
          items: external.availableAgents.map((agent) => ({
            ...toExternalCard(agent),
            id: `external-${agent.id}`,
          })),
        },
      ]}
      onRefresh={() => {
        void internal.invalidate();
        void external.invalidate();
      }}
      onConfirm={async (selection) => {
        const internalIds = selection
          .filter((item) => item.id.startsWith("internal-"))
          .map((item) => Number(item.id.slice(9)));
        const externalIds = selection
          .filter((item) => item.id.startsWith("external-"))
          .map((item) => Number(item.id.slice(9)));
        if (agentId) {
          const {
            synchronizedIds: nextIds,
            succeeded,
            failed,
          } = await synchronizeExternalAgentRelations(
            Number(agentId),
            synchronizedIds.current,
            externalIds,
            a2aClientService
          );
          synchronizedIds.current = nextIds;
          if (failed > 0) {
            if (succeeded > 0)
              useAgentStore.getState().updateExternalSubAgentIds(nextIds);
            throw new Error(
              succeeded > 0
                ? t("a2a.service.syncRelationsPartialFailed", {
                    succeeded,
                    failed,
                  })
                : t("a2a.service.addRelationFailed")
            );
          }
        }
        if (useAgentStore.getState().agentId !== agentId) {
          throw new Error(t("a2a.service.addRelationFailed"));
        }
        const existing = editedAgent?.sub_agent_relations ?? [];
        const relations = internalIds.map((id) => {
          const retained = existing.find(
            (relation) => relation.agent_id === id
          );
          if (retained) return retained;
          const agent = internal.availableAgents.find(
            (entry) => Number(entry.id) === id
          );
          return {
            agent_id: id,
            version_no: agent?.current_version_no ?? null,
            version_name: agent?.version_name,
          };
        });
        const store = useAgentStore.getState();
        store.updateSubAgentIds(internalIds);
        store.updateSubAgentRelations(relations);
        store.updateExternalSubAgentIds(externalIds);
      }}
    />
  );
}
