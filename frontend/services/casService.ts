import { API_ENDPOINTS } from "@/services/api";
import log from "@/lib/logger";

export interface CasConfig {
  enabled: boolean;
  login_mode: "button" | "force" | "disabled";
  renew_before_seconds: number;
  renew_timeout_seconds: number;
  display_name: string;
}

interface GetCasConfigOptions {
  forceRefresh?: boolean;
}

const disabledConfig: CasConfig = {
  enabled: false,
  login_mode: "disabled",
  renew_before_seconds: 300,
  renew_timeout_seconds: 10,
  display_name: "CAS",
};

const SUCCESS_CACHE_TTL_MS = 5 * 60 * 1000;
const FAILURE_CACHE_TTL_MS = 30 * 1000;

let cachedConfig: CasConfig | null = null;
let cacheExpiresAt = 0;
let inFlightConfigPromise: Promise<CasConfig> | null = null;

const cacheConfig = (config: CasConfig, ttlMs: number) => {
  cachedConfig = config;
  cacheExpiresAt = Date.now() + ttlMs;
};

export const casService = {
  getConfig: async (options: GetCasConfigOptions = {}): Promise<CasConfig> => {
    const now = Date.now();
    if (!options.forceRefresh && cachedConfig && cacheExpiresAt > now) {
      return cachedConfig;
    }

    if (inFlightConfigPromise) {
      return inFlightConfigPromise;
    }

    inFlightConfigPromise = (async () => {
      try {
        const response = await fetch(API_ENDPOINTS.cas.config);
        if (!response.ok) {
          cacheConfig(disabledConfig, FAILURE_CACHE_TTL_MS);
          return disabledConfig;
        }

        const data = await response.json();
        const config = { ...disabledConfig, ...(data.data || {}) };
        cacheConfig(config, SUCCESS_CACHE_TTL_MS);
        return config;
      } catch (error) {
        log.warn("Failed to fetch CAS config:", error);
        cacheConfig(disabledConfig, FAILURE_CACHE_TTL_MS);
        return disabledConfig;
      } finally {
        inFlightConfigPromise = null;
      }
    })();

    return inFlightConfigPromise;
  },

  startLogin: (redirect?: string): void => {
    const target =
      redirect || window.location.pathname + window.location.search;
    window.location.href = `${API_ENDPOINTS.cas.login}?redirect=${encodeURIComponent(target)}`;
  },

  renewInIframe: (timeoutSeconds: number): Promise<boolean> => {
    if (typeof window === "undefined") return Promise.resolve(false);

    return new Promise((resolve) => {
      const iframe = document.createElement("iframe");
      iframe.src = API_ENDPOINTS.cas.renew;
      iframe.style.display = "none";
      iframe.setAttribute("aria-hidden", "true");

      let settled = false;
      const cleanup = () => {
        window.removeEventListener("message", onMessage);
        iframe.remove();
      };
      const finish = (ok: boolean) => {
        if (settled) return;
        settled = true;
        cleanup();
        resolve(ok);
      };
      const onMessage = (event: MessageEvent) => {
        if (event.origin !== window.location.origin) return;
        if (event.data?.type === "cas-renew-success") finish(true);
        if (event.data?.type === "cas-renew-failed") finish(false);
      };

      window.addEventListener("message", onMessage);
      document.body.appendChild(iframe);
      window.setTimeout(
        () => finish(false),
        Math.max(1, timeoutSeconds) * 1000
      );
    });
  },
};
