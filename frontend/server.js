const { createServer } = require("http");
const http = require("http");
const https = require("https");
const { parse } = require("url");
const next = require("next");
const { createProxyServer } = require("http-proxy");
const cookie = require("cookie");
const path = require("path");
const fs = require("fs");
const multiparty = require("multiparty");

// Load environment variables from deploy/env/.env
// In container environments, env vars are injected directly by Docker, so .env file may not exist
// Using optional: true to avoid errors if .env file is not found
require("dotenv").config({
  path: path.resolve(__dirname, "../deploy/env/.env"),
  override: false, // Don't override existing environment variables (important for Docker)
});

const dev = process.env.NODE_ENV !== "production";
const app = next({
  dev,
});
const handle = app.getRequestHandler();

// Backend addresses
const HTTP_BACKEND = process.env.HTTP_BACKEND || "http://localhost:5010"; // config
const WS_BACKEND = process.env.WS_BACKEND || "ws://localhost:5014"; // runtime
const RUNTIME_HTTP_BACKEND =
  process.env.RUNTIME_HTTP_BACKEND || "http://localhost:5014"; // runtime
const MINIO_BACKEND = process.env.MINIO_ENDPOINT || "http://localhost:9010";
const MARKET_BACKEND =
  process.env.MARKET_BACKEND || "http://60.204.251.153:8010"; // market
const SHARE_BASE_URL =
  process.env.SHARE_BASE_URL || process.env.NEXT_PUBLIC_SHARE_BASE_URL || "";

const ICON_UPLOAD_DIR = path.resolve(__dirname, "./public/");
const LOCALES_CONFIG_DIR = path.resolve(__dirname, "./public/locales");
const PORT = 3000;

