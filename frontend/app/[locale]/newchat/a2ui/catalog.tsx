"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { z } from "zod";
import { Catalog, CommonSchemas } from "@a2ui/web_core/v0_9";
import {
  basicCatalog,
  createComponentImplementation,
  type ReactComponentImplementation,
} from "@a2ui/react/v0_9";
import {
  stageA2UIFormSubmission,
  type A2UIFormValues,
  useA2UIFormSubmitted,
} from "./form-submission-store";

const DataTable = createComponentImplementation(
  {
    name: "DataTable",
    schema: z.object({
      columns: z.array(z.object({ key: z.string(), label: z.string() })),
      rows: z.array(z.record(z.unknown())),
      caption: z.string().optional(),
    }),
  },
  ({ props }) => (
    <div className="my-3 overflow-x-auto rounded-lg border">
      <table className="w-full text-left text-sm">
        {props.caption ? (
          <caption className="border-b px-3 py-2 text-left font-medium">
            {props.caption}
          </caption>
        ) : null}
        <thead className="bg-muted/50">
          <tr>
            {props.columns.map((column) => (
              <th key={column.key} className="px-3 py-2 font-medium">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {props.rows.slice(0, 500).map((row, rowIndex) => (
            <tr key={rowIndex} className="border-t">
              {props.columns.map((column) => (
                <td key={column.key} className="px-3 py-2">
                  {String(row[column.key] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
);

const CHART_COLORS = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed"];

const Chart = createComponentImplementation(
  {
    name: "Chart",
    schema: z.object({
      chartType: z.enum(["line", "bar", "pie"]),
      data: z.array(z.record(z.unknown())),
      xKey: z.string().optional(),
      valueKey: z.string(),
      title: z.string().optional(),
    }),
  },
  ({ props }) => {
    const data = props.data.slice(0, 1000);
    const xKey = props.xKey ?? "name";
    return (
      <div className="my-3 rounded-lg border p-3">
        {props.title ? (
          <div className="mb-2 text-sm font-medium">{props.title}</div>
        ) : null}
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            {props.chartType === "line" ? (
              <LineChart data={data}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey={xKey} />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line
                  type="monotone"
                  dataKey={props.valueKey}
                  stroke={CHART_COLORS[0]}
                />
              </LineChart>
            ) : props.chartType === "bar" ? (
              <BarChart data={data}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey={xKey} />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey={props.valueKey} fill={CHART_COLORS[0]} />
              </BarChart>
            ) : (
              <PieChart>
                <Tooltip />
                <Legend />
                <Pie
                  data={data}
                  dataKey={props.valueKey}
                  nameKey={xKey}
                  outerRadius={96}
                >
                  {data.map((_, index) => (
                    <Cell
                      key={index}
                      fill={CHART_COLORS[index % CHART_COLORS.length]}
                    />
                  ))}
                </Pie>
              </PieChart>
            )}
          </ResponsiveContainer>
        </div>
      </div>
    );
  }
);

const formFieldSchema = z.object({
  name: z.string(),
  label: z.string(),
  type: z.enum(["text", "textarea", "number", "select", "checkbox", "date"]),
  required: z.boolean().optional(),
  options: z
    .array(z.object({ label: z.string(), value: z.string() }))
    .optional(),
});

const FormComponent = createComponentImplementation(
  {
    name: "Form",
    schema: z.object({
      title: z.string().optional(),
      fields: z.array(formFieldSchema),
      submitLabel: z.string().optional(),
      action: CommonSchemas.Action,
    }),
  },
  ({ props, context }) => {
    const [submitError, setSubmitError] = useState<string>();
    const surfaceId = context.dataContext.surface.id;
    const componentId = context.componentModel.id;
    const submitted = useA2UIFormSubmitted(surfaceId, componentId);
    const { register, handleSubmit, formState } =
      useForm<Record<string, unknown>>();
    const onSubmit = handleSubmit(async (values) => {
      if (submitted) return;
      const normalizedValues = Object.fromEntries(
        props.fields.map((field) => {
          const value = values[field.name];
          if (field.type === "checkbox") {
            return [field.name, value === true];
          }
          if (field.type === "number") {
            return [
              field.name,
              typeof value === "number" && Number.isFinite(value)
                ? value
                : null,
            ];
          }
          return [field.name, value === "" || value == null ? null : value];
        })
      ) as A2UIFormValues;
      for (const [name, value] of Object.entries(normalizedValues)) {
        context.dataContext.set(`/form/${name}`, value);
      }
      setSubmitError(undefined);
      let clearStagedSubmission: (() => void) | undefined;
      try {
        clearStagedSubmission = stageA2UIFormSubmission(
          surfaceId,
          componentId,
          normalizedValues
        );
        await props.action();
      } catch {
        setSubmitError("表单数据无法提交");
      } finally {
        clearStagedSubmission?.();
      }
    });
    return (
      <form
        onSubmit={onSubmit}
        className="my-3 space-y-3 rounded-lg border p-4"
      >
        {props.title ? <h3 className="font-medium">{props.title}</h3> : null}
        {props.fields.map((field) => (
          <label key={field.name} className="block space-y-1 text-sm">
            <span>{field.label}</span>
            {field.type === "textarea" ? (
              <textarea
                disabled={submitted}
                className="w-full rounded-md border bg-background p-2"
                {...register(field.name, { required: field.required })}
              />
            ) : field.type === "select" ? (
              <select
                disabled={submitted}
                className="w-full rounded-md border bg-background p-2"
                {...register(field.name, { required: field.required })}
              >
                {(field.options ?? []).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            ) : field.type === "checkbox" ? (
              <input
                type="checkbox"
                disabled={submitted}
                {...register(field.name)}
              />
            ) : (
              <input
                type={field.type}
                disabled={submitted}
                className="w-full rounded-md border bg-background p-2"
                {...register(field.name, {
                  required: field.required,
                  setValueAs:
                    field.type === "number"
                      ? (value) => (value === "" ? null : Number(value))
                      : undefined,
                })}
              />
            )}
          </label>
        ))}
        <button
          type="submit"
          disabled={submitted || formState.isSubmitting}
          className="rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50"
        >
          {submitted
            ? typeof document !== "undefined" &&
              document.documentElement.lang.toLowerCase().startsWith("zh")
              ? "已提交"
              : "Submitted"
            : (props.submitLabel ?? "Submit")}
        </button>
        {submitError ? (
          <p role="alert" className="text-sm text-destructive">
            {submitError}
          </p>
        ) : null}
      </form>
    );
  }
);

const ApprovalCard = createComponentImplementation(
  {
    name: "ApprovalCard",
    schema: z.object({
      title: z.string(),
      description: z.string().optional(),
      approveLabel: z.string().optional(),
      rejectLabel: z.string().optional(),
      approveAction: CommonSchemas.Action,
      rejectAction: CommonSchemas.Action,
    }),
  },
  ({ props }) => (
    <div className="my-3 rounded-lg border p-4">
      <h3 className="font-medium">{props.title}</h3>
      {props.description ? (
        <p className="mt-1 text-sm text-muted-foreground">
          {props.description}
        </p>
      ) : null}
      <div className="mt-3 flex gap-2">
        <button
          onClick={props.approveAction}
          className="rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground"
        >
          {props.approveLabel ?? "Approve"}
        </button>
        <button
          onClick={props.rejectAction}
          className="rounded-md border px-3 py-2 text-sm"
        >
          {props.rejectLabel ?? "Reject"}
        </button>
      </div>
    </div>
  )
);

const ArtifactCard = createComponentImplementation(
  {
    name: "ArtifactCard",
    schema: z.object({
      title: z.string(),
      description: z.string().optional(),
      url: z.string().url(),
    }),
  },
  ({ props }) => (
    <div className="my-3 rounded-lg border p-4">
      <div className="font-medium">{props.title}</div>
      {props.description ? (
        <p className="mt-1 text-sm text-muted-foreground">
          {props.description}
        </p>
      ) : null}
      <a
        href={props.url}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-3 inline-block text-sm text-primary underline"
      >
        Open artifact
      </a>
    </div>
  )
);

export const nexentCatalog = new Catalog<ReactComponentImplementation>(
  "nexent.v1",
  [
    ...Array.from(basicCatalog.components.values()).filter((component) =>
      [
        "Text",
        "Image",
        "Icon",
        "Button",
        "Card",
        "Row",
        "Column",
        "Divider",
      ].includes(component.name)
    ),
    DataTable,
    Chart,
    FormComponent,
    ApprovalCard,
    ArtifactCard,
  ],
  Array.from(basicCatalog.functions.values())
);
