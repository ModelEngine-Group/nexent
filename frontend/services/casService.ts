import { API_ENDPOINTS } from "@/services/api";
import { buildHeartbeatAuthHeader } from "@/lib/casHeartbeat";
import log from "@/lib/logger";

export interface CasConfig {
  enabled: boolean;
  login_mode: "button" | "force" | "disabled";
  heartbeat_url: string;
  heartbeat_interval_seconds: number;
  heartbeat_cookie_name: string;
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
  heartbeat_url: "",
  heartbeat_interval_seconds: 300,
  heartbeat_cookie_name: "",
  renew_before_seconds: 300,
  renew_timeout_seconds: 10,
  display_name: "CAS",
};

const SUCCESS_CACHE_TTL_MS = 5 * 60 * 1000;
const FAILURE_CACHE_TTL_MS = 30 * 1000;

let cachedConfig: CasConfig | null = null;
let cacheExpiresAt = 0;
let inFlightConfigPromise: Promise<CasConfig> | null = null;
let inFlightHeartbeatPromise: Promise<boolean> | null = null;

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

  sendHeartbeat: (config: CasConfig): Promise<boolean> => {
    if (typeof window === "undefined" || !config.heartbeat_url.trim()) {
      return Promise.resolve(false);
    }
    if (inFlightHeartbeatPromise) return inFlightHeartbeatPromise;

    let heartbeatUrl: URL;
    try {
      heartbeatUrl = new URL(config.heartbeat_url, window.location.origin);
      if (!["http:", "https:"].includes(heartbeatUrl.protocol)) {
        log.warn("CAS heartbeat URL must use HTTP or HTTPS");
        return Promise.resolve(false);
      }
    } catch {
      log.warn("CAS heartbeat URL is invalid");
      return Promise.resolve(false);
    }

    const headers: Record<string, string> = {};
    const authHeader = buildHeartbeatAuthHeader(
      document.cookie,
      config.heartbeat_cookie_name
    );
    if (authHeader) headers["X-Auth-Token"] = authHeader;

    const controller = new AbortController();
    const timeoutId = window.setTimeout(
      () => controller.abort(),
      Math.max(1, config.renew_timeout_seconds) * 1_000
    );

    const heartbeatPromise = (async (): Promise<boolean> => {
      try {
        const response = await fetch(heartbeatUrl.toString(), {
          method: "GET",
          headers,
          credentials: "omit",
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) {
          log.warn(`CAS heartbeat failed with status ${response.status}`);
          return false;
        }
        log.info("CAS heartbeat succeeded");
        return true;
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          log.warn("CAS heartbeat timed out");
        } else {
          log.warn("CAS heartbeat request failed");
        }
        return false;
      } finally {
        window.clearTimeout(timeoutId);
      }
    })();

    inFlightHeartbeatPromise = heartbeatPromise;
    void heartbeatPromise.finally(() => {
      if (inFlightHeartbeatPromise === heartbeatPromise) {
        inFlightHeartbeatPromise = null;
      }
    });
    return heartbeatPromise;
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
