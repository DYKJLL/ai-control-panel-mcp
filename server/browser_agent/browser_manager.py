import asyncio
import logging
import os
import subprocess
import time
from typing import Optional

from playwright.async_api import BrowserContext, Page

from . import actions

logger = logging.getLogger(__name__)

_CLOAK_AVAILABLE = False
try:
    from cloakbrowser import launch_persistent_context_async
    _CLOAK_AVAILABLE = True
except ImportError:
    launch_persistent_context_async = None


class ManagedBrowser:
    """一个受管理的独立浏览器实例，与一个账号绑定"""

    def __init__(self, account_id: str):
        self.account_id = account_id
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._playwright = None
        self.created_at: float = 0
        self.last_used_at: float = 0
        self.status: str = "idle"  # idle | busy | crashed
        self._lock = asyncio.Lock()

    @property
    def page(self) -> Optional[Page]:
        return self._page

    @property
    def is_open(self) -> bool:
        try:
            return self._page is not None and not self._page.is_closed()
        except Exception:
            return False

    @property
    def idle_seconds(self) -> float:
        if self.last_used_at <= 0:
            return 0
        return time.time() - self.last_used_at

    async def launch(self, user_data_dir: str, url: str = "", headless: bool = False,
                     cookies: list = None, viewport: dict = None,
                     proxy: dict = None, humanize: bool = True) -> dict:
        if self.is_open:
            if url:
                async with self._lock:
                    await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
                self.last_used_at = time.time()
            return {"status": "already_open", "url": url}

        os.makedirs(user_data_dir, exist_ok=True)
        vp = viewport or {"width": 1280, "height": 900}

        proxy_str = None
        if proxy and proxy.get("server"):
            s = proxy["server"]
            if proxy.get("username"):
                proxy_str = f"http://{proxy['username']}:{proxy['password']}@{s}"
            else:
                proxy_str = s

        # 清理残留的 Chromium 僵尸进程（它们会锁住 profile 导致无法重新启动）
        try:
            _acct_id = self.account_id
            _ps_cmd = ('Get-CimInstance Win32_Process -Filter "name=\'chrome.exe\'" | '
                       "Where-Object { $_.CommandLine.Contains('" + _acct_id + "') } | "
                       'ForEach-Object { Write-Output $_.ProcessId }')
            _zombie_out = subprocess.check_output(['powershell', '-Command', _ps_cmd], timeout=15, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            _zombie_pids = _zombie_out.decode('utf-8', errors='replace').strip().split()
            for _zpid in _zombie_pids:
                try:
                    subprocess.run(['taskkill', '/F', '/PID', _zpid], timeout=5, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                except Exception:
                    pass
        except Exception:
            pass

        # 清理残留锁文件和可能的损坏数据
        for f in ("SingletonLock", "SingletonSocket", "SingletonCookie", "First Run", "Last Version", "lockfile"):
            p = os.path.join(user_data_dir, f)
            if os.path.exists(p):
                try:
                    if os.path.isdir(p):
                        import shutil
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        os.remove(p)
                except OSError:
                    pass
        # 清理 GPU/Shader 缓存（GTX 1650 4GB 容易触发 GPU 崩溃）
        for cache_dir in ("GPUCache", "ShaderCache", "GrShaderCache"):
            p = os.path.join(user_data_dir, cache_dir)
            if os.path.exists(p):
                try:
                    import shutil
                    shutil.rmtree(p, ignore_errors=True)
                except OSError:
                    pass

        self._proxy_disabled = False
        last_error = None

        # 临时关闭 Windows 系统代理，避免 Chromium 走代理连不上（适用于 direct 模式）
        import winreg
        _orig_proxy_enabled = None
        _proxy_restored = False

        def _disable_sys_proxy():
            nonlocal _orig_proxy_enabled
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                     r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", 0,
                                     winreg.KEY_READ | winreg.KEY_WRITE)
                try:
                    _orig_proxy_enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
                except FileNotFoundError:
                    _orig_proxy_enabled = None
                winreg.CloseKey(key)
                self._proxy_disabled = True
            except Exception:
                pass

        def _restore_sys_proxy():
            nonlocal _proxy_restored, _orig_proxy_enabled
            if _proxy_restored:
                return
            _proxy_restored = True
            if _orig_proxy_enabled is None:
                self._proxy_disabled = False
                return
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                     r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", 0,
                                     winreg.KEY_WRITE)
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, _orig_proxy_enabled)
                winreg.CloseKey(key)
                self._proxy_disabled = False
            except Exception:
                pass

        # 如果是直连模式，禁用系统代理
        if not proxy or not proxy.get("server"):
            _disable_sys_proxy()

        launch_attempts = [
            ("CloakBrowser", _CLOAK_AVAILABLE and launch_persistent_context_async),
            ("Playwright", True),
        ]

        for attempt_name, should_attempt in launch_attempts:
            if not should_attempt:
                continue
            try:
                if attempt_name == "CloakBrowser":
                    self._context = await launch_persistent_context_async(
                        user_data_dir, headless=headless, proxy=proxy_str,
                        viewport=vp, locale="zh-CN", timezone="Asia/Shanghai",
                        humanize=humanize,
                    )
                else:
                    from playwright.async_api import async_playwright
                    self._playwright = await async_playwright().start()
                    pw_proxy = proxy if proxy and proxy.get("server") else None
                    # 使用 bundled Chromium（而非 system Chrome）以保证兼容性
                    # GTX 1650 4GB 显存不足时使用软件渲染
                    # 注意：保留 SwiftShader 软件渲染，不添加 --disable-software-rasterizer
                    # 否则 headless 模式无法渲染 Canvas/WebGL（千问生图需要）
                    chromium_args = [
                        "--disable-gpu",
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-field-trial-config",
                        "--disable-dev-shm-usage",
                        "--proxy-server=direct://",
                        "--proxy-bypass-list=*",
                    ]
                    try:
                        self._context = await self._playwright.chromium.launch_persistent_context(
                            user_data_dir, headless=headless,
                            args=chromium_args,
                            viewport=vp, locale="zh-CN", timezone_id="Asia/Shanghai",
                            proxy=pw_proxy,
                        )
                    except Exception as gpu_err:
                        logger.warning(f"[{self.account_id}] Chromium with GPU disabled failed: {gpu_err}，尝试无 GPU 模式")
                        # 彻底禁用 GPU 重试
                        chromium_args.extend(["--disable-gpu-compositing", "--disable-gpu-rasterization", "--disable-gpu-sandbox", "--disable-gpu-program-cache", "--disable-gpu-shader-disk-cache", "--enable-unsafe-swiftshader", "--proxy-server=direct://"])
                        self._context = await self._playwright.chromium.launch_persistent_context(
                            user_data_dir, headless=headless,
                            args=chromium_args,
                            viewport=vp, locale="zh-CN", timezone_id="Asia/Shanghai",
                            proxy=pw_proxy,
                        )
                logger.info(f"[{self.account_id}] {attempt_name} launched")
                last_error = None
                # 代理在浏览器关闭前不恢复（浏览器存活期间保持直连）
                # 注意：这意味着 Windows 代理在浏览器运行时是禁用的
                break
            except Exception as e:
                _restore_sys_proxy()
                last_error = e
                logger.warning(f"[{self.account_id}] {attempt_name} launch failed: {e}，尝试下一方案")
                # 清理残留上下文
                if hasattr(self, '_context') and self._context:
                    try: await self._context.close()
                    except Exception: pass
                    self._context = None
                if hasattr(self, '_playwright') and self._playwright:
                    try: await self._playwright.stop()
                    except Exception: pass
                    self._playwright = None
                self._page = None

        if last_error:
            _restore_sys_proxy()
            self.status = "crashed"
            logger.error(f"[{self.account_id}] All browser launch attempts failed")
            return {"error": f"browser launch failed: {last_error}"}

        if cookies:
            try:
                await self._context.add_cookies(cookies)
            except Exception as e:
                logger.warning(f"[{self.account_id}] Cookie注入失败: {e}")

        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        self.created_at = time.time()
        self.last_used_at = time.time()
        self.status = "idle"

        if url:
            await self._page.goto(url, wait_until="load", timeout=60000)
            for i in range(30):
                has_input = await self._page.evaluate("!!document.querySelector('textarea') || !!document.querySelector('[contenteditable=true]')")
                if has_input:
                    break
                await asyncio.sleep(2)

        return {"status": "opened", "url": url, "account_id": self.account_id}

    async def close(self):
        self.status = "crashed"
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._context = None
        self._page = None
        self._playwright = None
        # 恢复 Windows 系统代理
        if self._proxy_disabled:
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                     r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", 0,
                                     winreg.KEY_WRITE)
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                winreg.CloseKey(key)
            except Exception:
                pass
            self._proxy_disabled = False
        logger.info(f"[{self.account_id}] Browser closed")

    # ─── 操作委托 ───

    async def navigate(self, url: str) -> dict:
        if not self.is_open:
            return {"error": "browser not open"}
        async with self._lock:
            result = await actions.navigate(self._page, url)
        self.last_used_at = time.time()
        return result

    async def click(self, target: dict) -> dict:
        if not self.is_open:
            return {"error": "browser not open"}
        async with self._lock:
            result = await actions.click_target(self._page, target)
        self.last_used_at = time.time()
        return result

    async def type_text(self, text: str, target: dict = None) -> dict:
        if not self.is_open:
            return {"error": "browser not open"}
        async with self._lock:
            result = await actions.type_text(self._page, text, target=target)
        self.last_used_at = time.time()
        return result

    async def press_key(self, key: str) -> dict:
        if not self.is_open:
            return {"error": "browser not open"}
        async with self._lock:
            result = await actions.press_key(self._page, key)
        self.last_used_at = time.time()
        return result

    async def wait(self, seconds: float = 2) -> dict:
        if self._page:
            await self._page.wait_for_timeout(int(seconds * 1000))
        else:
            await asyncio.sleep(seconds)
        self.last_used_at = time.time()
        return {"status": "waited", "seconds": seconds}

    async def screenshot(self, path: str = None) -> dict:
        if not self.is_open:
            return {"error": "browser not open"}
        async with self._lock:
            result = await actions.screenshot(self._page, path)
        self.last_used_at = time.time()
        return result

    async def generate_image(self, prompt: str, output_dir: str = "output") -> dict:
        if not self.is_open:
            return {"error": "browser not open"}
        async with self._lock:
            result = await actions.generate_image(self._page, prompt, output_dir)
        self.last_used_at = time.time()
        return result

    async def ask_vision(self, image_source: str, question: str, output_dir: str = "output") -> dict:
        if not self.is_open:
            return {"error": "browser not open"}
        async with self._lock:
            result = await actions.ask_vision(self._page, image_source, question, output_dir)
        self.last_used_at = time.time()
        return result

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "status": self.status,
            "is_open": self.is_open,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "idle_seconds": round(self.idle_seconds, 1),
            "age_seconds": round(time.time() - self.created_at, 1) if self.created_at > 0 else 0,
        }


