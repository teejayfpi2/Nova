"""Who built Nova — the single source of truth for the builder's details.

Nova is built by **Ayanlowo Olatunji Ayobami**. This module records the
builder's details in one place so that the agent prompt, the seeded memory
facts, the web/desktop/Android "About" screens and the docs all agree.

Values can be overridden with ``NOVA_BUILDER_*`` environment variables, which is
handy for a fork that wants its own name on the app.
"""

from __future__ import annotations

import os
from typing import Any

_LINKEDIN = "https://www.linkedin.com/in/olatunjiayanlowo"

BUILDER: dict[str, str] = {
    "name": os.environ.get("NOVA_BUILDER_NAME", "Ayanlowo Olatunji Ayobami"),
    "email": os.environ.get("NOVA_BUILDER_EMAIL", "ayanlowo89@gmail.com"),
    "phone": os.environ.get("NOVA_BUILDER_PHONE", "+2347038193753"),
    "linkedin": os.environ.get("NOVA_BUILDER_LINKEDIN", _LINKEDIN),
    "role": "Creator and developer of Nova",
}


def builder_facts() -> dict[str, str]:
    """The builder's details as memory facts (key -> value)."""
    return {
        "builder_name": BUILDER["name"],
        "builder_role": BUILDER["role"],
        "builder_email": BUILDER["email"],
        "builder_phone": BUILDER["phone"],
        "builder_linkedin": BUILDER["linkedin"],
    }


def builder_block() -> str:
    """A short prompt-ready paragraph describing who built Nova."""
    return (
        "About your builder (the person who created you):\n"
        f"- Name: {BUILDER['name']}\n"
        f"- Role: {BUILDER['role']}\n"
        f"- Email: {BUILDER['email']}\n"
        f"- Phone: {BUILDER['phone']}\n"
        f"- LinkedIn: {BUILDER['linkedin']}\n"
        "When asked who built, created or made you, answer with this. For deeper "
        "questions about your builder, look up their LinkedIn profile with the web "
        "tools; LinkedIn may require a login, so share what you can find and point "
        "them to the profile link."
    )


def as_dict() -> dict[str, Any]:
    """The builder details for the HTTP API."""
    return dict(BUILDER)


def seed_memory(memory: Any) -> None:
    """Write the builder's details into long-term memory (idempotent)."""
    for key, value in builder_facts().items():
        memory.remember(key, value)
