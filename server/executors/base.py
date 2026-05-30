from abc import ABC, abstractmethod
from typing import Any


class BaseExecutor(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @abstractmethod
    async def execute(self, params: dict) -> Any:
        pass

    async def validate(self, params: dict) -> tuple[bool, str]:
        return True, ""

    def to_tool_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}, "required": []},
            }
        }
