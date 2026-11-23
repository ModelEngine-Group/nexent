// Exercise production routing and error handling with an isolated loopback upstream.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const vm = require('node:vm');
const { createRequire } = require('node:module');

const root = path.resolve(__dirname, '../../..');
const source = fs.readFileSync(path.join(root, 'frontend/server.js'), 'utf8');
const frontendRequire = createRequire(path.join(root, 'frontend/package.json'));
const proxy = frontendRequire('http-proxy').createProxyServer({});
const functionStart = source.indexOf('function handleAllApiProxy(');
const functionEnd = source.indexOf('// ====================== 通用工具函数', functionStart);
const errorStart = source.indexOf('proxy.on("error",');
const errorEnd = source.indexOf('\n});', errorStart) + '\n});'.length;
assert(functionStart >= 0 && functionEnd > functionStart && errorStart >= 0 && errorEnd > errorStart,
  'Production routing boundaries changed; update the probe explicitly');
const listen = server => new Promise((resolve, reject) => {
  server.once('error', reject);
  server.listen(0, '127.0.0.1', () => resolve(server.address().port));
});
const close = server => new Promise((resolve, reject) => {
  server.close(error => error ? reject(error) : resolve());
  server.closeAllConnections();
});

async function main() {
  const observations = [];
  const upstream = http.createServer((req, res) => {
    const status = req.url.includes('absent') ? 404 : req.url.includes('deny') ? 403 : 200;
    observations.push({ method: req.method, url: req.url });
    res.writeHead(status, { 'Content-Type': 'application/json', 'X-Probe-Upstream': 'isolated' });
    res.end(JSON.stringify({ method: req.method, url: req.url, status }));
  });
  let server;
  let upstreamOpen = false;
  try {
    const port = await listen(upstream);
    upstreamOpen = true;
    const context = vm.createContext({
      proxy, HTTP_BACKEND: `http://127.0.0.1:${port}`,
      PROXY_TIMEOUT_MS: 2000, SSE_PROXY_TIMEOUT_MS: 2000,
      AUTH_INTERCEPT_ENDPOINTS: new Set(), console: { error() {} },
      forwardAuthRequest() { throw new Error('Unexpected auth routing'); },
      getRuntimeProxyConfig() { throw new Error('Market/Repository reached Runtime'); },
    });
    vm.runInContext(source.slice(errorStart, errorEnd) + '\n' +
      source.slice(functionStart, functionEnd), context, { filename: 'frontend/server.js' });
    server = http.createServer((req, res) => {
      const pathname = new URL(req.url, 'http://loopback').pathname;
      if (!context.handleAllApiProxy(pathname, req, res)) { res.writeHead(404); res.end(); }
    });
    const base = `http://127.0.0.1:${await listen(server)}`;
    const paths = [
      '/api/market/agents?tag=general&page=1',
      '/api/market/absent?tag_predicates=%5B%7B%22x%22%3A1%7D%5D',
      '/api/repository/agent?tag=general&page_size=10', '/api/repository/deny',
    ];
    for (const requestPath of paths) {
      const response = await fetch(base + requestPath);
      const body = await response.json();
      assert.equal(body.url, requestPath);
      assert.equal(body.method, 'GET');
      assert.equal(response.status, body.status);
      assert.equal(response.headers.get('x-probe-upstream'), 'isolated');
    }
    assert.equal(observations.length, paths.length);
    await close(upstream);
    upstreamOpen = false;
    for (const requestPath of ['/api/market/agents', '/api/repository/agent']) {
      const response = await fetch(base + requestPath);
      assert.equal(response.status, 502);
      assert.deepEqual(await response.json(), { detail: 'Backend unavailable' });
    }
    await new Promise((resolve, reject) => {
      upstream.once('error', reject);
      upstream.listen(port, '127.0.0.1', resolve);
    });
    upstreamOpen = true;
    const restored = await fetch(base + paths[0]);
    assert.equal(restored.status, 200);
    assert.equal((await restored.json()).url, paths[0]);
    process.stdout.write(JSON.stringify({ result: 'PASS', forwarded: observations, outage_status: 502 }) + '\n');
  } finally {
    if (server) await close(server);
    if (upstreamOpen) await close(upstream);
    proxy.close();
  }
}
main().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
