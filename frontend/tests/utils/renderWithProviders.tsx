// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions, type RenderResult } from "@testing-library/react";

/**
 * Shared render helper for component tests.
 *
 * Several Nexus components consume TanStack Query hooks (directly or through
 * custom hooks such as `useAccountMonitoring`). Rendering them without a
 * `QueryClientProvider` throws:
 *
 *   "No QueryClient set, use QueryClientProvider to set one"
 *
 * Always use this helper instead of the bare `render()` from
 * `@testing-library/react` when the component under test (or anything it
 * mounts) may use react-query. Retries are disabled so a failing query
 * surfaces immediately instead of stalling the test.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

export function renderWithProviders(
  ui: React.ReactElement,
  options: Omit<RenderOptions, "wrapper"> & { queryClient?: QueryClient } = {}
): RenderResult & { queryClient: QueryClient } {
  const { queryClient, ...renderOptions } = options;
  const client = queryClient ?? createTestQueryClient();
  const result = render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
    renderOptions
  );
  return { ...result, queryClient: client };
}
