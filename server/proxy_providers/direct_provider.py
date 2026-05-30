from typing import Optional
from .base import ProxyProvider


class DirectProvider(ProxyProvider):
    @property
    def name(self) -> str:
        return "direct"

    @property
    def description(self) -> str:
        return "直连（无代理，仅测试用）"

    async def start(self):
        pass

    async def stop(self):
        pass

    def get_proxy_url(self) -> Optional[str]:
        return None

    async def check_health(self) -> dict:
        return {"alive": True, "ip": "直连", "mode": "direct", "warning": "无代理，真实 IP 可能暴露"}
