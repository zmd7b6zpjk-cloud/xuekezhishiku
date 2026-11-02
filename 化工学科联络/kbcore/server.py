"""本地 HTTP 服务：静态界面 + JSON API。

只用标准库（http.server + sqlite3），不依赖任何第三方包，离线可用。
默认只监听 127.0.0.1；需要手机访问时用 ``--lan``，会自动生成访问令牌。
"""

from __future__ import annotations

import json
import mimetypes
import secrets
import socket
import sys
import traceback
import urllib.parse
import webbrowser
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .store import KBError, Store

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY = 8 * 1024 * 1024
MAX_UPLOAD = 10 * 1024 * 1024
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "DisciplineKB/" + __version__

    # ------------------------------------------------------------ 基础设施
    @property
    def store(self) -> Store:
        return self.server.store  # type: ignore[attr-defined]

    def log_message(self, format, *args):  # noqa: A002 - 覆盖父类签名
        return

    def _parse_path(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path, encoding="utf-8", errors="replace")
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        return path, query

    def _token_ok(self, query) -> bool:
        token = getattr(self.server, "token", "")
        if not token:
            return True
        supplied = ""
        if query.get("token"):
            supplied = query["token"][0]
        elif self.headers.get("X-KB-Token"):
            supplied = self.headers["X-KB-Token"]
        else:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            if "kb_token" in cookie:
                supplied = cookie["kb_token"].value
        return secrets.compare_digest(supplied, token)

    def _guard(self, query) -> bool:
        if self._token_ok(query):
            token = getattr(self.server, "token", "")
            if token and query.get("token"):
                self._pending_cookie = (
                    f"kb_token={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000"
                )
            return True
        self._json({"error": "需要访问令牌，请使用启动时打印的带 token 的网址"}, 401)
        return False

    def _common_headers(self, status: int, length: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        cookie = getattr(self, "_pending_cookie", None)
        if cookie:
            self.send_header("Set-Cookie", cookie)
            self._pending_cookie = None

    def _json(self, payload, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self._common_headers(status, len(data), "application/json; charset=utf-8")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _file(self, path: Path, download: str | None = None) -> None:
        if not path.is_file():
            self._json({"error": "文件不存在", "path": path.name}, 404)
            return
        data = path.read_bytes()
        content_type = _MIME.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._common_headers(200, len(data), content_type)
        if download:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(download))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _safe_file(self, base: Path, relative: str) -> Path:
        target = (base / relative).resolve()
        base_resolved = base.resolve()
        if not target.is_relative_to(base_resolved):
            raise KBError("非法路径", 403)
        if not target.is_file():
            raise KBError("文件不存在", 404)
        return target

    def _body_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise KBError("请求内容过大", 413)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise KBError("请求体不是合法的 JSON", 400)
        if not isinstance(payload, dict):
            raise KBError("请求体必须是 JSON 对象", 400)
        return payload

    def _entry_payload(self, payload: dict) -> dict:
        title = str(payload.get("title") or "").strip()
        if not title:
            raise KBError("标题不能为空")
        body = payload.get("body")
        return {
            "title": title,
            "body": None if body is None else str(body),
            "discipline": "" if payload.get("discipline") is None else str(payload.get("discipline")),
            "tags": payload.get("tags") or [],
        }

    # ------------------------------------------------------------ 路由
    def do_GET(self):  # noqa: N802
        path, query = self._parse_path()
        try:
            if path == "/favicon.ico":
                self._common_headers(204, 0, "image/x-icon")
                self.end_headers()
                return
            if not self._guard(query):
                return
            if path in ("/", "/index.html"):
                self._file(STATIC_DIR / "index.html")
                return
            if path.startswith("/static/"):
                self._file(self._safe_file(STATIC_DIR, path[len("/static/"):]))
                return
            if path.startswith("/attachments/"):
                self._file(self._safe_file(self.store.attachments, path[len("/attachments/"):]))
                return
            if path == "/api/health":
                self._json({
                    "ok": True,
                    "app": "化工学科联络 · 本地知识库",
                    "version": __version__,
                    "root": str(self.store.root),
                    "cards": self.store.stats()["cards"],
                })
                return
            if path == "/api/stats":
                self._json(self.store.stats())
                return
            if path == "/api/graph":
                self._json(self.store.graph())
                return
            if path == "/api/export":
                data = self.store.export_zip_bytes()
                name = f"知识库备份-{datetime.now():%Y%m%d-%H%M}.zip"
                self._common_headers(200, len(data), "application/zip")
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(name))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            if path == "/api/entries":
                limit = _clamp(query.get("limit", ["300"])[0], 1, 5000, 300)
                offset = _clamp(query.get("offset", ["0"])[0], 0, 100000, 0)
                result = self.store.query(
                    q=query.get("q", [""])[0],
                    discipline=query.get("discipline", [""])[0],
                    tag=query.get("tag", [""])[0],
                    limit=limit,
                    offset=offset,
                )
                self._json(result)
                return
            if path.startswith("/api/entries/"):
                title = path[len("/api/entries/"):]
                self._json({"entry": self.store.get(title)})
                return
            self._json({"error": "接口不存在"}, 404)
        except KBError as exc:
            self._json({"error": str(exc)}, exc.status)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": f"服务器内部错误：{exc}"}, 500)

    def do_POST(self):  # noqa: N802
        path, query = self._parse_path()
        try:
            if not self._guard(query):
                return
            if path == "/api/entries":
                payload = self._body_json()
                data = self._entry_payload(payload)
                entry = self.store.create(
                    title=data["title"],
                    body=data["body"] or "",
                    discipline=data["discipline"],
                    tags=data["tags"],
                )
                self._json({"entry": entry}, 201)
                return
            if path == "/api/quick":
                payload = self._body_json()
                text = str(payload.get("text") or "").strip()
                if not text:
                    raise KBError("内容不能为空")
                entry = self.store.quick_capture(text, discipline=str(payload.get("discipline") or ""))
                self._json({"entry": entry}, 201)
                return
            if path == "/api/ingest":
                self._json(self.store.ingest_inbox())
                return
            if path == "/api/upload":
                self._upload(query)
                return
            if path == "/api/backup":
                destination = self.store.backup()
                self._json({"file": destination.name, "path": str(destination)})
                return
            self._json({"error": "接口不存在"}, 404)
        except KBError as exc:
            self._json({"error": str(exc)}, exc.status)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": f"服务器内部错误：{exc}"}, 500)

    def do_PUT(self):  # noqa: N802
        path, query = self._parse_path()
        try:
            if not self._guard(query):
                return
            if not path.startswith("/api/entries/"):
                self._json({"error": "接口不存在"}, 404)
                return
            old_title = path[len("/api/entries/"):]
            payload = self._body_json()
            kwargs = {}
            if "title" in payload:
                kwargs["title"] = str(payload["title"])
            if "body" in payload:
                kwargs["body"] = str(payload["body"])
            if "discipline" in payload:
                kwargs["discipline"] = str(payload["discipline"])
            if "tags" in payload:
                kwargs["tags"] = payload["tags"]
            entry = self.store.update(old_title, **kwargs)
            self._json({"entry": entry})
        except KBError as exc:
            self._json({"error": str(exc)}, exc.status)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": f"服务器内部错误：{exc}"}, 500)

    def do_DELETE(self):  # noqa: N802
        path, query = self._parse_path()
        try:
            if not self._guard(query):
                return
            if not path.startswith("/api/entries/"):
                self._json({"error": "接口不存在"}, 404)
                return
            title = path[len("/api/entries/"):]
            self._json({"deleted": self.store.delete(title)})
        except KBError as exc:
            self._json({"error": str(exc)}, exc.status)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": f"服务器内部错误：{exc}"}, 500)

    def _upload(self, query) -> None:
        name = (query.get("name") or ["image.png"])[0]
        suffix = Path(name).suffix.lower()
        if suffix not in IMAGE_TYPES:
            raise KBError("只支持 png / jpg / gif / webp / bmp 图片", 415)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            raise KBError("空文件", 400)
        if length > MAX_UPLOAD:
            raise KBError("图片超过 10MB", 413)
        raw = self.rfile.read(length)
        filename = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}{suffix}"
        (self.store.attachments / filename).write_bytes(raw)
        self._json({
            "url": f"/attachments/{filename}",
            "name": filename,
            "markdown": f"![](/attachments/{filename})",
        }, 201)


