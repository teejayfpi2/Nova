"""Tool registry.

A tool is a plain Python function annotated with ``@tool``. The registry turns
it into the JSON schema an OpenAI-compatible model expects, and dispatches calls
by name. Tools receive a :class:`ToolContext` so they can reach memory, settings
and the device bridges.
"""

from __future__ import annotations

import inspect
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, get_args, get_origin

from ..config import Settings
from ..memory import Memory

_PY_TO_JSON = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


@dataclass
class ToolContext:
    memory: Memory
    settings: Settings
    bridges: dict[str, Any] = field(default_factory=dict)
    session: str = "default"

    def bridge(self, name: str) -> Any:
        return self.bridges.get(name)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]
    dangerous: bool = False

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _json_schema_for(annotation: Any) -> dict[str, Any]:
    origin = get_origin(annotation)
    if origin in (list, typing.List):  # noqa: UP006
        args = get_args(annotation)
        item = _json_schema_for(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": item}
    if origin is dict or origin is typing.Dict:  # noqa: UP006
        return {"type": "object"}
    if origin is typing.Union or str(origin) == "types.UnionType":
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return _json_schema_for(args[0])
    if isinstance(annotation, type) and annotation in _PY_TO_JSON:
        return {"type": _PY_TO_JSON[annotation]}
    return {"type": "string"}


def _build_parameters(func: Callable[..., Any]) -> dict[str, Any]:
    sig = inspect.signature(func)
    hints = typing.get_type_hints(func)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname in {"ctx", "context"}:
            continue
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        schema = _json_schema_for(hints.get(pname, str))
        doc = _param_docs(func, pname)
        if doc:
            schema["description"] = doc
        properties[pname] = schema
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    result: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = required
    return result


def _param_docs(func: Callable[..., Any], pname: str) -> str:
    doc = inspect.getdoc(func) or ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{pname}:") or stripped.startswith(f":param {pname}:"):
            return stripped.split(":", 1)[1].strip()
    return ""


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self, exclude: set[str] | None = None) -> list[dict[str, Any]]:
        exclude = exclude or set()
        return [t.schema() for name, t in self._tools.items() if name not in exclude]

    def call(self, name: str, arguments: dict[str, Any], ctx: ToolContext) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"unknown tool: {name}")
        kwargs = {k: v for k, v in arguments.items() if k != "_raw"}
        sig = inspect.signature(tool.func)
        if "ctx" in sig.parameters:
            kwargs["ctx"] = ctx
        elif "context" in sig.parameters:
            kwargs["context"] = ctx
        return tool.func(**kwargs)


REGISTRY = ToolRegistry()


def tool(
    _func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    dangerous: bool = False,
) -> Callable[..., Any]:
    """Register a function as a tool.

    Use the function's own docstring as the description by default; document
    parameters as ``name: description`` lines.
    """

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        doc = inspect.getdoc(func) or ""
        summary = doc.split("\n\n")[0].strip().replace("\n", " ")
        REGISTRY.register(
            Tool(
                name=name or func.__name__,
                description=description or summary,
                parameters=_build_parameters(func),
                func=func,
                dangerous=dangerous,
            )
        )
        return func

    if _func is not None:
        return decorate(_func)
    return decorate
