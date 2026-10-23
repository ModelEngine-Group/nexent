// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render as testingRender } from "@testing-library/react";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement, ReactNode } from "react";

export function createQueryWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

export function render(ui: ReactElement) {
  return testingRender(ui, { wrapper: createQueryWrapper() });
}

export async function changePageSize(size: number) {
  const user = userEvent.setup();
  const pagination = document.querySelector(
    '[data-picker-part="pagination"]'
  ) as HTMLElement;
  await user.click(within(pagination).getByRole("combobox"));
  await user.click(
    screen.getByText((text) => text.startsWith(`${size} `), {
      selector: ".ant-select-item-option-content",
    })
  );
}
