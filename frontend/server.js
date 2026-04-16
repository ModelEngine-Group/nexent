const { createServer } = require("http");
const http = require("http");
const https = require("https");
const { parse } = require("url");
const next = require("next");
const { createProxyServer } = require("http-proxy");
const cookie = require("cookie");
const path = require("path");

// Load environment variables from .env file in parent directory (project root)
// In container environments, env vars are injected directly by Docker, so .env file may not exist
// Using optional: true to avoid errors if .env file is not found
require("dotenv").config({
  path: path.resolve(__dirname, "../.env"),
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
const PORT = 3000;

const proxy = createProxyServer();

// ============================================================================
// Cookie configuration
// ============================================================================
const COOKIE_NAMES = {
  ACCESS_TOKEN: "nexent_access_token",
  REFRESH_TOKEN: "nexent_refresh_token",
  EXPIRES_AT: "nexent_token_expires_at",
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
      cookie.serialize(
        COOKIE_NAMES.EXPIRES_AT,
        String(session.expires_at),
        {
          ...buildCookieOptions(false), // readable by frontend JS
          maxAge: expiresInSeconds, // Same as access token
        }
      )
    );
  }

  if (cookies.length > 0) {
    res.setHeader("Set-Cookie", cookies);
  }
}

function clearAuthCookies(res) {
  const expired = { maxAge: 0, path: "/" };
  res.setHeader("Set-Cookie", [
    cookie.serialize(COOKIE_NAMES.ACCESS_TOKEN, "", { ...expired, httpOnly: true }),
    cookie.serialize(COOKIE_NAMES.REFRESH_TOKEN, "", { ...expired, httpOnly: true }),
    cookie.serialize(COOKIE_NAMES.EXPIRES_AT, "", expired),
  ]);
}

function parseCookies(req) {
  return cookie.parse(req.headers.cookie || "");
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
 */
function prepareAuthRequestBody(pathname, body, cookies) {
  if (pathname === "/api/user/refresh_token" && cookies[COOKIE_NAMES.REFRESH_TOKEN]) {
    try {
      const parsed = body.length > 0 ? JSON.parse(body.toString()) : {};
      parsed.refresh_token = cookies[COOKIE_NAMES.REFRESH_TOKEN];
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

  collectRequestBody(req).then((rawBody) => {
    const body = prepareAuthRequestBody(req.parsedPathname, rawBody, cookies);

    const forwardHeaders = { ...req.headers, host: parsedTarget.host };

    // Inject access_token from cookie as Authorization header for the backend
    if (cookies[COOKIE_NAMES.ACCESS_TOKEN] && !forwardHeaders["authorization"]) {
      forwardHeaders["authorization"] = `Bearer ${cookies[COOKIE_NAMES.ACCESS_TOKEN]}`;
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
          if (contentType.includes("application/json") && responseBody.length > 0) {
            const data = JSON.parse(responseBody.toString());

            const isLogout = req.parsedPathname === "/api/user/logout";
            const isRevoke = req.parsedPathname === "/api/user/revoke";

            if (isLogout || isRevoke) {
              clearAuthCookies(res);
            } else if (data.data && data.data.session) {
              const session = data.data.session;
              setAuthCookies(res, session);

              const isOAuthCallback = req.parsedPathname === "/api/user/oauth/callback";
              if (isOAuthCallback) {
                res.writeHead(302, { Location: "/chat" });
                res.end();
                return;
              }

              const sanitized = { ...data };
              sanitized.data = { ...data.data };
              sanitized.data.session = {
                expires_at: session.expires_at,
                expires_in_seconds: session.expires_in_seconds,
              };
              finalBody = Buffer.from(JSON.stringify(sanitized));
            } else if (req.parsedPathname === "/api/user/oauth/callback" && data.data && data.data.oauth_error) {
              const errorParams = new URLSearchParams({
                oauth_error: data.data.oauth_error,
                oauth_error_description: data.data.oauth_error_description || "",
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
          ...(Array.isArray(existingSetCookie) ? existingSetCookie : [existingSetCookie]),
          ...(Array.isArray(upstreamSetCookie) ? upstreamSetCookie : [upstreamSetCookie]),
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
  }).catch((err) => {
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
  if (cookies[COOKIE_NAMES.ACCESS_TOKEN] && !proxyReq.getHeader("authorization")) {
    proxyReq.setHeader("Authorization", `Bearer ${cookies[COOKIE_NAMES.ACCESS_TOKEN]}`);
  }
});

// ============================================================================
// Server setup
// ============================================================================
app.prepare().then(() => {
  const server = createServer((req, res) => {
    const parsedUrl = parse(req.url, true);
    const { pathname } = parsedUrl;
    req.parsedPathname = pathname;

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
          pathname.startsWith("/api/memory/") ||
          pathname.startsWith("/api/file/storage") ||
          pathname.startsWith("/api/file/preprocess") ||
          pathname.startsWith("/api/skills/create-simple");
        const target = isRuntime ? RUNTIME_HTTP_BACKEND : HTTP_BACKEND;
        proxy.web(req, res, { target, changeOrigin: true });
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
        { target: WS_BACKEND, changeOrigin: true },
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
