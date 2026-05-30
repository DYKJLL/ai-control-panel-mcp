from abc import ABC, abstractmethod
from typing import Optional


class ProxyProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @abstractmethod
    async def start(self):
        pass

    @abstractmethod
    async def stop(self):
        pass

    @abstractmethod
    async def check_health(self) -> dict:
        pass

    @abstractmethod
    def get_proxy_url(self) -> Optional[str]:
        pass

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description}


class ProxyManager:
    def __init__(self):
        self._providers: dict[str, ProxyProvider] = {}
        self._current: Optional[str] = None

    def register(self, provider: ProxyProvider):
        self._providers[provider.name] = provider

    def list_modes(self) -> list[dict]:
        return [p.to_dict() for p in self._providers.values()]

    async def switch(self, name: str) -> dict:
        if name not in self._providers:
            raise ValueError(f"Unknown proxy mode: {name}")
        if self._current:
            await self._providers[self._current].stop()
        self._current = name
        await self._providers[name].start()
        return {"mode": name, "status": "started"}

    async def health(self) -> dict:
        results = {}
        for name, provider in self._providers.items():
            results[name] = await provider.check_health()
        return {
            "current": self._current,
            "providers": results,
        }

    def get_current_proxy(self) -> Optional[str]:
        if self._current and self._current in self._providers:
            return self._providers[self._current].get_proxy_url()
        return None

    async def test(self, name: str) -> dict:
        if name not in self._providers:
            raise ValueError(f"Unknown proxy mode: {name}")
        return await self._providers[name].check_health()
