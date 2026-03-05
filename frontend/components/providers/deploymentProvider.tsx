"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
} from "react";
import { API_ENDPOINTS, fetchWithErrorHandling } from "@/services/api";
import { APP_VERSION } from "@/const/constants";
import log from "@/lib/logger";

interface DeploymentContextType {
  isSpeedMode: boolean;
  isDeploymentReady: boolean;
  appVersion: string;
  deploymentVersion: string;
}

const DeploymentContext = createContext<DeploymentContextType>({
  isSpeedMode: false,
  isDeploymentReady: false,
  appVersion: APP_VERSION,
  deploymentVersion: "",
});

interface DeploymentVersionResponse {
  deployment_version: string;
  app_version: string;
  status: string;
}

export function DeploymentProvider({ children }: { children: ReactNode }) {
  const [isSpeedMode, setIsSpeedMode] = useState(false);
  const [isDeploymentReady, setIsDeploymentReady] = useState(false);
  const [appVersion, setAppVersion] = useState(APP_VERSION);
  const [deploymentVersion, setDeploymentVersion] = useState("");

  useEffect(() => {
    const fetchDeploymentInfo = async () => {
      try {
        const response = await fetchWithErrorHandling(
          API_ENDPOINTS.tenantConfig.deploymentVersion
        );
        const data: DeploymentVersionResponse = await response.json();
        setDeploymentVersion(data.deployment_version);
        setIsSpeedMode(data.deployment_version === "speed");
        if (data.app_version) {
          setAppVersion(data.app_version);
        }
      } catch (error) {
        log.error("Failed to fetch deployment info:", error);
        setIsSpeedMode(false);
      } finally {
        setIsDeploymentReady(true);
      }
    };

    fetchDeploymentInfo();
  }, []);

  return (
    <DeploymentContext.Provider
      value={{ isSpeedMode, isDeploymentReady, appVersion, deploymentVersion }}
    >
      {children}
    </DeploymentContext.Provider>
  );
}

export const useDeployment = () => useContext(DeploymentContext);
