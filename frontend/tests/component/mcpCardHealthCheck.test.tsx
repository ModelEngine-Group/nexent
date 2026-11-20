// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { expect, test, vi } from "vitest";
import MineMcpServiceCard from "@/app/resource-space/mcp/components/MineMcpServiceCard";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";
import {
  McpHealthStatus,
  McpServiceStatus,
  McpSource,
  McpTransportType,
} from "@/const/mcpTools";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/tag/ResourceTagChips", () => ({ default: () => null }));
vi.mock("@/app/resource-space/components/ResourceReviewCenter", () => ({
  ResourceReviewLink: () => null,
}));

function setup(
  layout: "cards" | "list",
  overrides: Partial<ComponentProps<typeof MineMcpServiceCard>> = {}
) {
  const props: ComponentProps<typeof MineMcpServiceCard> = {
    item: {
      kind: "local",
      service: {
        mcpId: 7,
        name: "Test MCP",
        description: "Description",
        source: McpSource.LOCAL,
        enabled: McpServiceStatus.DISABLED,
        updatedAt: "",
        createTime: "",
        tags: [],
        transportType: McpTransportType.HTTP,
        serverUrl: "",
        tools: [],
        healthStatus: McpHealthStatus.UNCHECKED,
        permission: "EDIT",
      },
    },
    onEditLocal: vi.fn(),
    onEditCommunity: vi.fn(),
    onToggle: vi.fn(),
    onSubmitVersionUpdate: vi.fn(),
    onUnpublishOnline: vi.fn(),
    onDelete: vi.fn(),
    onHealthCheck: vi.fn(),
    ...overrides,
  };
  render(
    <RepositoryPresentationContext.Provider
      value={{ layout, resourceType: "mcp" }}
    >
      <MineMcpServiceCard {...props} />
    </RepositoryPresentationContext.Provider>
  );
  return props;
}

test.each(["cards", "list"] as const)(
  "%s exposes health checking outside the more menu",
  async (layout) => {
    const props = setup(layout);
    const check = screen.getByRole("button", {
      name: "mcpConfig.serverList.button.healthCheck",
    });
    fireEvent.click(check);
    expect(props.onHealthCheck).toHaveBeenCalledWith(props.item);
    expect(props.onEditLocal).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "mcpTools.mine.moreActions" })
    );
    expect(await screen.findByRole("menu")).toBeTruthy();
    expect(
      screen.queryByRole("menuitem", {
        name: "mcpConfig.serverList.button.healthCheck",
      })
    ).toBeNull();
  }
);

test.each(["success", "failed"] as const)(
  "shows %s and allows another check",
  (connectionStatus) => {
    const props = setup("cards", { connectionStatus });
    const button = screen.getByRole("button", {
      name: "mcpConfig.serverList.button.healthCheck",
    });
    expect(button.textContent).toContain(
      `mcpTools.mine.connectionStatus.${connectionStatus}`
    );
    fireEvent.click(button);
    expect(props.onHealthCheck).toHaveBeenCalledOnce();
  }
);

test("blocks duplicate checks while a request is running", () => {
  const props = setup("cards", { healthChecking: true });
  const button = screen.getByRole("button", {
    name: "mcpConfig.serverList.button.healthCheck",
  });
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(props.onHealthCheck).not.toHaveBeenCalled();
});

test("does not add a check action without a callback", () => {
  setup("cards", { onHealthCheck: undefined });
  expect(
    screen.queryByRole("button", {
      name: "mcpConfig.serverList.button.healthCheck",
    })
  ).toBeNull();
});
