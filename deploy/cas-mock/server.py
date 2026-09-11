"""Small CAS 2.0-compatible server for local Nexent SSO integration tests."""

from __future__ import annotations

import html
import http.server
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from http import HTTPStatus


# CAS 2.0 defines this XML namespace; it is not a network endpoint.
CAS_NAMESPACE = "http://www.yale.edu/tp/cas"  # NOSONAR
DEFAULT_CONTEXT_PATH = "/cas"
DEFAULT_USERNAME = "casuser"
TICKET_TTL_SECONDS = 300


@dataclass(frozen=True)
class CasUser:
    username: str
    password: str
    display_name: str
    email: str
    role: str
    tenant_id: str


@dataclass(frozen=True)
class ServiceTicket:
    username: str
    service: str
    session_id: str
    issued_at: float


class CasState:
    def __init__(self, user: CasUser) -> None:
        self.user = user
        self.sessions: set[str] = set()
        self.tickets: dict[str, ServiceTicket] = {}

    def authenticate(self, username: str, password: str) -> bool:
        return username == self.user.username and secrets.compare_digest(password, self.user.password)

    def create_session(self) -> str:
        session_id = f"TGC-{secrets.token_urlsafe(24)}"
        self.sessions.add(session_id)
        return session_id

    def create_ticket(self, service: str, session_id: str) -> str:
        ticket = f"ST-{secrets.token_urlsafe(24)}"
        self.tickets[ticket] = ServiceTicket(
            username=self.user.username,
            service=service,
            session_id=session_id,
            issued_at=time.time(),
        )
        return ticket

    def consume_ticket(self, ticket: str, service: str) -> ServiceTicket | None:
        record = self.tickets.pop(ticket, None)
        if record is None or time.time() - record.issued_at > TICKET_TTL_SECONDS:
            return None
        if record.service != service or record.session_id not in self.sessions:
            return None
        return record


class CasMockServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], handler_class: type[http.server.BaseHTTPRequestHandler], state: CasState, context_path: str) -> None:
        super().__init__(server_address, handler_class)
        self.state = state
        self.context_path = context_path


