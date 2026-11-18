\"\"\"The agent loop: plan, call tools, observe, answer.\"\"\"

from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterator

from .config import Settings, settings as default_settings
from .identity import builder_block
from .llm import LLMClient, LLMError
from .memory import Memory
from .tools import REGISTRY, ToolContext, builtin  # noqa: F401 - builtin registers the tools

SYSTEM_PROMPT = \"\"\"You are Nova, a personal assistant running on the user's own \\
laptop and phone. You are practical, concise and friendly.

You have a unified hybrid intelligence:
- Your LOCAL body (this machine) handles typing, clicking, apps and system control.
- Your CLOUD mind (Anna, the Strategic Operations Center) handles heavy research, \\
complex web automation and professional document generation.

You can act on the real devices:
- Type text, press keys, click, take screenshots, open apps and URLs.
- Send and read messages (sms, whatsapp, telegram, signal, imessage).
- Search the web and read pages.
- Run shell commands and Python.
- Remember facts, take notes, keep a to-do list and set reminders.

For heavy, multi-step cloud jobs, use your Anna expansion:
- delegate_to_anna: hand off high-level research, PDF/PPTX generation, or \\
complex Talent Browser automation.
- generate_presentation: create professional slide decks.
- web_automation_task: perform deep web scraping or multi-page automation.

For local technical jobs (coding, terminal work), use OpenHands:
- delegate_task: hand off any long job (build a project, run and fix tests, \\
install software) and get the result back.
Prefer these over guessing when a request needs real, multi-step work.

Rules:
- Use tools whenever a request needs real information or a real action.
- For device actions, pass target=\"phone\" for phone tasks and target=\"laptop\" \\
for computer tasks.
- Keep spoken replies short (1-3 sentences) unless the user asks for detail.
- If asked who built, created or made you, answer with your builder's details.

{builder}

{memory}

Current time: {now}\"\"\"


class Agent:
    def __init__(
        self,
        memory: Memory,
        llm: LLMClient | None = None,
        settings: Settings | None = None,
        bridges: dict[str, Any] | None = None,
    ) -> None:
        self.memory = memory
        self.llm = llm or LLMClient()
        self.settings = settings or default_settings
        self.bridges = bridges or {}

    # -- context ---------------------------------------------------------
    def _system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(
            builder=builder_block(),
            memory=self.memory.context_block(),
            now=time.strftime(\"%A %d %B %Y, %H:%M %Z\"),
        )

    def _tool_context(self, session: str) -> ToolContext:
        return ToolContext(
            memory=self.memory, settings=self.settings, bridges=self.bridges, session=session
        )

    # -- main entry point -------------------------------------------------
    def run(
        self,
        user_message: str,
        session: str = \"default\",
        history: list[dict[str, Any]] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        \"\"\"Run one turn. Returns the final assistant text.\"\"\"
        events = self.stream(user_message, session=session, history=history)
        final = \"\"
        for event in events:
            if on_event:
                on_event(event)
            if event[\"type\"] == \"final\":
                final = event[\"text\"]
        return final

    def stream(
        self,
        user_message: str,
        session: str = \"default\",
        history: list[dict[str, Any]] | None = None,
    ) -> Iterator[dict[str, Any]]:
        \"\"\"Yield events: {'type': 'tool', ...}, {'type': 'final', 'text': ...}.\"\"\"
        ctx = self._tool_context(session)
        messages: list[dict[str, Any]] = [{\"role\": \"system\", \"content\": self._system_prompt()}]

        if history is None:
            history = self.memory.recent_messages(session, limit=20)
        messages.extend(history)
        messages.append({\"role\": \"user\", \"content\": user_message})
        self.memory.log_message(\"user\", user_message, session)

        tools = REGISTRY.schemas()
        for step in range(self.settings.max_steps):
            try:
                response = self.llm.chat(messages, tools=tools)
            except LLMError as exc:
                text = f\"I could not reach my language model: {exc}\"
                self.memory.log_message(\"assistant\", text, session)
                yield {\"type\": \"final\", \"text\": text}
                return

            if not response.tool_calls:
                text = response.content.strip() or \"Done.\"
                self.memory.log_message(\"assistant\", text, session)
                yield {\"type\": \"final\", \"text\": text}
                return

            messages.append(
                {
                    \"role\": \"assistant\",
                    \"content\": response.content or None,
                    \"tool_calls\": [
                        {
                            \"id\": tc.id or f\"call_{step}_{i}\",
                            \"type\": \"function\",
                            \"function\": {\"name\": tc.name, \"arguments\": json.dumps(tc.arguments)},
                        }
                        for i, tc in enumerate(response.tool_calls)
                    ],
                }
            )

            for i, tc in enumerate(response.tool_calls):
                call_id = tc.id or f\"call_{step}_{i}\"
                yield {\"type\": \"tool\", \"name\": tc.name, \"arguments\": tc.arguments}
                try:
                    result = REGISTRY.call(tc.name, tc.arguments, ctx)
                except Exception as exc:  # noqa: BLE001 - report tool errors to model
                    result = f\"Error: {type(exc).__name__}: {exc}\"
                yield {\"type\": \"tool_result\", \"name\": tc.name, \"result\": str(result)[:2000]}
                messages.append(
                    {
                        \"role\": \"tool\",
                        \"tool_call_id\": call_id,
                        \"content\": str(result)[:8000],
                    }
                )

        text = \"I hit my step limit while working on that. Try breaking it into smaller steps.\"
        self.memory.log_message(\"assistant\", text, session)
        yield {\"type\": \"final\", \"text\": text}
