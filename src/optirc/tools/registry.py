from typing import Any, Callable, Dict


class ToolRegistry:
    """Simple tool registry for agent tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, func: Callable[..., Any]) -> None:
        self._tools[name] = func

    def get(self, name: str) -> Callable[..., Any]:
        if name not in self._tools:
            raise KeyError(f"Tool {name} not found")
        return self._tools[name]

    def list_tools(self) -> list:
        return list(self._tools.keys())


tool_registry = ToolRegistry()
