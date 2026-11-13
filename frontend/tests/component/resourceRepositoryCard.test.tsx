// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ResourceCard from "@/components/resource/ResourceCard";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";

describe("repository card presentation compatibility", () => {
  it("keeps agent list actions in template-then-management order", () => {
    render(
      <RepositoryPresentationContext.Provider
        value={{ layout: "list", resourceType: "agent" }}
      >
        <ResourceCard
          title="Agent"
          actionsOnly
          footer={<button>Create from template</button>}
          headerActions={<button>Take down</button>}
        />
      </RepositoryPresentationContext.Provider>
    );
    expect(
      screen.getAllByRole("button").map((button) => button.textContent)
    ).toEqual(["Create from template", "Take down"]);
    expect(screen.queryByRole("heading", { name: "Agent" })).toBeNull();
  });
  it("keeps legacy footer placement outside the new repository", () => {
    render(<ResourceCard title="Legacy" footer={<button>Install</button>} />);
    expect(
      screen.getByRole("button", { name: "Install" }).parentElement?.className
    ).toContain("mt-4");
  });
  it("places a single install action in the compact card header", () => {
    render(
      <RepositoryPresentationContext.Provider value={{ layout: "cards" }}>
        <ResourceCard
          title="Resource"
          description="Description"
          footer={<button>Install</button>}
        />
      </RepositoryPresentationContext.Provider>
    );
    const button = screen.getByRole("button", { name: "Install" });
    expect(screen.getAllByRole("button", { name: "Install" })).toHaveLength(1);
    expect(button.parentElement?.textContent).toContain("Install");
    expect(button.parentElement?.parentElement?.textContent).toContain(
      "Resource"
    );
    expect(button.parentElement?.parentElement?.textContent).not.toContain(
      "Description"
    );
  });
});
