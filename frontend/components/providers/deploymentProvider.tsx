"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
} from "react";
import { API_ENDPOINTS } from "@/services/api";
import log from "@/lib/logger";

interface DeploymentContextType {
  isSpeedMode: boolean;
  isDeploymentReady: boolean;
}

const DeploymentContext = createContext<DeploymentContextType>({
  isSpeedMode: false,
  isDeploymentReady: false,
});

export function DeploymentProvider({ children }: { children: ReactNode }) {
  const [isSpeedMode, setIsSpeedMode] = useState(false);
  const [isDeploymentReady, setIsDeploymentReady] = useState(false);

  useEffect(() => {
    const checkDeploymentVersion = async () => {
      try {
        const response = await fetch(
          API_ENDPOINTS.tenantConfig.deploymentVersion
        );
        if (response.ok) {
          const data = await response.json();
          const version =
            data.content?.deployment_version || data.deployment_version;
          setIsSpeedMode(version === "speed");
        }
      } catch (error) {
        log.error("Failed to check deployment version:", error);
        setIsSpeedMode(false);
      } finally {
        setIsDeploymentReady(true);
      }
    };

    checkDeploymentVersion();
  }, []);

  return (
    <DeploymentContext.Provider value={{ isSpeedMode, isDeploymentReady }}>
      {children}
    </DeploymentContext.Provider>
  );
}

export const useDeployment = () => useContext(DeploymentContext);
