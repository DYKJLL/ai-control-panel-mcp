import asyncio
import logging
import os
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


class BrowserController:
    def __init__(self):
        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._current_url: Optional[str] = None
        self._current_account_id: Optional[str] = None

    @property
    def page(self) -> Optional[Page]:
        return self._page

    @property
    def is_open(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    async def open(self, url: str = "", headless: bool = False,
                   cookies: list = None, storage: list = None,
                   viewport: dict = None,
                   account_id: str = "", fingerprint: dict = None,
                   proxy: dict = None, humanize: bool = True) -> dict:
        if self.is_open and account_id and self._current_account_id == account_id:
            if url:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
                self._current_url = url
            return {"status": "already_open", "url": url or self._current_url}

        if self.is_open:
            await self.close()

        if account_id:
            user_data_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "data", "profiles", account_id
            )
            os.makedirs(user_data_dir, exist_ok=True)
            self._current_account_id = account_id
        else:
            user_data_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "data", "profiles", "_default"
            )
            os.makedirs(user_data_dir, exist_ok=True)

        vp = viewport or {"width": 1280, "height": 900}
        proxy_str = None
        if proxy and proxy.get("server"):
            s = proxy["server"]
            if proxy.get("username"):
                proxy_str = f"http://{proxy['username']}:{proxy['password']}@{s}"
            else:
                proxy_str = s

        if launch_persistent_context_async:
            context = await launch_persistent_context_async(
                user_data_dir, headless=headless, proxy=proxy_str,
                viewport=vp, locale="zh-CN", timezone="Asia/Shanghai",
                humanize=humanize,
            )
            self._context = context
        else:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            pw_proxy = proxy if proxy and proxy.get("server") else None
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir, headless=headless, channel="chrome",
                viewport=vp, locale="zh-CN", timezone_id="Asia/Shanghai",
                proxy=pw_proxy,
            )

        if cookies:
            try:
                await self._context.add_cookies(cookies)
            except Exception as e:
                logger.warning(f"Cookie 注入失败: {e}")

        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        self._current_url = url

        if url:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
            for i in range(15):
                has_buttons = await self._page.evaluate("document.querySelectorAll('button').length > 0")
                if has_buttons:
                    break
                await asyncio.sleep(2)

        return {
            "status": "opened", "url": url, "account_id": account_id,
            "cloakbrowser": launch_persistent_context_async is not None,
            "humanize": humanize and _CLOAK_AVAILABLE,
        }

    async def close(self):
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
        self._current_account_id = None

    async def navigate(self, url: str) -> dict:
        if not self.is_open:
            return {"error": "browser not open"}
        return await actions.navigate(self._page, url)

    async def click(self, target: dict) -> dict:
        if not self.is_open:
            return {"error": "browser not open"}
        return await actions.click_target(self._page, target)

    async def type_text(self, text: str, target: dict = None) -> dict:
        if not self.is_open:
            return {"error": "browser not open"}
        return await actions.type_text(self._page, text, target=target)

    async def press_key(self, key: str) -> dict:
        if not self.is_open:
            return {"error": "browser not open"}
        return await actions.press_key(self._page, key)

    async def wait(self, seconds: float = 2) -> dict:
        await asyncio.sleep(seconds)
        return {"status": "waited", "seconds": seconds}

    async def screenshot(self, path: str = None) -> dict:
        if not self.is_open:
            return {"error": "browser not open"}
        return await actions.screenshot(self._page, path)

    async def generate_image(self, prompt: str, output_dir: str = "output") -> dict:
        if not self.is_open:
            return {"error": "browser not open"}
        return await actions.generate_image(self._page, prompt, output_dir)

    async def ask_vision(self, image_source: str, question: str, output_dir: str = "output") -> dict:
        if not self.is_open:
            return {"error": "browser not open"}
        return await actions.ask_vision(self._page, image_source, question, output_dir)
