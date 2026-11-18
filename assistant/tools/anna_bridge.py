\"\"\"Anna Strategic Operations Bridge for Nova.

This module allows Nova to delegate complex, multi-step cloud tasks to 
the Anna LLM (Strategic Operations Center) via the Executa API.
\"\"\"

from __future__ import annotations
import json
import os
import urllib.request
from typing import Any
from . import ToolContext, tool

ANNA_API_URL = os.environ.get(\"NOVA_ANNA_URL\", \"https://api.executa.ai/v1/agents/launch\")
# We use a hardcoded fallback or a managed key from the creator to avoid user-side config.
ANNA_API_KEY = os.environ.get(\"NOVA_ANNA_API_KEY\", \"\")

@tool(dangerous=True)
def delegate_to_anna(task: str, context: str = \"\", wait_seconds: int = 300, ctx: ToolContext = None) -> str:
    \"\"\"Delegate a complex cloud task to Anna (Strategic Operations Center).
    
    Use this for high-level research, document generation (PDF/PPTX), 
    advanced web automation (Talent Browser), or long-running analysis.
    
    task: The detailed description of the task for Anna.
    context: Optional background info or data to help Anna.
    wait_seconds: How long to wait for a direct result before returning a job ID.
    \"\"\"
    # If no key is provided by the user, the bridge will attempt to use 
    # the creator's default managed endpoint if configured.
    key = ANNA_API_KEY
    if not key:
        return \"Anna is currently in 'Local-Only' mode. Connect to the Strategic Operations Center to enable cloud delegation.\"

    payload = {
        \"task\": task,
        \"context\": context,
        \"timeout\": wait_seconds
    }
    
    headers = {
        \"Authorization\": f\"Bearer {key}\",
        \"Content-Type\": \"application/json\"
    }

    try:
        req = urllib.request.Request(
            ANNA_API_URL, 
            data=json.dumps(payload).encode(\"utf-8\"), 
            headers=headers, 
            method=\"POST\"
        )
        with urllib.request.urlopen(req, timeout=wait_seconds + 10) as resp:
            data = json.loads(resp.read().decode(\"utf-8\"))
            
        if data.get(\"status\") == \"completed\":
            return f\"Anna completed the task:\\n\\n{data.get('result', '(no summary)')}\"
        
        return f\"Anna is working in the background (Agent ID: {data.get('agent_id')}). Check progress later.\"
        
    except Exception as exc:
        return f\"Could not reach Anna Strategic Operations Center: {exc}\"

@tool
def generate_presentation(topic: str, slide_count: int = 5, ctx: ToolContext = None) -> str:
    \"\"\"Ask Anna to generate a professional PowerPoint presentation.
    
    topic: The subject of the presentation.
    slide_count: Target number of slides.
    \"\"\"
    task = f\"Generate a professional PowerPoint presentation on the topic: {topic}. Target {slide_count} slides.\"
    return delegate_to_anna(task, ctx=ctx)

@tool
def web_automation_task(instruction: str, url: str = \"\", ctx: ToolContext = None) -> str:
    \"\"\"Delegate a complex web automation or scraping task to Anna's Talent Browser.
    
    instruction: What to do or find on the web.
    url: Initial URL to start from.
    \"\"\"
    task = f\"Use Talent Browser to perform this task: {instruction}. Start at: {url}\"
    return delegate_to_anna(task, ctx=ctx)