class CasMockHandler(http.server.BaseHTTPRequestHandler):
    server: CasMockServer

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path, query = self._request_path_and_query()
        if path == "/healthz":
            self._write_text("ok")
            return

        if path == f"{self.server.context_path}/login":
            self._handle_login(query)
            return
        if path == f"{self.server.context_path}/p3/serviceValidate":
            self._handle_service_validate(query)
            return
        if path == f"{self.server.context_path}/logout":
            self._handle_logout(query)
            return
        if path == "/":
            self._write_html(self._landing_page())
            return
        self._write_text("Not found", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path, query = self._request_path_and_query()
        if path == f"{self.server.context_path}/login":
            self._handle_login(query, self._read_form())
            return
        if path == f"{self.server.context_path}/logout":
            self._handle_logout(query)
            return
        self._write_text("Not found", HTTPStatus.NOT_FOUND)

    def _handle_login(self, query: dict[str, list[str]], form: dict[str, list[str]] | None = None) -> None:
        service = self._first(form or query, "service")
        gateway = self._first(form or query, "gateway") == "true"
        session_id = self._cookie("CASTGC")

        if session_id in self.server.state.sessions:
            self._redirect_with_ticket(service, session_id)
            return
        if gateway:
            self._redirect(service)
            return

        if form is None:
            self._write_html(self._login_page(service))
            return

        username = self._first(form, "username")
        password = self._first(form, "password")
        if not self.server.state.authenticate(username, password):
            self._write_html(self._login_page(service, "用户名或密码错误"), HTTPStatus.UNAUTHORIZED)
            return

        session_id = self.server.state.create_session()
        self._redirect_with_ticket(service, session_id, set_session=True)

    def _handle_service_validate(self, query: dict[str, list[str]]) -> None:
        ticket = self._first(query, "ticket")
        service = self._first(query, "service")
        record = self.server.state.consume_ticket(ticket, service)
        if record is None:
            response = (
                f'<cas:serviceResponse xmlns:cas="{CAS_NAMESPACE}">'
                '<cas:authenticationFailure code="INVALID_TICKET">'
                "Ticket is invalid or has expired"
                "</cas:authenticationFailure>"
                "</cas:serviceResponse>"
            )
            self._write_xml(response)
            return

        user = self.server.state.user
        response = f"""<cas:serviceResponse xmlns:cas="{CAS_NAMESPACE}">
  <cas:authenticationSuccess>
    <cas:user>{self._xml(user.username)}</cas:user>
    <cas:attributes>
      <cas:uid>{self._xml(user.username)}</cas:uid>
      <cas:email>{self._xml(user.email)}</cas:email>
      <cas:displayName>{self._xml(user.display_name)}</cas:displayName>
      <cas:name>{self._xml(user.display_name)}</cas:name>
      <cas:role>{self._xml(user.role)}</cas:role>
      <cas:tenant_id>{self._xml(user.tenant_id)}</cas:tenant_id>
      <cas:SessionIndex>{self._xml(record.session_id)}</cas:SessionIndex>
    </cas:attributes>
  </cas:authenticationSuccess>
</cas:serviceResponse>"""
        self._write_xml(response)

    def _handle_logout(self, query: dict[str, list[str]]) -> None:
        session_id = self._cookie("CASTGC")
        self.server.state.sessions.discard(session_id)
        service = self._first(query, "service")
        headers = [("Set-Cookie", "CASTGC=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax")]
        if service:
            self._redirect(service, headers)
            return
        self._write_html("<h1>已退出 CAS</h1>", headers=headers)

    def _redirect_with_ticket(self, service: str, session_id: str, set_session: bool = False) -> None:
        if not service:
            self._write_text("Missing service parameter", HTTPStatus.BAD_REQUEST)
            return
        ticket = self.server.state.create_ticket(service, session_id)
        separator = "&" if "?" in service else "?"
        headers: list[tuple[str, str]] = []
        if set_session:
            headers.append(("Set-Cookie", f"CASTGC={session_id}; Path=/; HttpOnly; SameSite=Lax"))
        self._redirect(f"{service}{separator}ticket={urllib.parse.quote(ticket)}", headers)

    def _login_page(self, service: str, error: str = "") -> str:
        message = f'<p class="error">{html.escape(error)}</p>' if error else ""
        return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>CAS 登录</title>
<style>body{{font-family:Arial,sans-serif;max-width:420px;margin:80px auto}}label{{display:block;margin:12px 0 4px}}input{{width:100%;padding:9px;box-sizing:border-box}}button{{margin-top:18px;padding:9px 20px}}.error{{color:#b42318}}</style>
</head><body><h1>CAS 登录</h1>{message}
<form method="post" action="{self.server.context_path}/login">
<input type="hidden" name="service" value="{html.escape(service, quote=True)}">
<label>用户名</label><input name="username" value="{html.escape(self.server.state.user.username, quote=True)}" required>
<label>密码</label><input name="password" type="password" required>
<button type="submit">登录</button>
</form><p>本地测试账号：casuser / casuser</p></body></html>"""

    def _landing_page(self) -> str:
        user = self.server.state.user
        return f"<h1>本地 CAS Mock Server</h1><p>测试用户：{html.escape(user.username)}</p><p>健康检查：<a href='/healthz'>/healthz</a></p>"

    def _request_path_and_query(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urllib.parse.urlsplit(self.path)
        return parsed.path, urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

    def _read_form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        return urllib.parse.parse_qs(body, keep_blank_values=True)

    def _cookie(self, name: str) -> str:
        raw = self.headers.get("Cookie", "")
        cookies = {
            key_value[0]: key_value[1]
            for item in raw.split(";")
            if "=" in item
            for key_value in [item.strip().split("=", 1)]
        }
        return cookies.get(name, "")

    @staticmethod
    def _first(values: dict[str, list[str]], key: str) -> str:
        return values.get(key, [""])[0]

    @staticmethod
    def _xml(value: str) -> str:
        return html.escape(value, quote=False)

    def _redirect(self, location: str, extra_headers: list[tuple[str, str]] | None = None) -> None:
        headers = [("Location", location), *(extra_headers or [])]
        self.send_response(HTTPStatus.FOUND)
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()

    def _write_html(self, content: str, status: HTTPStatus = HTTPStatus.OK, headers: list[tuple[str, str]] | None = None) -> None:
        payload = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for key, value in headers or []:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _write_xml(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _write_text(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"[cas-mock] {self.address_string()} - {format_string % args}")


def load_user() -> CasUser:
    password = os.getenv("CAS_MOCK_PASSWORD")
    if not password:
        raise RuntimeError("CAS_MOCK_PASSWORD must be set")

    return CasUser(
        username=os.getenv("CAS_MOCK_USERNAME", DEFAULT_USERNAME),
        password=password,
        display_name=os.getenv("CAS_MOCK_DISPLAY_NAME", DEFAULT_USERNAME),
        email=os.getenv("CAS_MOCK_EMAIL", "casuser@example.com"),
        role=os.getenv("CAS_MOCK_ROLE", "USER"),
        tenant_id=os.getenv("CAS_MOCK_TENANT_ID", "tenant_id"),
    )


def main() -> None:
    host = os.getenv("CAS_MOCK_HOST", "0.0.0.0")
    port = int(os.getenv("CAS_MOCK_PORT", "8080"))
    context_path = "/" + os.getenv("CAS_MOCK_CONTEXT_PATH", DEFAULT_CONTEXT_PATH).strip("/")
    server = CasMockServer((host, port), CasMockHandler, CasState(load_user()), context_path)
    print(f"CAS mock listening on {host}:{port}{context_path}")
    # This mock server intentionally uses plain HTTP for local integration tests.
    server.serve_forever()  # NOSONAR


if __name__ == "__main__":
    main()
