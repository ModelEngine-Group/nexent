// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useRef, useState } from "react";
import {
  Alert,
  Button,
  Flex,
  Form,
  Input,
  Modal,
  Select,
  Table,
  Typography,
} from "antd";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useModelList } from "@/hooks/model/useModelList";
import { evolutionService as api } from "@/services/evolutionService";
import { storageService } from "@/services/storageService";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";

function CaseForm({
  agent,
  version,
  close,
  saved,
}: {
  agent: number;
  version: number;
  close: () => void;
  saved: (id: number) => void;
}) {
  const { t } = useTranslation("common");
  const [files, setFiles] = useState<File[]>([]);
  const [form] = Form.useForm<{
    family: string;
    query: string;
    expected: string;
  }>();
  const mutation = useMutation({
    mutationFn: async () => {
      const values = await form.validateFields();
      const uploaded = files.length
        ? await storageService.uploadFiles(files)
        : undefined;
      if (
        uploaded &&
        (uploaded.failed_count || uploaded.results.length !== files.length)
      ) {
        throw new Error(t("evolution.attachmentFailed"));
      }
      const attachments =
        uploaded?.results.map((file, i) => ({
          name: files[i].name,
          object_name: file.object_name,
        })) || [];
      return api.createCase({
        ...values,
        agent_id: agent,
        version_no: version,
        attachments,
      });
    },
    onSuccess: (response) => saved(response.case_id),
  });
  return (
    <Modal
      open
      title={t("evolution.newCase")}
      onCancel={close}
      onOk={() => mutation.mutate()}
      confirmLoading={mutation.isPending}
      okText={t("evolution.saveCase")}
      cancelText={t("common.cancel")}
    >
      <Form form={form} layout="vertical">
        {(["family", "query", "expected"] as const).map((field) => (
          <Form.Item
            key={field}
            name={field}
            label={t(`evolution.${field}`)}
            rules={[{ required: true, whitespace: true }]}
          >
            {field === "family" ? (
              <Input maxLength={128} />
            ) : (
              <Input.TextArea rows={3} maxLength={16000} />
            )}
          </Form.Item>
        ))}
        <Form.Item label={t("evolution.attachments")}>
          <input
            type="file"
            multiple
            onChange={(e) => setFiles(Array.from(e.target.files || []))}
          />
        </Form.Item>
      </Form>
      {mutation.error instanceof Error && (
        <Alert type="error" message={mutation.error.message} />
      )}
    </Modal>
  );
}

