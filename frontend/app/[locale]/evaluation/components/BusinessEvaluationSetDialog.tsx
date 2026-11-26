// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useState } from "react";
import Link from "next/link";
import { Alert, Button, Flex, Input, Modal, Select, Table } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { businessSetKeys, evolutionService as api } from "@/services/evolutionService";
import { evolutionHref } from "./EvolutionDirections";

export default function BusinessEvaluationSetDialog({
  agent,
  viewer,
  setId,
  onCreated,
  close,
}: {
  agent: number;
  viewer: string;
  setId?: number;
  onCreated: (id: number) => void;
  close: () => void;
}) {
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const detail = useQuery({
    queryKey: businessSetKeys.detail(viewer, agent, setId),
    queryFn: () => api.businessSet(agent, setId!),
    enabled: !!setId,
  });
  const choices = useQuery({
    queryKey: businessSetKeys.choices(viewer, agent),
    queryFn: () => api.businessSetChoices(agent),
    enabled: !!setId,
  });
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: businessSetKeys.detail(viewer, agent, setId) }),
    queryClient.invalidateQueries({ queryKey: businessSetKeys.list(viewer, agent) }),
  ]);
  const create = useMutation({
    mutationFn: () => api.createBusinessSet(agent, name.trim()),
    onSuccess: (group) => {
      void refresh();
      onCreated(group.evaluation_set_id);
    },
  });
  const changeCases = useMutation({
    mutationFn: (operation: { add: number[] } | { remove: number }) => "add" in operation
      ? api.addBusinessSetCases(agent, setId!, operation.add)
      : api.removeBusinessSetCase(agent, setId!, operation.remove),
    onSuccess: async (_, operation) => {
      if ("add" in operation) setSelected([]);
      await refresh();
    },
  });
  const error = detail.error || choices.error || create.error || changeCases.error;
  const members = new Set(detail.data?.cases.map((item) => item.digest));

  return (
    <Modal
      open
      title={setId ? detail.data?.name ?? t("evolution.sets.manage") : t("evolution.sets.create")}
      onCancel={() => { if (!create.isPending && !changeCases.isPending) close(); }}
      width={640}
      footer={setId ? null : undefined}
      onOk={() => create.mutate()}
      okText={t("evolution.sets.create")}
      okButtonProps={{ disabled: !name.trim() }}
      cancelButtonProps={{ disabled: create.isPending }}
      confirmLoading={create.isPending}
    >
      <Flex vertical gap={12}>
        {error instanceof Error && <Alert type="error" message={error.message} />}
        {setId ? <>
          <Link href={`${evolutionHref(undefined, { agent, evaluationSet: setId })}&open_cases=1`}>
            {t("evolution.sets.openWorkflow")}
          </Link>
          <Flex gap={8}>
            <Select<number[]>
              mode="multiple"
              maxCount={100}
              showSearch={{ optionFilterProp: "label" }}
              aria-label={t("evolution.sets.existingCases")}
              placeholder={t("evolution.sets.existingCases")}
              className="flex-1"
              loading={choices.isFetching}
              value={selected}
              onChange={setSelected}
              options={choices.data?.filter((item) => !members.has(item.digest)).map((item) => ({
                value: item.case_id, label: `${item.family} · ${item.query}`,
              }))}
            />
            <Button disabled={!selected.length} loading={changeCases.isPending}
              onClick={() => changeCases.mutate({ add: selected })}>
              {t("evolution.sets.addCases")}
            </Button>
          </Flex>
          <Table
            size="small"
            loading={detail.isFetching}
            rowKey="case_id"
            dataSource={detail.data?.cases ?? []}
            columns={[
              { title: t("evolution.cases"), render: (_, row) => `${row.family} · ${row.query}` },
              { title: t("evolution.sets.source"), render: (_, row) => t(row.from_trace ? "evolution.sets.trace" : "evolution.sets.manual") },
              { title: t("agentEvaluation.colHeader.actions"), render: (_, row) => (
                <Button type="link" disabled={changeCases.isPending} onClick={() => changeCases.mutate({ remove: row.case_id })}>
                  {t("evolution.sets.remove")}
                </Button>
              ) },
            ]}
          />
        </> : <Input aria-label={t("evolution.sets.name")} placeholder={t("evolution.sets.name")}
          value={name} onChange={(event) => setName(event.target.value)} maxLength={100} />}
      </Flex>
    </Modal>
  );
}
