// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useState } from "react";
import {
  Alert,
  Button,
  Descriptions,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
} from "antd";
import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  evolutionService as api,
  type PublicBenchmarkInput,
} from "@/services/evolutionService";

const textFields = [
  ["dataset", 128, true],
  ["revision", 128, true],
  ["subset", 128, true],
  ["scoring_protocol", 512, true],
  ["adaptation", 512, false],
  ["run_reference", 512, false],
  ["metric", 80, true],
] as const;

export default function PublicBenchmarkReports({
  experiment,
  viewer,
}: {
  experiment: number;
  viewer: string;
}) {
  const { t } = useTranslation("common");
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form] = Form.useForm<PublicBenchmarkInput>();
  const cache = useQueryClient();
  const queryKey = ["evolution-public-benchmarks", viewer, experiment];
  const reports = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam }) => api.publicBenchmarks(experiment, pageParam),
    enabled: expanded,
    initialPageParam: null as number | null,
    getNextPageParam: (last) => last.next_before,
    retry: false,
  });
  const save = useMutation({
    mutationFn: (values: PublicBenchmarkInput) =>
      api.recordPublicBenchmark(experiment, values),
    onSuccess: async () => {
      await cache.invalidateQueries({ queryKey });
      form.resetFields();
      setEditing(false);
    },
  });
  const label = (field: string) => t(`evolution.publicBenchmark.${field}`);

  return (
    <details onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary className="cursor-pointer">{label("title")}</summary>
      {expanded && (
        <Flex vertical gap={12} className="py-3">
          <span>{label("scope")}</span>
          {reports.error && (
            <Alert
              type="error"
              message={reports.error.message}
              action={
                <Button onClick={() => reports.refetch()}>
                  {label("retry")}
                </Button>
              }
            />
          )}
          <Button
            className="self-start"
            onClick={() => {
              save.reset();
              setEditing(true);
            }}
          >
            {label("add")}
          </Button>
          {reports.data?.pages
            .flatMap((page) => page.items)
            .map((report) => (
              <Descriptions
                key={report.report_id}
                bordered
                size="small"
                column={1}
                title={`${report.dataset} · ${report.revision} · ${report.subset}`}
              >
                <Descriptions.Item label={label("scores")}>
                  {t("evolution.publicBenchmark.comparison", {
                    metric: report.metric,
                    count: report.sample_count,
                    base: report.baseline_score,
                    candidate: report.candidate_score,
                  })}
                </Descriptions.Item>
                <Descriptions.Item label={label("scoring_protocol")}>
                  {report.scoring_protocol}
                </Descriptions.Item>
                {report.adaptation && (
                  <Descriptions.Item label={label("adaptation")}>
                    {report.adaptation}
                  </Descriptions.Item>
                )}
                {report.run_reference && (
                  <Descriptions.Item label={label("run_reference")}>
                    {report.run_reference}
                  </Descriptions.Item>
                )}
              </Descriptions>
            ))}
          {reports.hasNextPage && (
            <Button
              loading={reports.isFetchingNextPage}
              onClick={() => reports.fetchNextPage()}
            >
              {label("more")}
            </Button>
          )}
        </Flex>
      )}
      <Modal
        open={editing}
        title={label("add")}
        onOk={() => form.submit()}
        confirmLoading={save.isPending}
        onCancel={() => {
          if (!save.isPending) setEditing(false);
        }}
      >
        {save.error && <Alert type="error" message={save.error.message} />}
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => save.mutate(values)}
        >
          {textFields.map(([field, maxLength, required]) => (
            <Form.Item
              key={field}
              name={field}
              label={label(field)}
              rules={[{ required, whitespace: required }]}
            >
              <Input maxLength={maxLength} />
            </Form.Item>
          ))}
          <Form.Item
            name="sample_count"
            label={label("sample_count")}
            rules={[
              { required: true, type: "integer", min: 1, max: 2147483647 },
            ]}
          >
            <InputNumber min={1} max={2147483647} precision={0} />
          </Form.Item>
          <Flex gap={12} wrap>
            {(["baseline_score", "candidate_score"] as const).map((field) => (
              <Form.Item
                key={field}
                name={field}
                label={label(field)}
                rules={[{ required: true, type: "number" }]}
              >
                <InputNumber />
              </Form.Item>
            ))}
          </Flex>
        </Form>
      </Modal>
    </details>
  );
}
