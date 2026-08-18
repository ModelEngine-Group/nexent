function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

export function handleHealthRequest(pathname, req, res) {
  if (pathname !== "/health/live" && pathname !== "/health/ready") {
    return false;
  }

  if (req.method !== "GET") {
    sendJson(res, 405, { message: "Method not allowed." });
    return true;
  }

  sendJson(res, 200, {
    status: pathname === "/health/live" ? "alive" : "ready",
  });
  return true;
}
