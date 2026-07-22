"use client";

import React, { useEffect, useMemo, useState } from "react";
import { Alert, Input, InputNumber, Modal, Select, Switch } from "antd";

import type { Nl2AgentWebSkillConfiguration } from "@/services/nl2agentService";

type SkillField = NonNullable<
  Nl2AgentWebSkillConfiguration["config_schemas"]
>[number];

interface WebSkillConfigurationModalProps {
  open: boolean;
  skillName: string;
  schemas: SkillField[];
  defaults: Record<string, unknown>;
  onCancel: () => void;
  onSubmit: (values: Record<string, unknown>) => Promise<boolean>;
}

const isSecretField = (field: SkillField) =>
  Boolean(
    field.isSecret ||
    field.is_secret ||
    /password|authorization|api[_-]?key|secret|token/i.test(field.name)
  );

export const WebSkillConfigurationModal: React.FC<
  WebSkillConfigurationModalProps
> = ({ open, skillName, schemas, defaults, onCancel, onSubmit }) => {
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [structuredValues, setStructuredValues] = useState<
    Record<string, string>
  >({});
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    const initialValues = Object.fromEntries(
      schemas.flatMap((field) => {
        const value = defaults[field.name] ?? field.value ?? field.default;
        return value === undefined || value === null
          ? []
          : [[field.name, value]];
      })
    );
    setValues(initialValues);
    setStructuredValues(
      Object.fromEntries(
        schemas.flatMap((field) => {
          const value = initialValues[field.name];
          return field.type === "array" || field.type === "object"
            ? [[field.name, value === undefined ? "" : JSON.stringify(value)]]
            : [];
        })
      )
    );
    setError(undefined);
  }, [defaults, open, schemas]);

  const visibleSchemas = useMemo(
    () =>
      schemas.filter(
        (field) => !field.depends_on || Boolean(values[field.depends_on])
      ),
    [schemas, values]
  );

  const submit = async () => {
    const resolved = { ...values };
    try {
      for (const field of visibleSchemas) {
        if (field.type === "array" || field.type === "object") {
          const raw = structuredValues[field.name]?.trim() || "";
          if (raw) resolved[field.name] = JSON.parse(raw);
          else delete resolved[field.name];
        }
        const value = resolved[field.name];
        if (
          (field.required || field.optional === false) &&
          (value === undefined || value === null || value === "")
        ) {
          throw new Error(`${field.name} is required.`);
        }
      }
    } catch (caught) {
      setError(
        caught instanceof SyntaxError
          ? "Array and object values must be valid JSON."
          : caught instanceof Error
            ? caught.message
            : "Invalid Skill configuration."
      );
      return;
    }

    setSubmitting(true);
    setError(undefined);
    try {
      if (await onSubmit(resolved)) onCancel();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title={`Configure ${skillName}`}
      okText="Install"
      confirmLoading={submitting}
      onCancel={onCancel}
      onOk={() => void submit()}
      destroyOnHidden
    >
      <div className="space-y-3 py-2">
        {visibleSchemas.map((field) => {
          const required = field.required || field.optional === false;
          const label = `${field.name}${required ? " *" : ""}`;
          const description = field.description_en || field.description_zh;
          const update = (value: unknown) =>
            setValues((current) => ({ ...current, [field.name]: value }));
          return (
            <div key={field.name}>
              <div className="mb-1 text-sm font-medium text-gray-700">
                {label}
              </div>
              {description ? (
                <div className="mb-1 text-xs text-gray-500">{description}</div>
              ) : null}
              {field.choices?.length ? (
                <Select
                  aria-label={label}
                  className="w-full"
                  value={values[field.name]}
                  options={field.choices.map((choice) => ({
                    value: choice as string | number,
                    label: String(choice),
                  }))}
                  onChange={update}
                />
              ) : field.type === "boolean" ? (
                <Switch
                  aria-label={label}
                  checked={Boolean(values[field.name])}
                  onChange={update}
                />
              ) : field.type === "number" || field.type === "integer" ? (
                <InputNumber
                  aria-label={label}
                  className="w-full"
                  value={
                    typeof values[field.name] === "number"
                      ? (values[field.name] as number)
                      : null
                  }
                  precision={field.type === "integer" ? 0 : undefined}
                  onChange={update}
                />
              ) : field.type === "array" || field.type === "object" ? (
                <Input.TextArea
                  aria-label={label}
                  rows={3}
                  value={structuredValues[field.name] ?? ""}
                  placeholder={field.type === "array" ? "[]" : "{}"}
                  onChange={(event) =>
                    setStructuredValues((current) => ({
                      ...current,
                      [field.name]: event.target.value,
                    }))
                  }
                />
              ) : isSecretField(field) ? (
                <Input.Password
                  aria-label={label}
                  value={String(values[field.name] ?? "")}
                  onChange={(event) => update(event.target.value)}
                />
              ) : (
                <Input
                  aria-label={label}
                  value={String(values[field.name] ?? "")}
                  onChange={(event) => update(event.target.value)}
                />
              )}
            </div>
          );
        })}
        {error ? <Alert type="error" showIcon message={error} /> : null}
      </div>
    </Modal>
  );
};
