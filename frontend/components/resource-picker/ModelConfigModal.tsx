"use client";

import { useState } from "react";

import {
  ParamDialog,
  ParamField,
  ParamInput,
  ParamLabel,
  ParamSlider,
  ParamSwitch,
} from "./ParamDialog";

const NUMBER_FIELDS = [
  { key: "contextWindow", label: "上下文窗口(Token)", value: "320,000" },
  { key: "maxRelated", label: "最大相关数(Token)", value: "100,000" },
  { key: "maxRelevance", label: "最高相关性(Token)", value: "10,000" },
  { key: "outputLimit", label: "输出限制(Token)", value: "2000" },
];

export interface ModelConfigModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm?: (values: Record<string, string>) => void;
}

export function ModelConfigModal({
  open,
  onClose,
  onConfirm,
}: ModelConfigModalProps) {
  const [deepThink, setDeepThink] = useState(true);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(NUMBER_FIELDS.map((f) => [f.key, f.value]))
  );
  const [perPage, setPerPage] = useState(35);
  const [topP, setTopP] = useState(65);

  const setValue = (key: string, value: string) =>
    setValues((prev) => ({ ...prev, [key]: value }));

  return (
    <ParamDialog
      open={open}
      title="模型配置参数"
      onClose={onClose}
      onConfirm={() => onConfirm?.(values)}
    >
      <div className="flex items-center gap-3">
        <ParamLabel label="深度思考" info />
        <ParamSwitch checked={deepThink} onChange={setDeepThink} />
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        {NUMBER_FIELDS.map((field) => (
          <ParamField key={field.key} label={field.label} info>
            <ParamInput
              inputSize="sm"
              value={values[field.key]}
              onChange={(e) => setValue(field.key, e.target.value)}
            />
          </ParamField>
        ))}
      </div>

      <ParamField label="每页内容数量" info>
        <ParamSlider value={perPage} minLabel="0" maxLabel="2.0" onChange={setPerPage} />
      </ParamField>

      <ParamField label="Top P" info>
        <ParamSlider value={topP} minLabel="2.0" maxLabel="0.0" onChange={setTopP} />
      </ParamField>
    </ParamDialog>
  );
}