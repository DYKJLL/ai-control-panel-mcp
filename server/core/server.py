import json
import logging
from pathlib import Path
from typing import Any, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from .registry import get_registry, FunctionRegistry
from .event_bus import EventBus
from .task_queue import TaskQueue

logger = logging.getLogger(__name__)


class AppServer:
    def __init__(self, registry: FunctionRegistry = None, event_bus: EventBus = None,
                 task_queue: TaskQueue = None, account_manager=None, login_manager=None,
                 fingerprint_manager=None, browser_manager=None):
        self.registry = registry or get_registry()
        self.event_bus = event_bus or EventBus()
        self.task_queue = task_queue
        self.account_manager = account_manager
        self.login_manager = login_manager
        self.fingerprint_manager = fingerprint_manager
        self.browser_manager = browser_manager
        self.app = FastAPI(title="AI Control Panel")
        self._websockets: list[WebSocket] = []
        self._host_ip = self._detect_host_ip()
        self._setup_routes()

    @staticmethod
    def _detect_host_ip() -> str:
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.254.254.254", 1))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _setup_routes(self):
        app = self.app

        # ── CORS ──
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # ── 静态文件 ──
        static_dir = Path(__file__).parent.parent / "web" / "dashboard"
        if static_dir.exists():
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        # ── 函数元信息 ──
        @app.get("/api/functions")
        async def list_functions():
            return {"functions": self.registry.list_dicts()}

        @app.get("/api/functions/schemas")
        async def list_schemas():
            return {"functions": self.registry.list_schemas()}

        # ── 函数调用（POST + GET） ──
        @app.post("/api/call/{name}")
        async def call_function_post(name: str, body: dict = None):
            return await self._do_call(name, body or {})

        @app.get("/api/call/{name}")
        async def call_function_get(name: str, body: Optional[str] = Query(None)):
            params = json.loads(body) if body else {}
            return await self._do_call(name, params)

        # ── 队列 ──
        @app.get("/api/queue/status")
        async def queue_status():
            if self.task_queue:
                return self.task_queue.get_status()
            return {"error": "queue not initialized"}

        @app.get("/api/queue/batch/{batch_id}")
        async def batch_status(batch_id: str):
            if self.task_queue:
                batch = self.task_queue.get_batch(batch_id)
                if batch:
                    return batch.status
                return {"error": "batch not found"}
            return {"error": "queue not initialized"}

        @app.post("/api/queue/cancel/{batch_id}")
        async def cancel_batch(batch_id: str):
            if self.task_queue:
                self.task_queue.cancel_batch(batch_id)
                return {"success": True}
            return {"error": "queue not initialized"}

        # ── 账号登录 ──
        @app.post("/api/account/start-login")
        async def start_login(body: dict):
            if not self.account_manager or not self.login_manager:
                return {"success": False, "error": "登录模块未初始化"}
            service = body.get("service", "custom")
            label = body.get("label", "")
            url = body.get("url", "")
            if not url:
                return {"success": False, "error": "请输入网站地址"}
            account = self.account_manager.add_account(service, label, url=url)
            account.status = "logging_in"
            logger.info(f"启动登录: service={service} url={url} account_id={account.id}")
            import asyncio
            asyncio.create_task(self.login_manager.start_login(account.id, url))
            return {"success": True, "account_id": account.id, "message": "浏览器已打开，请在浏览器中登录"}

        @app.get("/api/account/login-status/{account_id}")
        async def login_status(account_id: str):
            if not self.account_manager:
                return {"status": "error", "error": "未初始化"}
            account = self.account_manager.get_account(account_id)
            if not account:
                return {"status": "not_found"}
            session = self.login_manager.get_session(account_id) if self.login_manager else None
            browser_open = session is not None
            return {"status": account.status, "browser_open": browser_open, "account": account.to_dict()}

        @app.post("/api/account/capture-login")
        async def capture_login(body: dict):
            if not self.account_manager or not self.login_manager:
                return {"success": False, "error": "登录模块未初始化"}
            account_id = body.get("account_id", "")
            account = self.account_manager.get_account(account_id)
            if not account:
                return {"success": False, "error": "账号不存在"}
            try:
                data = await self.login_manager.capture_and_close(account_id)
                self.account_manager.update_cookies(account_id, data["cookies"], data["storage"])
                logger.info(f"登录捕获成功: {account_id}")
                await self.event_bus.emit("login_complete", {"account_id": account_id, "service": account.service})
                return {"success": True, "message": "登录信息已保存"}
            except Exception as e:
                logger.exception(f"捕获登录失败: {account_id}")
                return {"success": False, "error": str(e)}

        @app.post("/api/account/cancel-login")
        async def cancel_login(body: dict):
            account_id = body.get("account_id", "")
            if self.login_manager:
                try:
                    await self.login_manager.capture_and_close(account_id)
                except Exception:
                    pass
            if self.account_manager:
                self.account_manager.remove_account(account_id)
            return {"success": True}

        @app.post("/api/account/delete")
        async def delete_account(body: dict):
            if not self.account_manager:
                return {"success": False, "error": "未初始化"}
            account_id = body.get("account_id", "")
            if self.login_manager:
                try:
                    await self.login_manager.capture_and_close(account_id)
                except Exception:
                    pass
            self.account_manager.remove_account(account_id)
            await self.event_bus.emit("account_deleted", {"account_id": account_id})
            return {"success": True, "message": "账号已删除"}

        @app.post("/api/account/open-browser")
        async def open_account_browser(body: dict):
            if not self.account_manager:
                return {"success": False, "error": "未初始化"}
            account_id = body.get("account_id", "")
            account = self.account_manager.get_account(account_id)
            if not account:
                return {"success": False, "error": "账号不存在"}
            url = account.url
            if not url and account.cookies:
                domain = account.cookies[0].get("domain", "")
                if domain:
                    url = f"https://{domain.lstrip('.')}"
            if not url:
                return {"success": False, "error": "该账号没有保存访问地址"}
            if not account.cookies:
                return {"success": False, "error": "该账号没有登录凭证，请先登录"}
            # 存回 account，下次直接用
            if not account.url and url:
                account.url = url
                self.account_manager.save()
            try:
                result = await self.registry.call("browser_open",
                    url=url,
                    account_id=account.id,
                    headless=False,
                )
                account.add_login_record(True, url=account.url, note="manual_open")
                self.account_manager.save()
                return {"success": True, "result": result}
            except Exception as e:
                logger.exception(f"打开账号页面失败: {account_id}")
                account.add_login_record(False, url=account.url, note=str(e))
                return {"success": False, "error": str(e)}

        # ── 批量生成 ──
        @app.post("/api/batch/generate-images")
        async def batch_generate_images(body: dict):
            if not self.browser_manager:
                return {"success": False, "error": "browser manager not initialized"}
            tasks = body.get("tasks", [])
            max_concurrency = body.get("max_concurrency", 3)
            headless = body.get("headless", True)
            output_dir = body.get("output_dir", "output")
            if not tasks:
                return {"success": False, "error": "tasks is empty"}
            results = await self.browser_manager.execute_batch(
                tasks, max_concurrency=max_concurrency,
                headless=headless, output_dir=output_dir,
            )
            succeeded = sum(1 for r in results if r.get("success"))
            failed = sum(1 for r in results if not r.get("success"))
            return {
                "success": True,
                "total": len(results),
                "succeeded": succeeded,
                "failed": failed,
                "results": results,
            }

        @app.get("/api/browser-pool/stats")
        async def browser_pool_stats():
            if not self.browser_manager:
                return {"error": "browser manager not initialized"}
            return self.browser_manager.get_stats()

        # ── 系统 ──
        @app.get("/api/ping")
        async def ping():
            return {"pong": True, "base_url": f"http://{self._host_ip}:1984"}

        @app.get("/api/system/state")
        async def system_state():
            state = {"proxy": {}, "queue": {}, "accounts": []}
            if self.task_queue:
                state["queue"] = self.task_queue.get_status()
            if self.account_manager:
                state["accounts"] = self.account_manager.list_accounts()
            return state

        # ── AI 摘要（另一个 AI 通过此链接获取最新工具定义和状态） ──
        # 每次代码/工具更新后，此端点内容自动同步。
        # 另一个 AI 通过比较 version_hash 判断是否有更新。
        @app.get("/api/ai-summary")
        async def ai_summary():
            import hashlib
            import json as _json
            import os
            base_dir = Path(__file__).parent.parent
            vision_dir_path = base_dir / "data" / "vision_dir.json"
            vision_dir = ""
            if vision_dir_path.exists():
                try:
                    vd = _json.loads(vision_dir_path.read_text(encoding="utf-8"))
                    vision_dir = vd.get("default", "")
                except Exception:
                    pass
            host_ip = self._host_ip
            tools = self.registry.list_dicts()
            accounts = self.account_manager.list_accounts() if self.account_manager else []
            payload = {
                "server": {
                    "title": "AI Control Panel",
                    "base_url": f"http://{host_ip}:1984",
                    "local_url": "http://127.0.0.1:1984",
                    "summary_url": f"http://{host_ip}:1984/api/ai-summary",
                    "api_prefix": "/api",
                    "docs": f"http://{host_ip}:1984/docs",
                    "note": "WSL 或其他设备请用 base_url（局域网 IP），Windows 本机可用 local_url",
                },
                "calling_convention": {
                    "method": "POST",
                    "endpoint_template": "{base_url}/api/call/{tool_name}",
                    "request_body": "直接传工具参数（非嵌套），例如 {\"prompt\": \"a cat\", \"account_id\": \"acc_xxx\"}",
                    "response_format": '{"success": true, "result": {...}} 或 {"success": false, "error": "错误信息"}',
                    "example_call": {
                        "url": "http://192.168.0.102:1984/api/call/browser_generate_image",
                        "body": '{"prompt": "a cute cat", "account_id": "acc_577cd0d2", "output_dir": "output"}',
                        "method": "POST",
                    },
                },
                "tools": tools,
                "vision": {
                    "configured": bool(vision_dir),
                    "storage_dir": vision_dir or "",
                    "doc_url": f"http://{host_ip}:1984/vision_api",
                    "usage_note": "先调用 set_vision_dir 设置存储目录，再调用 browser_ask_vision",
                },
                "batch_generate": {
                    "endpoint": "/api/batch/generate-images",
                    "method": "POST",
                    "body": {
                        "tasks": [{"prompt": "描述文字", "account_id": "acc_xxx", "output_dir": "output"}],
                        "max_concurrency": 3,
                        "headless": True,
                    },
                },
                "accounts": accounts,
                "browser_pool_stats": self.browser_manager.get_stats() if self.browser_manager else {},
                "update_protocol": {
                    "summary_url": f"http://{host_ip}:1984/api/ai-summary",
                    "version_hash": "每次 tools/accounts 变化时更新",
                    "detection": "对比 version_hash，不同则重新加载整个 JSON",
                },
                "critical_rules": [
                    "browser_generate_image: 同一账号反复调用时不刷新页面，保留聊天上下文。如需同角色一致性生图，请连续调用同一 account_id",
                    "browser_ask_vision: 你是文本模型，不用读取图片内容。直接把 image_source 字符串传给工具，豆包会看图回答",
                ],
            }
            # 版本哈希：计算 tools+accounts 的摘要，变化时 hash 变化
            raw = _json.dumps({"t": tools, "a": accounts, "v": vision_dir}, sort_keys=True, ensure_ascii=False)
            payload["version_hash"] = hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]
            return payload

        # ── WebSocket ──
        @app.websocket("/ws")
        async def websocket_endpoint(ws: WebSocket):
            await ws.accept()
            self._websockets.append(ws)
            try:
                while True:
                    data = await ws.receive_text()
                    msg = json.loads(data)
                    action = msg.get("action")
                    if action == "call":
                        name = msg.get("name")
                        params = msg.get("params", {})
                        result = await self.registry.call(name, **params)
                        await ws.send_json({"type": "result", "name": name, "result": result})
                    elif action == "ping":
                        await ws.send_json({"type": "pong"})
            except WebSocketDisconnect:
                self._websockets.remove(ws)
            except Exception:
                if ws in self._websockets:
                    self._websockets.remove(ws)

        # ── 首页 ──
        @app.get("/")
        async def dashboard():
            html_path = Path(__file__).parent.parent / "web" / "dashboard" / "index.html"
            if html_path.exists():
                return HTMLResponse(html_path.read_text(encoding="utf-8"))
            return HTMLResponse("<h1>AI Control Panel</h1><p>Dashboard not found.</p>")

        @app.get("/vision_api")
        async def vision_api_doc():
            doc_path = Path(__file__).parent.parent / "mcp_vision" / "VISION_API.md"
            if doc_path.exists():
                return Response(content=doc_path.read_text(encoding="utf-8"),
                               media_type="text/plain; charset=utf-8")
            return Response(content="# 图片理解工具说明\n文件未找到", media_type="text/plain")

        @app.get("/vision_api/mcp_server.py")
        async def vision_api_mcp():
            mcp_path = Path(__file__).parent.parent / "mcp_vision" / "mcp_server.py"
            if mcp_path.exists():
                return Response(content=mcp_path.read_text(encoding="utf-8"),
                               media_type="text/plain; charset=utf-8")
            return Response(content="# MCP Server\n文件未找到", media_type="text/plain")

    async def _do_call(self, name: str, params: dict) -> dict:
        try:
            result = await self.registry.call(name, **params)
            return {"success": True, "result": result}
        except Exception as e:
            logger.exception(f"Call {name} failed")
            return {"success": False, "error": str(e)}

    async def broadcast(self, event: dict):
        dead = []
        for ws in self._websockets:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._websockets.remove(ws)

    async def start_event_listener(self):
        async def on_event(event: dict):
            await self.broadcast(event)
        self.event_bus.subscribe("*", on_event)

    async def start(self, host: str = "0.0.0.0", port: int = 1984):
        import uvicorn.config
        config = uvicorn.config.Config(self.app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
