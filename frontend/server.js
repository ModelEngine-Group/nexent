const { createServer } = require('http');
const { parse } = require('url');
const next = require('next');
const { createProxyServer } = require('http-proxy');

const dev = process.env.NODE_ENV !== 'production';
const app = next({ 
  dev,
});
const handle = app.getRequestHandler();
const wsHandle = app.getUpgradeHandler();

// 后端地址
const HTTP_BACKEND = process.env.HTTP_BACKEND || 'http://localhost:5010';
const WS_BACKEND = process.env.WS_BACKEND || 'ws://localhost:5010';
const MINIO_BACKEND = process.env.MINIO_ENDPOINT || 'http://localhost:9000';
const PORT = 3000

const proxy = createProxyServer();
app.prepare().then(() => {
  const server = createServer((req, res) => {
    const parsedUrl = parse(req.url, true);
    const { pathname } = parsedUrl;

    // 代理普通 HTTP 请求
    if (pathname.includes('/attachments/') && !pathname.startsWith('/api/')) {
      console.log(MINIO_BACKEND)
      proxy.web(req, res, { target: MINIO_BACKEND });
    } else if (pathname.startsWith('/api/') && !pathname.startsWith('/api/voice/')) {
      proxy.web(req, res, { target: HTTP_BACKEND });
    } else {
      handle(req, res, parsedUrl);
    }
  });

  // 代理 WebSocket 请求
  server.on('upgrade', (req, socket, head) => {
    const { pathname } = parse(req.url);
    if (pathname.startsWith('/api/voice/')) {
      proxy.ws(req, socket, head, { target: WS_BACKEND });
    } else {
      wsHandle(req, socket, head);
    }
  });

  server.listen(PORT, () => {
    console.log(`> Ready on http://localhost:${PORT}`);
    console.log('> Backend URLs:');
    console.log(`  HTTP Backend: ${HTTP_BACKEND}`);
    console.log(`  WebSocket Backend: ${WS_BACKEND}`);
    console.log(`  MinIO Backend: ${MINIO_BACKEND}`);
  });
});