// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { forwardRef } from "react";
import { Search } from "lucide-react";
import {
  InputField,
  type InputFieldProps,
} from "@/components/common/InputField";
import { cn } from "@/lib/utils";

export type SearchInputProps = Omit<InputFieldProps, "prefix" | "type">;

/** Search presentation is shared; callers own filtering, requests and layout. */
export const SearchInput = forwardRef<HTMLInputElement, SearchInputProps>(
  function SearchInput({ allowClear = true, className, ...props }, ref) {
    return (
      <InputField
        {...props}
        ref={ref}
        type="text"
        allowClear={allowClear}
        prefix={
          <Search className="size-4 text-muted-foreground" aria-hidden="true" />
        }
        className={cn("h-8", className)}
      />
    );
  }
);