function parseTimeout(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

const PROXY_TIMEOUT_MS = parseTimeout(process.env.PROXY_TIMEOUT_MS, 10 * 60 * 1000);
const PROXY_WS_TIMEOUT_MS = parseTimeout(
  process.env.PROXY_WS_TIMEOUT_MS,
  PROXY_TIMEOUT_MS
);
const SSE_PROXY_TIMEOUT_MS = parseTimeout(
  process.env.SSE_PROXY_TIMEOUT_MS,
  PROXY_TIMEOUT_MS
);

const proxy = createProxyServer({
  proxyTimeout: PROXY_TIMEOUT_MS,
  timeout: PROXY_TIMEOUT_MS,
});

// ============================================================================
// Cookie configuration
// ============================================================================
const COOKIE_NAMES = {
  ACCESS_TOKEN: "nexent_access_token",
  REFRESH_TOKEN: "nexent_refresh_token",
  EXPIRES_AT: "nexent_token_expires_at",
  OAUTH_PENDING: "nexent_oauth_pending",
};

const isProduction = process.env.NODE_ENV === "production";

function buildCookieOptions(httpOnly) {
  return {
    httpOnly,
    secure: false, // cookie can be send through http
    sameSite: "lax",
    path: "/",
  };
}

function appendSetCookies(res, cookies) {
  const existing = res.getHeader("Set-Cookie") || [];
  const existingCookies = Array.isArray(existing) ? existing : [existing];
  res.setHeader("Set-Cookie", [...existingCookies, ...cookies].filter(Boolean));
}

function setAuthCookies(res, session) {
  const cookies = [];

  const expiresInSeconds = session.expires_in_seconds || 3600;

  const refreshTokenMaxAge = expiresInSeconds * 10;

  if (session.access_token) {
    cookies.push(
      cookie.serialize(COOKIE_NAMES.ACCESS_TOKEN, session.access_token, {
        ...buildCookieOptions(true),
        maxAge: expiresInSeconds, // Use backend-provided value
      })
    );
  }

  if (session.refresh_token) {
    cookies.push(
      cookie.serialize(COOKIE_NAMES.REFRESH_TOKEN, session.refresh_token, {
        ...buildCookieOptions(true),
        maxAge: refreshTokenMaxAge, // 10x access token lifetime
      })
    );
  }

  if (session.expires_at) {
    cookies.push(
      cookie.serialize(COOKIE_NAMES.EXPIRES_AT, String(session.expires_at), {
        ...buildCookieOptions(false), // readable by frontend JS
        maxAge: expiresInSeconds, // Same as access token
      })
    );
  }

  if (cookies.length > 0) {
    appendSetCookies(res, cookies);
  }
}

function clearAuthCookies(res) {
  const expired = { maxAge: 0, path: "/" };
  res.setHeader("Set-Cookie", [
    cookie.serialize(COOKIE_NAMES.ACCESS_TOKEN, "", {
      ...expired,
      httpOnly: true,
    }),
    cookie.serialize(COOKIE_NAMES.REFRESH_TOKEN, "", {
      ...expired,
      httpOnly: true,
    }),
    cookie.serialize(COOKIE_NAMES.EXPIRES_AT, "", expired),
    cookie.serialize(COOKIE_NAMES.OAUTH_PENDING, "", {
      ...expired,
      httpOnly: true,
    }),
  ]);
}

function setPendingOAuthCookie(res, pendingToken) {
  appendSetCookies(res, [
    cookie.serialize(COOKIE_NAMES.OAUTH_PENDING, pendingToken, {
      ...buildCookieOptions(true),
      maxAge: 10 * 60,
    }),
  ]);
}

function clearPendingOAuthCookie(res) {
  appendSetCookies(res, [
    cookie.serialize(COOKIE_NAMES.OAUTH_PENDING, "", {
      maxAge: 0,
      path: "/",
      httpOnly: true,
    }),
  ]);
}

function getPreferredLocale(cookies) {
  const locale = cookies.NEXT_LOCALE;
  return locale === "en" || locale === "zh" ? locale : "zh";
}

function parseCookies(req) {
  return cookie.parse(req.headers.cookie || "");
}

function decodeJwtPayload(token) {
  try {
    const parts = token.split('.');
    if (parts.length !==3 ) return null;
      const payload = parts[1];
      const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
      const decoded = Buffer.from(padded, "base64").toString("utf-8");
      return JSON.parse(decoded)
  } catch (error) {
    console.error("decodeJwtPayload error:", err.message);
    return null;
  }
}

function isSuperAdminRequest(req) {
  const cookies = parseCookies(req);
  const token = cookies[COOKIE_NAMES.ACCESS_TOKEN];
  if (!token) {
    return false;
  }
  const payload = decodeJwtPayload(token);
  if (!payload) {
    return false;
  }
  return payload.role === 'authenticated' && payload.email === 'suadmin@nexent.com';
}

function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function renameFile(oldPath, newFileName) {
  ensureDir(ICON_UPLOAD_DIR);
  fs.renameSync(oldPath, path.join(ICON_UPLOAD_DIR, newFileName));
}

function readLocaleConfig(lang) {
  try {
    const fileName = 'custom.json';
    const filepath = path.join(LOCALES_CONFIG_DIR, lang === 'zh' ? 'zh' : 'en', fileName);
    if (!fs.existsSync(filepath)) {
      return {};
    }
    const data = JSON.parse(fs.readFileSync(filepath, "utf-8"))
    return data;
  } catch (error) {
    console.log(error.message)
  }
}

function saveLocaleConfig(fileData, lang) {
  ensureDir(LOCALES_CONFIG_DIR);
  const fileName = 'custom.json';
  const filepath = path.join(LOCALES_CONFIG_DIR, lang, fileName);
  fs.writeFileSync(filepath, fileData, "utf-8");
  return fileName;
}

function updateLocalConfig(oldData, newData) {
  if (!oldData || !newData) {
    return oldData;
  }
  return Object.keys(oldData).reduce((acc, key) => {
    acc[key] = newData[key] ? newData[key] : oldData[key]
    return acc;
  }, {});
}

// ============================================================================
// Auth endpoint interception — manually forward and intercept tokens
// ============================================================================
const AUTH_INTERCEPT_ENDPOINTS = new Set([
  "/api/user/signin",
  "/api/user/signup",
  "/api/user/refresh_token",
  "/api/user/logout",
  "/api/user/revoke",
  "/api/user/oauth/callback",
  "/api/user/oauth/link",
  "/api/user/oauth/pending",
  "/api/user/oauth/complete",
  "/api/user/cas/config",
  "/api/user/cas/login",
  "/api/user/cas/callback",
  "/api/user/cas/renew",
  "/api/user/cas/renew_callback",
  "/api/user/cas/logout_callback",
]);

function collectRequestBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

/**
 * For the refresh_token endpoint, inject the refresh_token from cookie
 * into the request body so the backend can process it normally.
 * If no refresh_token cookie exists, return 401 immediately.
 */
function prepareAuthRequestBody(pathname, body, cookies, res) {
  if (
    pathname === "/api/user/refresh_token" ) {
    const refreshToken =
    cookies[COOKIE_NAMES.REFRESH_TOKEN]
  ;
    if (!refreshToken) {
      res.writeHead(401, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ detail: "No refresh token cookie found" }));
      return null;
    }
    try {
      const parsed = body.length > 0 ? JSON.parse(body.toString()) : {};
      parsed.refresh_token = refreshToken;
      return Buffer.from(JSON.stringify(parsed));
    } catch {
      return body;
    }
  }
  return body;
}

