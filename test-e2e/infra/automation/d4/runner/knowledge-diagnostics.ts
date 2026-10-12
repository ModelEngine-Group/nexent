import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export function knowledgeRetrievalFailure(status: number, body: unknown, resultDir = process.env.RESULT_DIR): Error {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  const diagnostic = {
    http_status: status,
    upstream_tls_error: /SSLError|SSLEOFError|SSL:|TLS|certificate verify failed/i.test(text),
    upstream_connection_error: /ConnectionError|connection reset|connection refused|Max retries exceeded/i.test(text),
    upstream_timeout: /ReadTimeout|ConnectTimeout|timed out/i.test(text),
  };
  // Provider errors may embed credentials and internal URLs. Persist only
  // fixed booleans and the HTTP status, never the original response body.
  if (resultDir) {
    const directory = join(resultDir, "runtime");
    mkdirSync(directory, { recursive: true });
    writeFileSync(join(directory, "knowledge-retrieval-failure.json"), JSON.stringify(diagnostic, null, 2));
  }
  const error = new Error(`knowledge hybrid search returned HTTP ${status}; upstream_tls_error=${diagnostic.upstream_tls_error}, upstream_connection_error=${diagnostic.upstream_connection_error}, upstream_timeout=${diagnostic.upstream_timeout}; inspect runtime/knowledge-retrieval-failure.json`);
  // A failed product HTTP response is an execution FAIL, not a script crash.
  // This category alone does not attribute its root cause to product code.
  error.name = "ProductFailure";
  return error;
}
