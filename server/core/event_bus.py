import asyncio
from typing import Any, Callable
from datetime import datetime


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
        self._history: list[dict] = []
        self._max_history = 500

    def subscribe(self, event_type: str, handler: Callable):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable):
        if event_type in self._subscribers:
            self._subscribers[event_type] = [h for h in self._subscribers[event_type] if h != handler]

    async def emit(self, event_type: str, data: Any = None):
        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        handlers = self._subscribers.get(event_type, []) + self._subscribers.get("*", [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                print(f"[EventBus] handler error: {e}")

    async def emit_state_change(self, state: dict):
        await self.emit("state_change", state)

    def get_history(self, last_n: int = 50) -> list[dict]:
        return self._history[-last_n:]

    def get_subscribers(self) -> dict:
        return {k: len(v) for k, v in self._subscribers.items()}
