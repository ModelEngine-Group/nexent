// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Input } from "antd";
import { Search } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

export default function RepositorySearchBar({
  value,
  placeholder,
  onChange,
  filter,
  children,
  repository = true,
  legacyInputClassName = "rounded-xl",
}: {
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
  filter?: ReactNode;
  children?: ReactNode;
  repository?: boolean;
  legacyInputClassName?: string;
}) {
  const composing = useRef(false);
  const [draft, setDraft] = useState<string | null>(null);
  const input = (
    <Input
      value={draft ?? value}
      placeholder={placeholder}
      allowClear
      prefix={<Search className="size-4 text-muted-foreground" aria-hidden />}
      className={
        repository
          ? "h-8 w-full min-w-0 gap-1 rounded px-3 text-body-2"
          : legacyInputClassName
      }
      onCompositionStart={(event) => {
        composing.current = true;
        setDraft(event.currentTarget.value);
      }}
      onCompositionEnd={(event) => {
        composing.current = false;
        onChange(event.currentTarget.value);
        setDraft(null);
      }}
      onChange={(event) => {
        if (composing.current) setDraft(event.target.value);
        else onChange(event.target.value);
      }}
    />
  );

  return repository ? (
    <div className="flex shrink-0 flex-wrap items-center gap-2">
      <div className="flex w-full min-w-0 max-w-[1104px] flex-col items-stretch gap-2 sm:flex-row sm:items-center">
        <div className="w-full min-w-0 max-w-[800px] sm:flex-1">{input}</div>
        {filter && (
          <div className="w-full min-w-0 [&>*]:w-full sm:w-[27%] sm:max-w-[296px]">
            {filter}
          </div>
        )}
      </div>
      {children}
    </div>
  ) : (
    <div className="flex items-center gap-3">
      <div className="min-w-0 flex-1">{input}</div>
      {filter}
      {children}
    </div>
  );
}
