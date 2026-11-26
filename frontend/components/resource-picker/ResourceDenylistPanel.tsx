// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { Alert, Button, Space, Table, Tag } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import {
  loadResourceDenylist,
  saveResourceDenylist,
} from "@/services/resourceDenylistService";
import type { DenylistState } from "@/types/resourceDenylist";
import {
  denylistResourceKind,
  denylistSelectedGroups,
} from "@/lib/resourceDenylist";
import { ResourceDenylistDrawer } from "./ResourceDenylistDrawer";

type ResourceDenylistPanelProps =
  { scope: "global"; tenantId?: never } | { scope: "tenant"; tenantId: string };

export function ResourceDenylistPanel({
  scope,
  tenantId,
}: ResourceDenylistPanelProps) {
  const { t } = useTranslation("common");
  const client = useQueryClient();
  const queryKey = ["resourceDenylist", scope, tenantId];
  const [editing, setEditing] = useState<DenylistState>();
  const [editingSession, setEditingSession] = useState(0);
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => loadResourceDenylist(scope, signal),
    refetchOnMount: "always",
  });
  const save = useMutation({
    mutationFn: (selected: string[]) =>
      saveResourceDenylist(scope, editing!.revision, selected),
    onSuccess: async (data) => {
      client.setQueryData(queryKey, data);
      setEditing(undefined);
      await Promise.all([
        client.invalidateQueries({ queryKey: ["tools"] }),
        client.invalidateQueries({ queryKey: ["skills"] }),
        client.invalidateQueries({ queryKey: ["resourceDenylist"] }),
      ]);
    },
  });
  const open = () => {
    if (query.data && !query.isError) {
      save.reset();
      setEditing(query.data);
    }
  };
  const selectedKeys = new Set(query.data?.selected);
  const groups = denylistSelectedGroups(
    scope,
    query.data?.items ?? [],
    selectedKeys
  );
  const blocked = [...groups.global, ...groups.current];
  const counts = new Map<string, number>();
  for (const item of new Map(
    blocked.map((item) => [item.key, item])
  ).values()) {
    const kind = denylistResourceKind(item);
    counts.set(kind, (counts.get(kind) ?? 0) + 1);
  }

  return (
    <div className="w-full p-4" data-testid="resource-configuration">
      <div className="mb-4">
        <p className="m-0 text-[var(--color-text-secondary)]">
          {t(`resourceDenylist.${scope}Help`)}
        </p>
      </div>
      {query.isError && (
        <Alert
          className="mb-4"
          type="error"
          showIcon
          message={t("resourceDenylist.loadFailed")}
          action={
            <Button onClick={() => void query.refetch()}>
              {t("resourceDenylist.reload")}
            </Button>
          }
        />
      )}
      <Table
        rowKey="key"
        loading={query.isFetching}
        pagination={false}
        dataSource={[{ key: "resource-exclusions" }]}
        columns={[
          {
            title: t("resourceDenylist.configuration"),
            width: "25%",
            render: () => t("resourceDenylist.blockedResources"),
          },
          {
            title: t("resourceDenylist.description"),
            render: () => t("resourceDenylist.descriptionText"),
          },
          {
            title: t("resourceDenylist.currentValue"),
            render: () =>
              query.data ? (
                <Space wrap>
                  {counts.size
                    ? [...counts].map(([kind, count]) => (
                        <Tag key={kind}>
                          {t(`resourceDenylist.summary.${kind}`)} {count}
                        </Tag>
                      ))
                    : t("resourceDenylist.notConfigured")}
                </Space>
              ) : (
                "—"
              ),
          },
          {
            title: t("resourceDenylist.actions"),
            width: 120,
            render: () => (
              <Button
                type="link"
                onClick={open}
                disabled={!query.data || query.isError}
              >
                {t("resourceDenylist.details")}
              </Button>
            ),
          },
        ]}
      />
      {editing && (
        <ResourceDenylistDrawer
          scope={scope}
          key={`${scope}-${tenantId}-${editing.revision}-${editingSession}`}
          snapshot={editing}
          saving={save.isPending}
          error={save.isError}
          onClose={() => {
            if (!save.isPending) setEditing(undefined);
          }}
          onSave={(selected) => save.mutate(selected)}
          onReload={async () => {
            const result = await query.refetch();
            if (result.data && !result.isError) {
              save.reset();
              setEditing(result.data);
              // Reset the local draft even if the server revision and cached data are unchanged.
              setEditingSession((current) => current + 1);
            }
          }}
        />
      )}
    </div>
  );
}
