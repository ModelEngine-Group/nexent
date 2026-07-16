"use client";

import React from "react";
import { Alert, Input, InputNumber, Select } from "antd";

import type { WebMcpInstallOption } from "./webMcpTypes";

interface WebMcpInstallConfigurationProps {
  options: WebMcpInstallOption[];
  optionId: string;
  selectedOption?: WebMcpInstallOption;
  fieldValues: Record<string, string>;
  installError?: string;
  onOptionChange: (optionId: string) => void;
  onFieldChange: (key: string, value: string) => void;
}

/** Presentational configuration form for one trusted MCP install option. */
export const WebMcpInstallConfiguration: React.FC<
  WebMcpInstallConfigurationProps
> = ({
  options,
  optionId,
  selectedOption,
  fieldValues,
  installError,
  onOptionChange,
  onFieldChange,
}) => (
  <div className="mt-3 space-y-2 border-t border-sky-100 pt-2">
    {options.length > 1 && (
      <Select
        className="w-full"
        value={optionId}
        onChange={onOptionChange}
        options={options.map((option) => ({
          value: option.option_id,
          label: option.label || `${option.type} ${option.transport ?? ""}`,
          disabled: option.supported === false,
        }))}
      />
    )}
    {selectedOption?.supported === false ? (
      <Alert
        type="warning"
        showIcon
        message={selectedOption.unsupported_reason || "Unsupported option"}
      />
    ) : null}
    {selectedOption?.description ? (
      <div className="text-xs text-gray-500">{selectedOption.description}</div>
    ) : null}
    {(selectedOption?.fields ?? []).map((field) => {
      const label = `${field.label || field.name}${field.required ? " *" : ""}`;
      const update = (value: string) => onFieldChange(field.key, value);
      return (
        <div key={field.key}>
          <div className="mb-1 text-xs font-medium text-gray-600">{label}</div>
          {field.description ? (
            <div className="mb-1 text-[11px] text-gray-400">
              {field.description}
            </div>
          ) : null}
          {field.secret ? (
            <Input.Password
              placeholder={field.placeholder || label}
              value={fieldValues[field.key] ?? ""}
              onChange={(event) => update(event.target.value)}
            />
          ) : field.choices?.length ? (
            <Select
              className="w-full"
              value={fieldValues[field.key]}
              onChange={update}
              options={field.choices.map((choice) => ({
                value: choice,
                label: choice,
              }))}
            />
          ) : field.type === "json" ? (
            <Input.TextArea
              rows={4}
              placeholder={field.placeholder || label}
              value={fieldValues[field.key] ?? ""}
              onChange={(event) => update(event.target.value)}
            />
          ) : field.type === "number" ? (
            <InputNumber
              className="w-full"
              placeholder={field.placeholder || label}
              value={
                fieldValues[field.key] ? Number(fieldValues[field.key]) : null
              }
              onChange={(value) => update(value == null ? "" : String(value))}
            />
          ) : (
            <Input
              type={field.type === "url" ? "url" : "text"}
              placeholder={field.placeholder || label}
              value={fieldValues[field.key] ?? ""}
              onChange={(event) => update(event.target.value)}
            />
          )}
        </div>
      );
    })}
    {installError ? (
      <Alert
        type="error"
        showIcon
        message="Installation failed"
        description={installError}
      />
    ) : null}
  </div>
);
