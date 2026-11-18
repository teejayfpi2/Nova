"""Guard against modules that do not import.

The "Native Hybrid Intelligence" change shipped files whose quotes were
written as \\", which is a SyntaxError - importing ``assistant.agent``
failed and broke the whole app. A plain import sweep catches that class of
breakage in CI, where the rest of the suite (which imports the modules it
needs) can otherwise pass by accident.
"""

from __future__ import annotations

import importlib
import pkgutil

import assistant
import assistant.tools


def _submodules(package) -> list[str]:
    # walk_packages already yields fully-qualified names once a prefix is given.
    return [info.name for info in pkgutil.walk_packages(package.__path__, f"{package.__name__}.")]


def test_every_assistant_module_imports():
    modules = ["assistant.agent", "assistant.server", "assistant.cli"] + _submodules(assistant)
    for name in sorted(set(modules)):
        importlib.import_module(name)


def test_tools_register_expected_names():
    names = set(assistant.tools.REGISTRY.names())
    # The built-ins must always be present.
    assert {"remember", "web_search", "type_text", "delegate_task"} <= names
    # The Anna bridge registers exactly these three tools.
    assert {"delegate_to_anna", "generate_presentation", "web_automation_task"} <= names


def test_tool_schemas_have_no_framework_params():
    """A parameter named ctx/context is consumed by the framework, not the model."""
    for schema in assistant.tools.REGISTRY.schemas():
        props = schema["function"]["parameters"].get("properties", {})
        assert "ctx" not in props
        assert "context" not in props
