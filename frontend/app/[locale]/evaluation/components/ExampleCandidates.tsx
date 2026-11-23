// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useState } from "react";
import { Alert, Button, Form, Input, Modal, Select, Space } from "antd";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  evolutionService,
  type ApprovedExample,
  type ExperimentReport,
  type Workspace,
} from "@/services/evolutionService";

interface Fields {
  target: number;
  behavior: string;
  examples: (Omit<ApprovedExample, "case_id" | "variant"> & {
    trial: string;
  })[];
}

export default function ExampleCandidates({
  report,
  cases,
  onGenerated,
}: {
  report: ExperimentReport;
  cases: Workspace["cases"];
  onGenerated: (id: number) => void;
}) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<Fields>();
  const pairs = Object.entries(report.pairs);
  const label = (id: string) =>
    cases.find((c) => c.case_id === Number(id))?.family || id;
  const targets = pairs
    .filter(([, pair]) => pair.base.status === "fail")
    .map(([id]) => ({ value: Number(id), label: label(id) }));
  const passed = pairs.flatMap(([id, pair]) =>
    (["base", "result"] as const)
      .filter((v) => pair[v].status === "pass")
      .map((v) => ({
        value: `${id}:${v}`,
        label: `${label(id)} · ${t(`evolution.${v}`)}`,
      }))
  );
  const generate = useMutation({
    mutationFn: async () => {
      const values = await form.validateFields();
      return evolutionService.exampleCandidates(report.experiment_id, {
        target_case_id: values.target,
        target_behavior: values.behavior,
        examples: values.examples.map(
          ({ trial, attachment_name, ...sample }) => {
            const [id, variant] = trial.split(":");
            return {
              ...sample,
              attachment_name: attachment_name?.trim() || undefined,
              case_id: Number(id),
              variant: variant as ApprovedExample["variant"],
            };
          }
        ),
      });
    },
  });
  if (!targets.length || !passed.length) return null;
  const required = [{ required: true }];
  return (
    <>
      <Button
        onClick={() => {
          generate.reset();
          setOpen(true);
        }}
      >
        {t("evolution.selectExamples")}
      </Button>
      <Modal
        open={open}
        title={t("evolution.selectExamples")}
        onCancel={() => setOpen(false)}
        footer={generate.isSuccess ? null : undefined}
        okText={t("evolution.generateExamples")}
        confirmLoading={generate.isPending}
        onOk={() => generate.mutate()}
      >
        {generate.isSuccess ? (
          <Space wrap>
            {generate.data.variants
              .filter((v) => v.candidate_id !== null)
              .map((v) => (
                <Button
                  key={v.candidate_id}
                  onClick={() => {
                    onGenerated(v.candidate_id!);
                    setOpen(false);
                  }}
                >
                  {t("evolution.tryExampleCandidate", {
                    count: v.example_count,
                    id: v.candidate_id,
                  })}
                </Button>
              ))}
          </Space>
        ) : (
          <Form
            form={form}
            layout="vertical"
            initialValues={{ examples: [{}] }}
          >
            <Form.Item
              name="target"
              label={t("evolution.failedTarget")}
              rules={required}
            >
              <Select options={targets} />
            </Form.Item>
            <Form.Item
              name="behavior"
              label={t("evolution.targetBehavior")}
              rules={required}
            >
              <Input maxLength={128} />
            </Form.Item>
            <Form.List name="examples">
              {(fields, { add, remove }) => (
                <>
                  {fields.map(({ key, name }) => (
                    <section key={key}>
                      <Form.Item
                        name={[name, "trial"]}
                        label={t("evolution.passingTrial")}
                        rules={required}
                      >
                        <Select options={passed} />
                      </Form.Item>
                      <Form.Item
                        name={[name, "behavior"]}
                        label={t("evolution.exampleBehavior")}
                        rules={required}
                      >
                        <Input maxLength={128} />
                      </Form.Item>
                      <Form.Item
                        name={[name, "attachment_name"]}
                        label={t("evolution.exampleAttachment")}
                      >
                        <Input maxLength={240} />
                      </Form.Item>
                      {(["input_excerpt", "output_excerpt"] as const).map(
                        (field) => (
                          <Form.Item
                            key={field}
                            name={[name, field]}
                            label={t(`evolution.${field}`)}
                            rules={required}
                          >
                            <Input.TextArea rows={2} maxLength={1200} />
                          </Form.Item>
                        )
                      )}
                      {fields.length > 1 && (
                        <Button onClick={() => remove(name)}>
                          {t("evolution.removeExample")}
                        </Button>
                      )}
                    </section>
                  ))}
                  {fields.length < 20 && (
                    <Button onClick={() => add()}>
                      {t("evolution.addExample")}
                    </Button>
                  )}
                </>
              )}
            </Form.List>
            {generate.error instanceof Error && (
              <Alert type="error" message={generate.error.message} />
            )}
          </Form>
        )}
      </Modal>
    </>
  );
}