function Experiments({
  agent,
  version,
  viewer,
}: {
  agent: number;
  version: number;
  viewer: string;
}) {
  const { t, i18n } = useTranslation("common");
  const { availableLlmModels } = useModelList();
  const [caseIds, setCases] = useState<number[]>([]);
  const [candidate, setCandidate] = useState<string>();
  const [evaluatorId, setEvaluator] = useState<number>();
  const [judge, setJudge] = useState<number>();
  const [selected, setSelected] = useState<number>();
  const [adding, setAdding] = useState(false);
  const previous = useRef({ selection: "", key: "" });
  const workspace = useQuery({
    queryKey: ["evolution", viewer, agent, version],
    queryFn: () => api.workspace(agent, version),
    retry: false,
  });
  const rules = useQuery({
    queryKey: ["evolution-evaluators", viewer],
    queryFn: api.evaluators,
  });
  const needsJudge =
    rules.data?.find((item) => item.evaluator_id === evaluatorId)
      ?.evaluator_type !== "code";
  const report = useQuery({
    queryKey: ["experiment-report", viewer, selected],
    queryFn: () => api.report(selected!),
    enabled: !!selected,
    retry: false,
    refetchInterval: (query) =>
      ["pending", "running"].includes(query.state.data?.status || "")
        ? 2000
        : false,
  });
  const start = useMutation({
    mutationFn: () => {
      const [kind, id] = candidate!.split(":");
      const params = {
        agent_id: agent,
        version_no: version,
        candidate_type: kind,
        candidate_id: Number(id),
        case_ids: caseIds,
        evaluator_id: evaluatorId!,
        judge_model_id: needsJudge ? judge : undefined,
        language: i18n.language.startsWith("zh") ? "zh" : "en",
      };
      const selection = JSON.stringify(params);
      if (previous.current.selection !== selection)
        previous.current = { selection, key: crypto.randomUUID() };
      return api.submit({ ...params, request_id: previous.current.key });
    },
    onSuccess: (result) => {
      previous.current.selection = "";
      setSelected(result.experiment_id);
      void workspace.refetch();
    },
  });
  const cancel = useMutation({
    mutationFn: () => api.cancel(selected!),
    onSuccess: () => {
      void report.refetch();
    },
  });
  const choices = workspace.data;
  const active = ["pending", "running"].includes(report.data?.status || "");
  const error =
    workspace.error ||
    rules.error ||
    start.error ||
    report.error ||
    cancel.error;
  return (
    <Flex vertical gap={14}>
      {error instanceof Error && (
        <Alert type="error" showIcon message={error.message} />
      )}
      {choices && (
        <>
          <Flex gap={8} wrap align="center">
            <Select
              aria-label={t("evolution.candidate")}
              placeholder={t("evolution.candidate")}
              style={{ minWidth: 220 }}
              value={candidate}
              onChange={setCandidate}
              options={choices.candidates.map((c) => ({
                value: `${c.kind}:${c.candidate_id}`,
                label: `#${c.candidate_id} · ${c.name}`,
              }))}
            />
            <Select
              mode="multiple"
              aria-label={t("evolution.cases")}
              placeholder={t("evolution.cases")}
              style={{ minWidth: 260 }}
              value={caseIds}
              onChange={setCases}
              options={choices.cases.map((c) => ({
                value: c.case_id,
                label: `${c.family} · ${c.query}`,
              }))}
            />
            <Button onClick={() => setAdding(true)}>
              {t("evolution.newCase")}
            </Button>
          </Flex>
          <Flex gap={8} wrap>
            <Select
              aria-label={t("evolution.evaluator")}
              placeholder={t("evolution.evaluator")}
              style={{ minWidth: 180 }}
              value={evaluatorId}
              onChange={setEvaluator}
              options={(rules.data || [])
                .filter((r) => r.status === "PUBLISHED")
                .map((r) => ({ value: r.evaluator_id, label: r.name }))}
            />
            {evaluatorId && needsJudge && (
              <Select
                aria-label={t("agentEvaluation.judgeModelLabel")}
                style={{ minWidth: 160 }}
                placeholder={t("agentEvaluation.judgeModelLabel")}
                value={judge}
                onChange={setJudge}
                options={availableLlmModels.map((m) => ({
                  value: m.id,
                  label: m.displayName || m.name,
                }))}
              />
            )}
            <Button
              type="primary"
              disabled={
                !candidate ||
                !caseIds.length ||
                !evaluatorId ||
                (needsJudge && !judge)
              }
              loading={start.isPending}
              onClick={() => start.mutate()}
            >
              {t("evolution.compare")}
            </Button>
          </Flex>
          <Select
            aria-label={t("evolution.history")}
            placeholder={t("evolution.history")}
            style={{ maxWidth: 350 }}
            value={selected}
            onChange={setSelected}
            options={choices.experiments.map((e) => ({
              value: e.experiment_id,
              label: `#${e.experiment_id} · ${new Date(e.create_time).toLocaleString()}`,
            }))}
          />
        </>
      )}
      {report.data && (
        <>
          <Flex gap={12} align="center">
            <Typography.Text>
              {t("evolution.coverage", {
                valid: report.data.valid_pairs,
                total: report.data.total_pairs,
              })}
            </Typography.Text>
            {active && (
              <Button
                onClick={() => cancel.mutate()}
                loading={cancel.isPending}
              >
                {t("evolution.cancel")}
              </Button>
            )}
          </Flex>
          <Table
            pagination={false}
            rowKey="id"
            dataSource={Object.entries(report.data.pairs).map(([id, p]) => ({
              id,
              ...p,
            }))}
            columns={[
              {
                title: t("evolution.cases"),
                dataIndex: "id",
                render: (id) =>
                  choices?.cases.find((c) => String(c.case_id) === id)
                    ?.family || id,
              },
              ...(["base", "result"] as const).map((key) => ({
                title: t(`evolution.${key}`),
                dataIndex: key,
                render: (trial: {
                  status: string;
                  result?: { answer?: string; error?: string };
                }) => (
                  <div>
                    <strong>{t(`evolution.state.${trial.status}`)}</strong>
                    <div className="whitespace-pre-wrap">
                      {trial.result?.answer || trial.result?.error}
                    </div>
                  </div>
                ),
              })),
              {
                title: t("evolution.change"),
                dataIndex: "comparison",
                render: (value) => t(`evolution.state.${value}`),
              },
            ]}
          />
        </>
      )}
      {adding && (
        <CaseForm
          agent={agent}
          version={version}
          close={() => setAdding(false)}
          saved={(id) => {
            setCases((current) => [...new Set([...current, id])]);
            setAdding(false);
            void workspace.refetch();
          }}
        />
      )}
    </Flex>
  );
}

export default function EvolutionExperiments() {
  const { user } = useAuthorizationContext();
  if (!user) return null;
  const viewer = JSON.stringify([user.tenantId, user.id]);
  return <AgentPicker key={viewer} viewer={viewer} />;
}

function AgentPicker({ viewer }: { viewer: string }) {
  const { t } = useTranslation("common");
  const [agent, setAgent] = useState<number>();
  const [version, setVersion] = useState<number>();
  const agents = useQuery({
    queryKey: ["evolution-agents", viewer],
    queryFn: api.agents,
  });
  const versions = useQuery({
    queryKey: ["evolution-versions", viewer, agent],
    queryFn: () => api.versions(agent!),
    enabled: !!agent,
  });
  const error = agents.error || versions.error;
  return (
    <Flex vertical gap={16}>
      {error instanceof Error && <Alert type="error" message={error.message} />}
      <Flex gap={8}>
        <Select
          showSearch
          optionFilterProp="label"
          aria-label={t("agentEvaluation.agentLabel")}
          value={agent}
          style={{ minWidth: 230 }}
          placeholder={t("agentEvaluation.selectAgent")}
          options={agents.data?.map((a) => ({
            value: a.agent_id,
            label: a.display_name || a.name,
          }))}
          onChange={(id) => {
            setAgent(id);
            setVersion(undefined);
          }}
        />
        <Select
          aria-label={t("agentEvaluation.agentVersionLabel")}
          disabled={!agent}
          value={version}
          style={{ minWidth: 150 }}
          placeholder={t("agentEvaluation.agentVersionLabel")}
          onChange={setVersion}
          options={versions.data
            ?.filter((v) => v.version_no > 0)
            .map((v) => ({
              value: v.version_no,
              label: `V${v.version_no} ${v.version_name || ""}`,
            }))}
        />
      </Flex>
      {agent && version && (
        <Experiments
          key={`${agent}:${version}`}
          agent={agent}
          version={version}
          viewer={viewer}
        />
      )}
    </Flex>
  );
}