function forwardAuthRequest(req, res, targetUrl) {
  const parsedTarget = new URL(targetUrl);
  const transport = parsedTarget.protocol === "https:" ? https : http;
  const cookies = parseCookies(req);

  if (
    req.parsedPathname === "/api/user/refresh_token" &&
    !cookies[COOKIE_NAMES.REFRESH_TOKEN]
  ) {
    res.writeHead(204);
    res.end();
    return;
  }

  collectRequestBody(req)
    .then((rawBody) => {
      const body = prepareAuthRequestBody(req.parsedPathname, rawBody, cookies, res);

    // If body is null, prepareAuthRequestBody already sent the error response
    if (body === null) {
      return;
    }

      const forwardHeaders = { ...req.headers, host: parsedTarget.host };

      // Inject access_token from cookie as Authorization header for the backend
      if (
        cookies[COOKIE_NAMES.ACCESS_TOKEN] &&
        !forwardHeaders["authorization"]
      ) {
        forwardHeaders["authorization"] =
          `Bearer ${cookies[COOKIE_NAMES.ACCESS_TOKEN]}`;
      }

      if (
        cookies[COOKIE_NAMES.OAUTH_PENDING] &&
        (req.parsedPathname === "/api/user/oauth/pending" ||
          req.parsedPathname === "/api/user/oauth/complete")
      ) {
        forwardHeaders["x-oauth-pending-token"] =
          cookies[COOKIE_NAMES.OAUTH_PENDING];
      }

      // Update content-length if body was modified
      if (body.length !== rawBody.length) {
        forwardHeaders["content-length"] = String(body.length);
      }

      const options = {
        hostname: parsedTarget.hostname,
        port: parsedTarget.port,
        path: req.url,
        method: req.method,
        headers: forwardHeaders,
      };

      const proxyReq = transport.request(options, (proxyRes) => {
        const responseChunks = [];
        proxyRes.on("data", (chunk) => responseChunks.push(chunk));
        proxyRes.on("end", () => {
          const responseBody = Buffer.concat(responseChunks);
          let finalBody = responseBody;

          try {
            const contentType = proxyRes.headers["content-type"] || "";
            if (
              contentType.includes("application/json") &&
              responseBody.length > 0
            ) {
              const data = JSON.parse(responseBody.toString());

              const isLogout = req.parsedPathname === "/api/user/logout";
              const isRevoke = req.parsedPathname === "/api/user/revoke";

              if (isLogout || isRevoke) {
                clearAuthCookies(res);
              } else if (
                req.parsedPathname === "/api/user/oauth/callback" &&
                data.data &&
                data.data.requires_account_completion &&
                data.data.pending_token
              ) {
                setPendingOAuthCookie(res, data.data.pending_token);
                const locale = getPreferredLocale(cookies);
                res.writeHead(302, { Location: `/${locale}/oauth/complete` });
                res.end();
                return;
              } else if (data.data && data.data.session) {
                const session = data.data.session;
                setAuthCookies(res, session);

                const isOAuthCallback =
                  req.parsedPathname === "/api/user/oauth/callback";
                const isCasCallback =
                  req.parsedPathname === "/api/user/cas/callback";
                const isCasRenewCallback =
                  req.parsedPathname === "/api/user/cas/renew_callback";
                if (isOAuthCallback) {
                  res.writeHead(302, { Location: "/" });
                  res.end();
                  return;
                }
                if (isCasCallback) {
                  res.writeHead(302, {
                    Location: data.data.redirect_url || "/",
                  });
                  res.end();
                  return;
                }
                if (isCasRenewCallback) {
                  const html = Buffer.from(`<!doctype html><html><body><script>
window.parent && window.parent.postMessage({ type: "cas-renew-success" }, window.location.origin);
</script></body></html>`);
                  const responseHeaders = {
                    "content-type": "text/html; charset=utf-8",
                    "content-length": String(html.length),
                  };
                  const existingSetCookie = res.getHeader("Set-Cookie") || [];
                  const cookiesToSend = Array.isArray(existingSetCookie)
                    ? existingSetCookie
                    : [existingSetCookie];
                  if (cookiesToSend.filter(Boolean).length > 0) {
                    responseHeaders["set-cookie"] =
                      cookiesToSend.filter(Boolean);
                  }
                  res.writeHead(200, responseHeaders);
                  res.end(html);
                  return;
                }

                if (req.parsedPathname === "/api/user/oauth/complete") {
                  clearPendingOAuthCookie(res);
                }

                const sanitized = { ...data };
                sanitized.data = { ...data.data };
                sanitized.data.session = {
                  expires_at: session.expires_at,
                  expires_in_seconds: session.expires_in_seconds,
                };
                finalBody = Buffer.from(JSON.stringify(sanitized));
              } else if (
                req.parsedPathname === "/api/user/oauth/callback" &&
                data.data &&
                data.data.oauth_error
              ) {
                const errorParams = new URLSearchParams({
                  oauth_error: data.data.oauth_error,
                  oauth_error_description:
                    data.data.oauth_error_description || "",
                });
                res.writeHead(302, { Location: `/?${errorParams.toString()}` });
                res.end();
                return;
              }
            }
          } catch {
            // If JSON parsing fails, pass through unchanged
          }

          // Copy response headers, but override content-length and set cookies
          const responseHeaders = { ...proxyRes.headers };
          responseHeaders["content-length"] = String(finalBody.length);
          // Merge Set-Cookie: proxyRes cookies + our auth cookies
          const existingSetCookie = res.getHeader("Set-Cookie") || [];
          const upstreamSetCookie = proxyRes.headers["set-cookie"] || [];
          const mergedCookies = [
            ...(Array.isArray(existingSetCookie)
              ? existingSetCookie
              : [existingSetCookie]),
            ...(Array.isArray(upstreamSetCookie)
              ? upstreamSetCookie
              : [upstreamSetCookie]),
          ].filter(Boolean);

          delete responseHeaders["set-cookie"];
          if (mergedCookies.length > 0) {
            responseHeaders["set-cookie"] = mergedCookies;
          }

          res.writeHead(proxyRes.statusCode, responseHeaders);
          res.end(finalBody);
        });
      });

      proxyReq.on("error", (err) => {
        console.error("[Auth Proxy] Forward error:", err.message);
        if (!res.headersSent) {
          res.writeHead(502, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ detail: "Backend unavailable" }));
        }
      });

      proxyReq.write(body);
      proxyReq.end();
    })
    .catch((err) => {
      console.error("[Auth Proxy] Body read error:", err.message);
      if (!res.headersSent) {
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ detail: "Internal proxy error" }));
      }
    });
}