class BrowserManager:
    """多实例浏览器管理器：池化 + 看门狗 + 预热"""

    def __init__(self, max_instances: int = 5, idle_timeout: int = 600, account_manager=None, proxy_manager=None):
        self._instances: dict[str, ManagedBrowser] = {}
        self._max = max_instances
        self._idle_timeout = idle_timeout
        self._lock = asyncio.Lock()
        self._watchdog_task: Optional[asyncio.Task] = None
        self.account_manager = account_manager
        self.proxy_manager = proxy_manager

    # ─── 实例获取/释放 ───

    async def acquire(self, account_id: str, url: str = "",
                      headless: bool = False, humanize: bool = True) -> ManagedBrowser:
        """获取一个账号的浏览器实例（存在则返回，不存在则创建）"""
        need_launch = False
        mb = None

        async with self._lock:
            if account_id in self._instances:
                mb = self._instances[account_id]
                if mb.is_open:
                    mb.status = "busy"
                else:
                    logger.info(f"[{account_id}] 实例已关闭，重建")
                    del self._instances[account_id]
                    mb = ManagedBrowser(account_id)
                    self._instances[account_id] = mb
                    need_launch = True
            else:
                if len(self._instances) >= self._max:
                    self._evict_one()
                mb = ManagedBrowser(account_id)
                self._instances[account_id] = mb
                need_launch = True

        if need_launch:
            user_data_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "data", "profiles", account_id
            )
            cookies = None
            proxy = None
            if self.account_manager:
                acc = self.account_manager.get_account(account_id)
                if acc:
                    cookies = acc.cookies
                    if acc.proxy_mode and acc.proxy_mode != "direct" and self.proxy_manager:
                        provider = self.proxy_manager._providers.get(acc.proxy_mode)
                        if provider and provider.get_proxy_url():
                            proxy = {"server": provider.get_proxy_url()}

            result = await mb.launch(user_data_dir, url=url, headless=headless,
                                     cookies=cookies, proxy=proxy, humanize=humanize)
            if isinstance(result, dict) and "error" in result:
                async with self._lock:
                    self._instances.pop(account_id, None)
                raise RuntimeError(result["error"])

        mb.status = "busy"
        return mb

    async def release(self, account_id: str):
        """归还实例到空闲池"""
        async with self._lock:
            mb = self._instances.get(account_id)
            if mb:
                mb.status = "idle"
                mb.last_used_at = time.time()

    async def close(self, account_id: str):
        """关闭指定账号的浏览器"""
        async with self._lock:
            mb = self._instances.pop(account_id, None)
        if mb:
            await mb.close()

    async def close_all(self):
        """关闭所有浏览器"""
        async with self._lock:
            mb_list = list(self._instances.values())
            self._instances.clear()
        for mb in mb_list:
            await mb.close()
        logger.info(f"已关闭 {len(mb_list)} 个浏览器实例")

    # ─── 看门狗 ───

    async def start_watchdog(self, interval: int = 30):
        """启动看门狗协程：定期检查健康 + 回收空闲实例"""
        if self._watchdog_task:
            self._watchdog_task.cancel()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop(interval))

    async def _watchdog_loop(self, interval: int):
        while True:
            try:
                await self._check_health()
                await self._reclaim_idle()
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
            await asyncio.sleep(interval)

    async def _check_health(self):
        async with self._lock:
            crashed = []
            for aid, mb in self._instances.items():
                if mb.status == "crashed" or (mb.status != "crashed" and not mb.is_open):
                    crashed.append(aid)
        for aid in crashed:
            logger.warning(f"[{aid}] 浏览器无响应，关闭")
            await self.close(aid)

    async def _reclaim_idle(self):
        now = time.time()
        reclaim = []
        async with self._lock:
            for aid, mb in self._instances.items():
                if mb.status == "idle" and mb.idle_seconds > self._idle_timeout:
                    reclaim.append(aid)
        for aid in reclaim:
            logger.info(f"[{aid}] 空闲超时({self._idle_timeout}s)，回收")
            await self.close(aid)

    def _evict_one(self):
        """驱逐一个最久未使用的空闲实例"""
        best = None
        for aid, mb in self._instances.items():
            if mb.status == "idle":
                if best is None or mb.last_used_at < self._instances[best].last_used_at:
                    best = aid
        if best:
            mb = self._instances.pop(best, None)
            if mb:
                logger.info(f"[{best}] 驱逐以腾出空间")
                asyncio.create_task(mb.close())
        else:
            logger.warning("达到最大实例数且无空闲实例可驱逐")
            raise RuntimeError(f"已达到最大浏览器实例数 ({self._max})，且所有实例忙碌中")

    # ─── 批量执行 ───

    async def execute_batch(self, tasks: list[dict], max_concurrency: int = 3,
                            headless: bool = True, output_dir: str = "output") -> list[dict]:
        results = []
        sem = asyncio.Semaphore(max_concurrency)

        async def run_one(task: dict) -> dict:
            aid = task.get("account_id", "")
            prompt = task.get("prompt", "")
            async with sem:
                mb = None
                try:
                    # 使用账号实际 URL
                    _task_url = task.get("url", "")
                    if not _task_url and self.account_manager:
                        _acc = self.account_manager.get_account(aid)
                        if _acc:
                            _task_url = _acc.url
                    mb = await self.acquire(aid, url=_task_url,
                                            headless=headless, humanize=True)
                    result = await mb.generate_image(prompt, output_dir)
                    await self.release(aid)
                    return {"account_id": aid, "prompt": prompt[:30], "success": True, "result": result}
                except Exception as e:
                    logger.error(f"[{aid}] batch task failed: {e}")
                    if mb:
                        await self.close(aid)
                    return {"account_id": aid, "prompt": prompt[:30], "success": False, "error": str(e)}

        coros = [run_one(t) for t in tasks]
        for coro in asyncio.as_completed(coros):
            results.append(await coro)
        return results

    def get_instance(self, account_id: str) -> Optional[ManagedBrowser]:
        """获取指定账号的浏览器实例（不启动，不存在返回 None）"""
        return self._instances.get(account_id)

    # ─── 查询 ───

    def get_stats(self) -> dict:
        instances = []
        idle_count = 0
        busy_count = 0
        for aid, mb in list(self._instances.items()):
            d = mb.to_dict()
            instances.append(d)
            if d["status"] == "idle":
                idle_count += 1
            elif d["status"] == "busy":
                busy_count += 1
        return {
            "max_instances": self._max,
            "current_count": len(self._instances),
            "idle": idle_count,
            "busy": busy_count,
            "idle_timeout": self._idle_timeout,
            "instances": instances,
        }
