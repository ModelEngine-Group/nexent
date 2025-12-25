const { createServer } = require('http');
const { parse } = require('url');
const next = require('next');
const { createProxyServer } = require('http-proxy');
const path = require('path');

// Load environment variables from .env file in parent directory (project root)
// In container environments, env vars are injected directly by Docker, so .env file may not exist
// Using optional: true to avoid errors if .env file is not found
require('dotenv').config({
  path: path.resolve(__dirname, '../.env'),
  override: false // Don't override existing environment variables (important for Docker)
});

const dev = process.env.NODE_ENV !== 'production';
const app = next({
  dev,
});
const handle = app.getRequestHandler();

// Backend addresses
const HTTP_BACKEND = process.env.HTTP_BACKEND || 'http://localhost:5010'; // config
const WS_BACKEND = process.env.WS_BACKEND || 'ws://localhost:5014'; // runtime
const RUNTIME_HTTP_BACKEND = process.env.RUNTIME_HTTP_BACKEND || 'http://localhost:5014'; // runtime
const MINIO_BACKEND = process.env.MINIO_ENDPOINT || 'http://localhost:9010';
const MARKET_BACKEND = process.env.MARKET_BACKEND || 'https://market.nexent.tech'; // market
const PORT = 3000;
// Expose MODEL_ENGINE_ENABLED to client via runtime JS endpoint
// Read raw env value and parse to a boolean for server-side checks.
const MODEL_ENGINE_ENABLED = process.env.MODEL_ENGINE_ENABLED || 'false';
const modelEngineEnabled =
  MODEL_ENGINE_ENABLED === true ||
  String(MODEL_ENGINE_ENABLED).toLowerCase() === 'true' ||
  String(MODEL_ENGINE_ENABLED) === '1';

const proxy = createProxyServer();

app.prepare().then(() => {
  const server = createServer((req, res) => {
    const parsedUrl = parse(req.url, true);
    const { pathname } = parsedUrl;

    // Serve a small runtime script so the client can read the server env flag without rebuild
    if (pathname === '/__runtime_config.js') {
      res.setHeader('Content-Type', 'application/javascript; charset=utf-8');
      res.setHeader('Cache-Control', dev ? 'no-cache' : 'public, max-age=600');
      const boolLiteral = modelEngineEnabled ? 'true' : 'false';
      res.end(`window.__MODEL_ENGINE_ENABLED = ${boolLiteral};`);
      return;
    }

    // Proxy HTTP requests
    if (pathname.includes('/attachments/') && !pathname.startsWith('/api/')) {
      proxy.web(req, res, { target: MINIO_BACKEND });
    } else if (pathname.startsWith('/api/')) {
      // Route market endpoints to market backend
      if (pathname.startsWith('/api/market/')) {
        // Rewrite path: /api/market/agents -> /agents
        req.url = req.url.replace('/api/market', '');
        proxy.web(req, res, { target: MARKET_BACKEND, changeOrigin: true });
      } else {
      // Route runtime endpoints to runtime backend, others to config backend
      const isRuntime =
        pathname.startsWith('/api/agent/run') ||
        pathname.startsWith('/api/agent/stop') ||
        pathname.startsWith('/api/conversation/') ||
        pathname.startsWith('/api/memory/') ||
        pathname.startsWith('/api/file/storage') ||
        pathname.startsWith('/api/file/preprocess');
      // If runtime endpoints are requested but the model engine is disabled, respond accordingly.
      if (isRuntime && !modelEngineEnabled) {
        res.statusCode = 503;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(JSON.stringify({ error: 'Model engine is disabled on this server' }));
        return;
      }
      const target = isRuntime ? RUNTIME_HTTP_BACKEND : HTTP_BACKEND;
      proxy.web(req, res, { target, changeOrigin: true });
      }
    } else {
      // Let Next.js handle all other requests
      handle(req, res, parsedUrl);
    }
  });

  // Proxy WebSocket upgrade requests
  server.on('upgrade', (req, socket, head) => {
    const { pathname } = parse(req.url);
    if (pathname.startsWith('/api/voice/')) {
      if (!modelEngineEnabled) {
        console.log('[Proxy] Rejecting WebSocket upgrade for voice because model engine is disabled:', pathname);
        try {
          socket.write('HTTP/1.1 503 Service Unavailable\r\n\r\n');
        } catch (e) {
          // ignore
        }
        socket.destroy();
        return;
      }
      proxy.ws(req, socket, head, { target: WS_BACKEND, changeOrigin: true }, (err) => {
        console.error('[Proxy] WebSocket Proxy Error:', err);
        socket.destroy();
      });
    } else {
      console.log(`[Proxy] Ignoring non-voice WebSocket upgrade for: ${pathname}`);
      // Do nothing for other WebSocket requests (like Next.js HMR).
    }
  });

  server.listen(PORT, (err) => {
    if (err) throw err;
    console.log(`> Ready on http://localhost:${PORT}`);
    console.log('> --- Backend URL Configuration ---');
    console.log(`> HTTP Backend Target: ${HTTP_BACKEND}`);
    console.log(`> WebSocket Backend Target: ${WS_BACKEND}`);
    console.log(`> MinIO Backend Target: ${MINIO_BACKEND}`);
    console.log(`> Market Backend Target: ${MARKET_BACKEND}`);
    console.log(`> ModelEngine Enabled: ${modelEngineEnabled}`);
    console.log('> ---------------------------------');
  });
});
