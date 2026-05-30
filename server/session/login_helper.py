import asyncio
import logging
import time
from typing import Optional
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


class LoginSession:
    def __init__(self, account_id: str, url: str):
        self.account_id = account_id
        self.url = url
        self.browser = None
        self.context = None
        self.page = None
        self.captured = False
        self.error: Optional[str] = None
        self.created_at = time.time()

    async def open_browser(self):
        p = await async_playwright().start()
        self.browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=ChromeWhatsNewUI",
            ]
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
        )
        self.page = await self.context.new_page()
        await self.page.goto(self.url, wait_until="domcontentloaded")
        logger.info(f"登录浏览器已打开: {self.url} (account={self.account_id})")

    async def capture(self) -> dict:
        if not self.context:
            raise RuntimeError("浏览器未打开")

        cookies = await self.context.cookies()
        storage = await self.context.storage_state()

        self.captured = True
        return {
            "cookies": cookies,
            "storage": storage.get("origins", []),
        }

    async def close(self):
        try:
            if self.browser:
                await self.browser.close()
        except Exception as e:
            logger.warning(f"关闭浏览器异常: {e}")


class LoginManager:
    def __init__(self):
        self._sessions: dict[str, LoginSession] = {}
        self._capture_events: dict[str, asyncio.Event] = {}

    async def start_login(self, account_id: str, url: str) -> LoginSession:
        session = LoginSession(account_id, url)
        self._sessions[account_id] = session
        self._capture_events[account_id] = asyncio.Event()
        await session.open_browser()
        return session

    def get_session(self, account_id: str) -> Optional[LoginSession]:
        return self._sessions.get(account_id)

    async def wait_for_capture_signal(self, account_id: str, timeout: int = 600) -> bool:
        event = self._capture_events.get(account_id)
        if not event:
            return False
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def signal_capture(self, account_id: str):
        event = self._capture_events.get(account_id)
        if event:
            event.set()

    async def capture_and_close(self, account_id: str) -> dict:
        session = self._sessions.get(account_id)
        if not session:
            raise ValueError(f"登录会话不存在: {account_id}")
        try:
            data = await session.capture()
            return data
        finally:
            await session.close()
            self._sessions.pop(account_id, None)
            self._capture_events.pop(account_id, None)

    def cleanup(self):
        for sid, session in list(self._sessions.items()):
            if session.captured or (time.time() - session.created_at > 3600):
                asyncio.create_task(session.close())
                self._sessions.pop(sid, None)
                self._capture_events.pop(sid, None)
