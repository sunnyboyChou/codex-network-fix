#!/usr/bin/env python3
"""
codex-relay: 本地转发服务
把 pi 的 openai-codex 请求转发到 chatgpt.com/backend-api，
使用 curl_cffi 的 Chrome TLS 指纹绕过 Cloudflare 的 JA3 风控。

用法: python3 codex-relay.py [--port 8899]
"""
import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from curl_cffi import requests as cffi_requests

UPSTREAM = "https://chatgpt.com"
# 与 Codex App / 官方客户端一致的后端 API 版本头
BACKEND_VERSION = "2025-08-07"
PROXY = "http://127.0.0.1:7897"

# 需要透传的请求头（pi 发的）
PASS_HEADERS = [
    "authorization",
    "content-type",
    "content-encoding",  # pi 的 SSE body 是 zstd 压缩的，必须透传标记
    "accept",
    "openai-backend-api-version",
    "openai-beta",
    "x-request-id",
    "x-client-version",
]


class RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[relay] %s\n" % (fmt % args))

    def _handle(self):
        parsed = urlparse(self.path)
        # pi 的 openai-codex baseUrl 是 http://127.0.0.1:8899
        # 它请求的路径是 /codex/responses（缺少 /backend-api 前缀）
        # 真实上游是 https://chatgpt.com/backend-api/codex/responses
        path = parsed.path
        if not path.startswith("/backend-api"):
            path = "/backend-api" + path
        target = UPSTREAM + path
        if parsed.query:
            target += "?" + parsed.query

        # 组装转发头
        headers = {}
        for name in PASS_HEADERS:
            val = self.headers.get(name)
            if val:
                headers[name] = val
        headers.setdefault("accept", "application/json")
        headers.setdefault("openai-backend-api-version", BACKEND_VERSION)

        length = int(self.headers.get("content-length", 0))
        body = self.rfile.read(length) if length > 0 else None

        sys.stderr.write(f"[relay] {self.command} {target} -> {self.headers.get('authorization', 'no-auth')[:20]}...\n")

        try:
            upstream = cffi_requests.request(
                self.command,
                target,
                headers=headers,
                data=body,
                impersonate="chrome",
                proxies={"https": PROXY, "http": PROXY},
                timeout=300,
                stream=True,
            )
        except Exception as e:
            self.send_response(502)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": f"relay upstream error: {e}"}}).encode())
            return

        # 转发状态与响应头
        self.send_response(upstream.status_code)
        skip = {"transfer-encoding", "connection", "keep-alive"}
        for k, v in upstream.headers.items():
            if k.lower() in skip:
                continue
            # content-encoding: 上游 SSE 一般不用压缩；若有则保留
            self.send_header(k, v)
        self.end_headers()

        # 流式转发响应体（SSE）
        try:
            for chunk in upstream.iter_content(chunk_size=8192):
                if chunk:
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            upstream.close()

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def do_OPTIONS(self):
        self._handle()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--upstream", default=UPSTREAM)
    args = ap.parse_args()
    if args.upstream != UPSTREAM:
        raise SystemExit("--upstream 需在模块顶部修改 UPSTREAM 常量，或删除该参数")
    # UPSTREAM 由模块常量决定，保持简单

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), RelayHandler)
    print(f"[codex-relay] listening on http://127.0.0.1:{args.port} -> {UPSTREAM} (chrome fingerprint via {PROXY})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
