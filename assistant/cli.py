"""Nova command-line interface."""

from __future__ import annotations

import argparse
import sys

from .agent import Agent
from .bridges import REGISTRY as BRIDGES
from .bridges import LocalBridge
from .config import settings
from .llm import LLMClient
from .memory import Memory


def build_agent() -> Agent:
    BRIDGES.register("laptop", LocalBridge("laptop"))
    return Agent(memory=Memory(), llm=LLMClient(), settings=settings, bridges=BRIDGES.as_dict())


def repl() -> int:
    agent = build_agent()
    print("Nova ready. Type 'exit' to quit.\n")
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in {"exit", "quit"}:
            return 0
        for event in agent.stream(line):
            if event["type"] == "tool":
                print(f"  · {event['name']}({event['arguments']})")
            elif event["type"] == "tool_result":
                print(f"    → {event['result'][:200]}")
            elif event["type"] == "final":
                print(f"nova> {event['text']}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nova", description="Nova personal assistant")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("chat", help="interactive chat")
    sub.add_parser("serve", help="run the web server")

    ask = sub.add_parser("ask", help="send a single message")
    ask.add_argument("message", nargs="+")

    args = parser.parse_args(argv)

    if args.command == "serve":
        from .server import main as serve

        serve()
        return 0
    if args.command == "ask":
        agent = build_agent()
        print(agent.run(" ".join(args.message)))
        return 0
    return repl()


if __name__ == "__main__":
    sys.exit(main())
