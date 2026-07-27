# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from click.testing import CliRunner

from qwenpaw.cli import desktop_cmd as desktop_cmd_module
from qwenpaw.cli.desktop_cmd import _DesktopConsoleStaticHandler, desktop_cmd


def test_desktop_remote_api_url_serves_local_frontend_without_backend(
    monkeypatch,
) -> None:
    created: dict[str, object] = {}
    started: list[bool] = []
    server_events: list[str] = []
    server_args: dict[str, str] = {}

    class FakeWebview:
        @staticmethod
        def create_window(*args, **kwargs):
            created["args"] = args
            created["kwargs"] = kwargs

        @staticmethod
        def start(*args, **kwargs):
            started.append(True)

    def fail_popen(*_args, **_kwargs):
        raise AssertionError("remote desktop mode must not start local backend")

    class FakeServer:
        def shutdown(self):
            server_events.append("shutdown")

        def server_close(self):
            server_events.append("close")

    def fake_start_remote_console_server(*, api_base_url: str, host: str):
        server_args["api_base_url"] = api_base_url
        server_args["host"] = host
        return FakeServer(), "http://127.0.0.1:32123/"

    monkeypatch.setattr(desktop_cmd_module, "webview", FakeWebview)
    monkeypatch.setattr(desktop_cmd_module.subprocess, "Popen", fail_popen)
    monkeypatch.setattr(
        desktop_cmd_module,
        "_start_remote_console_server",
        fake_start_remote_console_server,
    )

    result = CliRunner().invoke(
        desktop_cmd,
        ["--remote-api-url", "https://dclaw.deepmega.cn/"],
    )

    assert result.exit_code == 0
    assert server_args == {
        "api_base_url": "https://dclaw.deepmega.cn",
        "host": "127.0.0.1",
    }
    assert created["args"][:2] == ("DClaw", "http://127.0.0.1:32123/")
    assert created["kwargs"]["width"] == 1280
    assert started == [True]
    assert server_events == ["shutdown", "close"]


def test_desktop_remote_console_server_proxies_api_requests(tmp_path) -> None:
    class UpstreamHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/api/auth/status":
                body = b'{"enabled":true,"has_users":true}'
                self.send_response(200)
            else:
                body = b'{"detail":"Not authenticated"}'
                self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    upstream_thread = threading.Thread(
        target=upstream.serve_forever,
        daemon=True,
    )
    upstream_thread.start()

    index_path = tmp_path / "index.html"
    index_path.write_text(
        "<html><head></head><body>DClaw</body></html>",
        encoding="utf-8",
    )
    asset_path = tmp_path / "登陆界面IP.png"
    asset_path.write_bytes(b"fake-png")
    handler = type(
        "DesktopProxyHandler",
        (_DesktopConsoleStaticHandler,),
        {
            "api_base_url": "",
            "remote_api_url": f"http://127.0.0.1:{upstream.server_port}",
            "static_dir": tmp_path,
            "index_path": index_path,
        },
    )
    local = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    local_thread = threading.Thread(target=local.serve_forever, daemon=True)
    local_thread.start()

    try:
        base = f"http://127.0.0.1:{local.server_port}"
        status_body = urllib.request.urlopen(
            f"{base}/api/auth/status",
            timeout=5,
        ).read()
        assert status_body == b'{"enabled":true,"has_users":true}'

        with urllib.request.urlopen(f"{base}/", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert 'window.__DCLAW_DESKTOP_API_BASE_URL__ = "";' in html

        encoded_asset = urllib.parse.quote("登陆界面IP.png")
        with urllib.request.urlopen(f"{base}/{encoded_asset}", timeout=5) as response:
            assert response.read() == b"fake-png"

        try:
            urllib.request.urlopen(f"{base}/api/user/agents", timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
            assert exc.read() == b'{"detail":"Not authenticated"}'
        else:
            raise AssertionError("Expected proxied upstream 401")
    finally:
        local.shutdown()
        local.server_close()
        upstream.shutdown()
        upstream.server_close()
