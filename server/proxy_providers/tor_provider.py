import asyncio
import aiohttp
from typing import Optional
from .base import ProxyProvider


class TorProvider(ProxyProvider):
    def __init__(self, socks_host: str = "127.0.0.1", socks_port: int = 9050, control_port: int = 9051):
        self._host = socks_host
        self._port = socks_port
        self._control_port = control_port
        self._alive = False
        self._last_check: Optional[str] = None

    @property
    def name(self) -> str:
        return "tor"

    @property
    def description(self) -> str:
        return "Tor 匿名网络 (SOCKS5 代理)"

    async def start(self):
        alive = await self.check_health()
        self._alive = alive.get("alive", False)

    async def stop(self):
        self._alive = False

    def get_proxy_url(self) -> Optional[str]:
        return f"socks5://{self._host}:{self._port}"

    async def check_health(self) -> dict:
        proxy_url = self.get_proxy_url()
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    "https://check.torproject.org/api/ip",
                    proxy=proxy_url,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._alive = True
                        self._last_check = data.get("IP", "unknown")
                        return {"alive": True, "ip": self._last_check, "mode": "tor"}
                    self._alive = False
                    return {"alive": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            self._alive = False
            return {"alive": False, "error": str(e), "mode": "tor"}
