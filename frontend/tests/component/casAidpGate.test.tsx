// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import KnowledgesContent from "../../app/[locale]/knowledges/page";
const deployment = vi.hoisted(() => ({
  enableAidpKnowledge: false,
  isDeploymentReady: true,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({}) }));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => deployment,
}));
vi.mock("@/hooks/useSetupFlow", () => ({ useSetupFlow: () => ({}) }));
vi.mock("@/app/[locale]/knowledges/KnowledgeBaseConfiguration", () => ({
  default: () => <div>Local KB</div>,
}));
vi.mock("@/ext_components/aidp/AidpKnowledgeConfiguration", () => ({
  default: () => <div>AIDP KB</div>,
}));
describe("knowledge entry retains its existing AIDP gate", () => {
  it.each([false, true])(
    "selects the configured branch when enabled=%s",
    (enabled) => {
      deployment.enableAidpKnowledge = enabled;
      deployment.isDeploymentReady = true;
      render(<KnowledgesContent />);
      expect(
        screen.getByText(enabled ? "AIDP KB" : "Local KB")
      ).toBeInTheDocument();
      expect(
        screen.queryByText(enabled ? "Local KB" : "AIDP KB")
      ).not.toBeInTheDocument();
    }
  );
  it("waits for deployment configuration", () => {
    deployment.isDeploymentReady = false;
    render(<KnowledgesContent />);
    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(screen.queryByText("AIDP KB")).not.toBeInTheDocument();
  });
});
