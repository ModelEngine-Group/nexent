// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { createContext, useContext } from "react";

export const RepositoryPresentationContext = createContext<{
  layout: "cards" | "list";
  resourceType?: string;
  query?: Pick<URLSearchParams, "get">;
  updateQuery?: (
    changes: Record<string, string | null>,
    replace?: boolean
  ) => void;
} | null>(null);

export const useRepositoryPresentation = () =>
  useContext(RepositoryPresentationContext);
