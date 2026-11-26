// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  type ReactNode,
} from "react";
import { API_ENDPOINTS, fetchWithErrorHandling } from "@/services/api";
import { APP_VERSION } from "@/const/constants";
import log from "@/lib/logger";
import { useAuthenticationContext } from "./AuthenticationProvider";

interface DeploymentContextType {
  agentCore: "smolagents" | "jiuwen";
  isSpeedMode: boolean;
  isDeploymentReady: boolean;
  appVersion: string;
  deploymentVersion: string;
  enableAidpKnowledge: boolean;
  enableAgentWorkbench: boolean;
  hideHomePage: boolean;
  aidpEnabled: boolean;
}

const DeploymentContext = createContext<DeploymentContextType>({
  agentCore: "smolagents",
  isSpeedMode: false,
  isDeploymentReady: false,
  appVersion: APP_VERSION,
  deploymentVersion: "",
  enableAidpKnowledge: false,
  enableAgentWorkbench: false,
  hideHomePage: false,
  aidpEnabled: false,
});

interface DeploymentVersionResponse {
  agent_core?: "smolagents" | "jiuwen";
  deployment_version: string;
  app_version: string;
  enable_aidp_knowledge?: boolean;
  enable_agent_workbench?: boolean;
  hide_home_page?: boolean;
  status: string;
}

export function DeploymentProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, isAuthChecking } = useAuthenticationContext();
  const [deployment, setDeployment] =
    useState<DeploymentVersionResponse | null>();

  if (!isAuthenticated && deployment !== undefined) {
    setDeployment(undefined);
  }

  useEffect(() => {
    if (isAuthChecking || !isAuthenticated) return;

    const controller = new AbortController();
    const fetchDeploymentInfo = async () => {
      try {
        const response = await fetchWithErrorHandling(
          API_ENDPOINTS.tenantConfig.deploymentVersion,
          { signal: controller.signal }
        );
        const data: DeploymentVersionResponse = await response.json();
        if (!controller.signal.aborted) {
          setDeployment(data);
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          log.error("Failed to fetch deployment info:", error);
          setDeployment(null);
        }
      }
    };

    void fetchDeploymentInfo();
    return () => controller.abort();
  }, [isAuthChecking, isAuthenticated]);

  const isDeploymentReady =
    !isAuthChecking && (!isAuthenticated || deployment !== undefined);
  const enableAidpKnowledge = deployment?.enable_aidp_knowledge ?? false;

  return (
    <DeploymentContext.Provider
      value={{
        agentCore: deployment?.agent_core ?? "smolagents",
        isSpeedMode: false,
        isDeploymentReady,
        appVersion: deployment?.app_version || APP_VERSION,
        deploymentVersion: deployment?.deployment_version ?? "",
        enableAidpKnowledge,
        enableAgentWorkbench: deployment?.enable_agent_workbench ?? false,
        hideHomePage: deployment?.hide_home_page ?? false,
        aidpEnabled: enableAidpKnowledge,
      }}
    >
      {children}
    </DeploymentContext.Provider>
  );
}

export const useDeployment = () => useContext(DeploymentContext);