// ============================================================================
// Cookie-to-Header injection for regular proxy requests
// ============================================================================
proxy.on("proxyReq", (proxyReq, req) => {
  const cookies = parseCookies(req);
  if (
    cookies[COOKIE_NAMES.ACCESS_TOKEN] &&
    !proxyReq.getHeader("authorization")
  ) {
    proxyReq.setHeader(
      "Authorization",
      `Bearer ${cookies[COOKIE_NAMES.ACCESS_TOKEN]}`
    );
  }
});

// ============================================================================
// Server setup
// ============================================================================
app.prepare().then(() => {
  const server = createServer(async (req, res) => {
    const parsedUrl = parse(req.url, true);
    const { pathname } = parsedUrl;
    req.parsedPathname = pathname;

    // Runtime frontend configuration for browser-only features.
    if (pathname === "/api/frontend-config") {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ shareBaseUrl: SHARE_BASE_URL }));
      return;
    }

    if (pathname === "/api/config/project-config") {
      if (!isSuperAdminRequest(req)) {
        res.writeHead(403, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ message: "Super admin access required" }));
        return;
      }

      const form = new multiparty.Form({
        uploadDir: ICON_UPLOAD_DIR,
      });
      try {
         const {fields, files} = await new Promise((res, rej) => {
            form.parse(req, (err, fields, files) => {
              if (err) rej(err);
              else res({ fields, files })
            })
          });
        if (files.logo) {
          renameFile(files.logo[0].path, 'modelengine-logo2.png');
        }
        if (files.logo2) {
          renameFile(files.logo2[0].path, 'modelengine-logo.png');
        }
        const configZh = readLocaleConfig("zh");
        const configEn = readLocaleConfig("en");
        const fieldsZh = JSON.parse(fields.configZh[0]);
        const fieldsEn = JSON.parse(fields.configEn[0]);
        const newConfigZh = updateLocalConfig(configZh, fieldsZh);
        const newConfigEn = updateLocalConfig(configEn, fieldsEn);
        saveLocaleConfig(JSON.stringify(newConfigZh, null, 2), "zh");
        saveLocaleConfig(JSON.stringify(newConfigEn, null, 2), "en");
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ message: "success update" }));
      } catch (err) {
          // example to check for a very specific error
          console.error(err);
          res.writeHead(err.httpCode || 400, { 'Content-Type': 'text/plain' });
          res.end(String(err));
          return;
      }

      return;
    }

    // Proxy HTTP requests
    if (pathname.includes("/attachments/") && !pathname.startsWith("/api/")) {
      proxy.web(req, res, { target: MINIO_BACKEND });
    } else if (pathname.startsWith("/api/")) {
      // Intercept auth endpoints to manage HttpOnly cookies
      if (AUTH_INTERCEPT_ENDPOINTS.has(pathname)) {
        const target = HTTP_BACKEND;
        forwardAuthRequest(req, res, target);
      } else if (pathname.startsWith("/api/market/")) {
        // Route market endpoints to market backend
        req.url = req.url.replace("/api/market", "");
        proxy.web(req, res, { target: MARKET_BACKEND, changeOrigin: true });
      } else {
        // Route runtime endpoints to runtime backend, others to config backend
        const isRuntime =
          pathname.startsWith("/api/agent/run") ||
          pathname.startsWith("/api/agent/stop") ||
          pathname.startsWith("/api/conversation/") ||
          pathname.startsWith("/api/share/") ||
          pathname.startsWith("/api/memory/") ||
          pathname.startsWith("/api/file/storage") ||
          pathname.startsWith("/api/file/preprocess");
        if (isRuntime) {
          const runtimeProxyTimeout = pathname.startsWith("/api/agent/run")
            ? SSE_PROXY_TIMEOUT_MS
            : PROXY_TIMEOUT_MS;
          proxy.web(req, res, {
            target: RUNTIME_HTTP_BACKEND,
            changeOrigin: true,
            proxyTimeout: runtimeProxyTimeout,
            timeout: runtimeProxyTimeout,
          });
        } else if (
          pathname === "/api/skills/create" ||
          pathname.startsWith("/api/skills/stop/")
        ) {
          proxy.web(req, res, {
            target: RUNTIME_HTTP_BACKEND,
            changeOrigin: true,
            proxyTimeout: PROXY_TIMEOUT_MS,
            timeout: PROXY_TIMEOUT_MS,
          });
        } else {
          proxy.web(req, res, {
            target: HTTP_BACKEND,
            changeOrigin: true,
            proxyTimeout: PROXY_TIMEOUT_MS,
            timeout: PROXY_TIMEOUT_MS,
          });
        }
      }
    } else {
      // Let Next.js handle the request
      handle(req, res, parsedUrl);
    }
  });

  // Proxy WebSocket upgrade requests
  server.on("upgrade", (req, socket, head) => {
    const { pathname } = parse(req.url);
    if (pathname.startsWith("/api/voice/")) {
      proxy.ws(
        req,
        socket,
        head,
        {
          target: WS_BACKEND,
          changeOrigin: true,
          proxyTimeout: PROXY_WS_TIMEOUT_MS,
          timeout: PROXY_WS_TIMEOUT_MS,
        },
        (err) => {
          console.error("[Proxy] WebSocket Proxy Error:", err);
          socket.destroy();
        }
      );
    } else {
      console.log(
        `[Proxy] Ignoring non-voice WebSocket upgrade for: ${pathname}`
      );
    }
  });

  server.listen(PORT, (err) => {
    if (err) throw err;
    console.log(`> Ready on http://localhost:${PORT}`);
    console.log("> --- Backend URL Configuration ---");
    console.log(`> HTTP Backend Target: ${HTTP_BACKEND}`);
    console.log(`> WebSocket Backend Target: ${WS_BACKEND}`);
    console.log(`> MinIO Backend Target: ${MINIO_BACKEND}`);
    console.log(`> Market Backend Target: ${MARKET_BACKEND}`);
    console.log("> ---------------------------------");
  });
});
