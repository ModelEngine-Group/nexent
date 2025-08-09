const { createServer } = require('http');
const { parse } = require('url');
const next = require('next');
const { createProxyServer } = require('http-proxy');

const dev = process.env.NODE_ENV !== 'production';
const app = next({ 
  dev,
});
const handle = app.getRequestHandler();

// Backend addresses
const HTTP_BACKEND = process.env.HTTP_BACKEND || 'http://localhost:5010';
const WS_BACKEND = process.env.WS_BACKEND || 'ws://localhost:5010';
const MINIO_BACKEND = process.env.MINIO_ENDPOINT || 'http://localhost:9000';
const PORT = 3000;

const proxy = createProxyServer();

app.prepare().then(() => {
  const server = createServer((req, res) => {
    const parsedUrl = parse(req.url, true);
    const { pathname } = parsedUrl;

    // Proxy HTTP requests
    if (pathname.includes('/attachments/') && !pathname.startsWith('/api/')) {
      proxy.web(req, res, { target: MINIO_BACKEND });
    } else if (pathname.startsWith('/api/')) {
      // All /api/ requests (including the initial handshake for WebSockets) go to the backend
      proxy.web(req, res, { target: HTTP_BACKEND, changeOrigin: true });
    } else {
      // Let Next.js handle all other requests
      handle(req, res, parsedUrl);
    }
  });

  // Proxy WebSocket upgrade requests
  server.on('upgrade', (req, socket, head) => {
    const { pathname } = parse(req.url);
    if (pathname.startsWith('/api/voice/')) {
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
    console.log('> ---------------------------------');
  });
});