def _clamp(value, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _lan_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.168.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


class KBHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, store: Store, token: str = ""):
        super().__init__(address, handler)
        self.store = store
        self.token = token


def make_server(store: Store, host: str, port: int, token: str = "") -> KBHTTPServer:
    return KBHTTPServer((host, port), Handler, store, token)


def run_server(store: Store, host: str = "127.0.0.1", port: int = 8765,
               token: str = "", open_browser: bool = True) -> None:
    server = None
    attempts = [port] if port == 0 else list(range(port, port + 10))
    last_error: Exception | None = None
    for candidate in attempts:
        try:
            server = make_server(store, host, candidate, token)
            break
        except OSError as exc:
            last_error = exc
    if server is None:
        raise SystemExit(f"端口 {port}–{port + 9} 都被占用了：{last_error}")

    actual_port = server.server_address[1]
    suffix = f"?token={token}" if token else ""
    local_url = f"http://127.0.0.1:{actual_port}/{suffix}"
    stats = store.stats()
    print("")
    print("  化工学科联络 · 本地知识库")
    print("  " + "─" * 46)
    print(f"  界面地址 : {local_url}")
    print(f"  卡片数量 : {stats['cards']} 张    收件箱 : {stats['inbox']} 个待导入文件")
    print(f"  数据目录 : {store.root}")
    if host not in ("127.0.0.1", "localhost"):
        ip = _lan_ip()
        if ip:
            print(f"  局域网   : http://{ip}:{actual_port}/{suffix}")
    if token:
        print(f"  访问令牌 : {token}")
    print("  " + "─" * 46)
    print("  按 Ctrl+C 停止服务")
    print("", flush=True)

    if open_browser:
        try:
            webbrowser.open(local_url)
        except Exception:  # noqa: BLE001
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止，知识数据都在 vault/ 里，随时可以再启动。")
    finally:
        server.server_close()
