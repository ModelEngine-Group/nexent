// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Form, Input, Select } from "antd";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import {
  evolutionService as api,
  type ExperimentReport,
  type NewSkillBrief,
  type Workspace,
} from "@/services/evolutionService";

export default function NewSkillBriefForm({
  report,
  workspace,
}: {
  report: ExperimentReport;
  workspace: Workspace;
}) {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const [form] = Form.useForm<NewSkillBrief>();
  const successes = Form.useWatch("successes", form) || [];
  const cases = workspace.cases.filter(
    (c) =>
      report.pairs[c.case_id]?.base &&
      !report.fixed_regression?.case_ids.includes(c.case_id)
  );
  const options = cases.map((c) => ({
    value: c.case_id,
    label: `#${c.case_id} ${c.query}`,
  }));
  const required = [{ required: true }];
  const submit = useMutation({
    mutationFn: async () =>
      api.newSkillBrief(report.experiment_id, await form.validateFields()),
  });
  return (
    <details>
      <summary>{t("evolution.newSkill.title")}</summary>
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          creator_id: user?.id,
          parameters: [],
          covered: [],
          successes: [
            { outcomes: [], private_values: [] },
            { outcomes: [], private_values: [] },
          ],
        }}
      >
        <Form.Item
          name="name"
          label={t("evolution.newSkill.name")}
          rules={[
            { required: true, pattern: /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/ },
          ]}
        >
          <Input maxLength={80} />
        </Form.Item>
        <Form.Item
          name="creator_id"
          label={t("evolution.newSkill.creator")}
          rules={required}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="purpose"
          label={t("evolution.newSkill.purpose")}
          rules={required}
        >
          <Input maxLength={350} />
        </Form.Item>
        <Form.Item
          name="skip_when"
          label={t("evolution.newSkill.skip")}
          rules={required}
        >
          <Input maxLength={350} />
        </Form.Item>
        <Form.Item name="parameters" label={t("evolution.newSkill.inputs")}>
          <Select mode="tags" />
        </Form.Item>
        <Form.List name="successes">
          {(fields, { add, remove }) => (
            <>
              {fields.map((field) => (
                <fieldset key={field.key} className="mb-3 border p-3">
                  <Form.Item
                    name={[field.name, "case_id"]}
                    label={t("evolution.newSkill.success")}
                    rules={required}
                  >
                    <Select
                      options={options.filter(
                        (o) =>
                          report.pairs[o.value].base.status === "pass" &&
                          !successes.some(
                            (s, i) => i !== field.name && s?.case_id === o.value
                          )
                      )}
                    />
                  </Form.Item>
                  <Form.Item
                    name={[field.name, "private_values"]}
                    label={t("evolution.newSkill.private")}
                  >
                    <Select mode="tags" />
                  </Form.Item>
                  <Form.List name={[field.name, "outcomes"]}>
                    {(items, ops) => (
                      <>
                        {items.map((item) => (
                          <div key={item.key}>
                            <Form.Item
                              name={[item.name, "step"]}
                              label={t("evolution.newSkill.step")}
                              rules={required}
                            >
                              <Input />
                            </Form.Item>
                            <Form.Item
                              name={[item.name, "excerpt"]}
                              label={t("evolution.newSkill.excerpt")}
                              rules={required}
                            >
                              <Input />
                            </Form.Item>
                            <Button
                              size="small"
                              onClick={() => ops.remove(item.name)}
                            >
                              {t("evolution.newSkill.remove")}
                            </Button>
                          </div>
                        ))}
                        <Button size="small" onClick={() => ops.add()}>
                          {t("evolution.newSkill.addStep")}
                        </Button>
                      </>
                    )}
                  </Form.List>
                  {fields.length > 2 && (
                    <Button onClick={() => remove(field.name)}>
                      {t("evolution.newSkill.remove")}
                    </Button>
                  )}
                </fieldset>
              ))}
              {fields.length < 10 && (
                <Button
                  onClick={() => add({ outcomes: [], private_values: [] })}
                >
                  {t("evolution.newSkill.addCase")}
                </Button>
              )}
            </>
          )}
        </Form.List>
        <Form.Item
          name="counterexample_id"
          label={t("evolution.newSkill.counter")}
          rules={required}
        >
          <Select
            options={options.filter(
              (o) => !successes.some((s) => s?.case_id === o.value)
            )}
          />
        </Form.Item>
        <Form.List name="covered">
          {(fields, { add, remove }) => (
            <>
              {fields.map((field) => (
                <div key={field.key}>
                  <Form.Item
                    name={[field.name, "skill"]}
                    label={t("evolution.newSkill.existing")}
                    rules={required}
                  >
                    <Select
                      options={workspace.skills?.map((s) => ({
                        value: s.name,
                        label: s.name,
                      }))}
                    />
                  </Form.Item>
                  <Form.Item
                    name={[field.name, "step"]}
                    label={t("evolution.newSkill.coveredStep")}
                    rules={required}
                  >
                    <Input />
                  </Form.Item>
                  <Form.Item
                    name={[field.name, "passage"]}
                    label={t("evolution.newSkill.passage")}
                    rules={required}
                  >
                    <Input />
                  </Form.Item>
                  <Button onClick={() => remove(field.name)}>
                    {t("evolution.newSkill.remove")}
                  </Button>
                </div>
              ))}
              {!!workspace.skills?.length && (
                <Button onClick={() => add()}>
                  {t("evolution.newSkill.addCovered")}
                </Button>
              )}
            </>
          )}
        </Form.List>
        <Button
          type="primary"
          loading={submit.isPending}
          onClick={() => submit.mutate()}
        >
          {t("evolution.newSkill.submit")}
        </Button>
      </Form>
      {submit.error && <Alert type="error" message={submit.error.message} />}
      {submit.data && (
        <Alert
          type="success"
          message={t("evolution.feedbackCreated", {
            id: submit.data.feedback_id,
          })}
          description={submit.data.steps.join(" → ")}
        />
      )}
    </details>
  );
}
