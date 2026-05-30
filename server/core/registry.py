import inspect
import json
from typing import Any, Callable, Optional
from datetime import datetime


class ToolFunction:
    def __init__(self, name: str, description: str, handler: Callable, parameters: dict):
        self.name = name
        self.description = description
        self.handler = handler
        self.parameters = parameters
        self.created_at = datetime.now()

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    async def call(self, **kwargs) -> Any:
        if inspect.iscoroutinefunction(self.handler):
            return await self.handler(**kwargs)
        return self.handler(**kwargs)


class FunctionRegistry:
    def __init__(self):
        self._functions: dict[str, ToolFunction] = {}

    def register(self, name: str = None, description: str = None, parameters: dict = None):
        def decorator(handler: Callable):
            fn_name = name or handler.__name__
            fn_desc = description or handler.__doc__ or ""
            fn_params = parameters or self._infer_params(handler)
            self._functions[fn_name] = ToolFunction(fn_name, fn_desc, handler, fn_params)
            return handler
        return decorator

    def get(self, name: str) -> Optional[ToolFunction]:
        return self._functions.get(name)

    def all(self) -> list[ToolFunction]:
        return list(self._functions.values())

    def list_schemas(self) -> list[dict]:
        return [f.to_openai_schema() for f in self._functions.values()]

    def list_dicts(self) -> list[dict]:
        return [f.to_dict() for f in self._functions.values()]

    async def call(self, name: str, **kwargs) -> Any:
        fn = self.get(name)
        if not fn:
            raise ValueError(f"Unknown function: {name}")
        return await fn.call(**kwargs)

    def _infer_params(self, handler: Callable) -> dict:
        sig = inspect.signature(handler)
        properties = {}
        required = []
        for p_name, p_param in sig.parameters.items():
            if p_name == "self":
                continue
            param_type = "string"
            if p_param.annotation != inspect.Parameter.empty:
                type_map = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}
                param_type = type_map.get(p_param.annotation, "string")
            properties[p_name] = {"type": param_type, "description": f"Parameter {p_name}"}
            if p_param.default == inspect.Parameter.empty:
                required.append(p_name)
        return {"type": "object", "properties": properties, "required": required}


_tool_registry = FunctionRegistry()

def tool(name: str = None, description: str = None, parameters: dict = None):
    return _tool_registry.register(name, description, parameters)

def get_registry() -> FunctionRegistry:
    return _tool_registry
