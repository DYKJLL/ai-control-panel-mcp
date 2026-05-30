import aiohttp
from typing import Optional
from .base import ProxyProvider


class WorkersProvider(ProxyProvider):
    def __init__(self, workers_url: str = ""):
        self._workers_url = workers_url
        self._alive = False
        self._last_ip: Optional[str] = None

    @property
    def name(self) -> str:
        return "workers"

    @property
    def description(self) -> str:
        return "Cloudflare Workers (HTTP 中转)"

    async def start(self):
        await self.check_health()

    async def stop(self):
        self._alive = False

    def set_url(self, url: str):
        self._workers_url = url

    def get_proxy_url(self) -> Optional[str]:
        if self._workers_url:
            return self._workers_url
        return None

    async def check_health(self) -> dict:
        if not self._workers_url:
            return {"alive": False, "error": "Workers URL 未配置", "mode": "workers"}
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                test_url = f"{self._workers_url}?target=https://httpbin.org/ip"
                async with session.get(test_url) as resp:
                    if resp.status == 200:
                        self._alive = True
                        data = await resp.json()
                        self._last_ip = data.get("origin", "unknown")
                        return {"alive": True, "ip": self._last_ip, "mode": "workers"}
                    self._alive = False
                    return {"alive": False, "error": f"HTTP {resp.status}", "mode": "workers"}
        except Exception as e:
            self._alive = False
            return {"alive": False, "error": str(e), "mode": "workers"}
