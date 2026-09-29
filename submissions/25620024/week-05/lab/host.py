"""Week 05 lab, step 4: the week-01 loop turned into an MCP host.

Copied from week-01/first_agent.py. The loop is unchanged; only two lines moved:
  - TOOLS (hand-written schemas)  ->  list_tools() from the server
  - TOOLS_IMPL[name](**args)      ->  call_tool(name, args) on the server
The tool functions themselves now live in tools_server.py.

Requires: pip install "mcp>=2" anthropic, ANTHROPIC_API_KEY in the environment,
and the server running:  python tools_server.py --http
"""
import sys
import asyncio

import anthropic
from mcp import Client

MCP_SERVER = "http://127.0.0.1:8000/mcp"


def to_anthropic(tool) -> dict:
    """MCP tool entry -> the tool format the Anthropic Messages API expects."""
    return {"name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.input_schema}


async def run(goal: str, max_steps: int = 8):
    async with Client(MCP_SERVER) as mcp:
        TOOLS = [to_anthropic(t) for t in (await mcp.list_tools()).tools]
        print(f"[host] {MCP_SERVER} tools={[t['name'] for t in TOOLS]}")

        client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY
        messages = [{"role": "user", "content": goal}]

        for step in range(max_steps):   # <- this loop is what makes it an agent
            resp = client.messages.create(
                model="claude-sonnet-4-5", max_tokens=1024,
                tools=TOOLS, messages=messages)
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":   # final answer -> stop
                return "".join(b.text for b in resp.content if b.type == "text")

            results = []
            for block in resp.content:           # execute tool calls -> observe
                if block.type == "tool_use":
                    res = await mcp.call_tool(block.name, block.input)
                    out = "".join(c.text for c in res.content if c.type == "text")
                    print(f"  [tool] {block.name}({block.input}) -> {out}")
                    results.append({"type": "tool_result",
                                    "tool_use_id": block.id, "content": out,
                                    "is_error": res.is_error})
            messages.append({"role": "user", "content": results})

        return "stopped: max steps exceeded"   # the stop condition is a safety net


if __name__ == "__main__":
    goal = sys.argv[1] if len(sys.argv) > 1 else (
        "Read notes.txt and add up every number in it.")
    print(asyncio.run(run(goal)))
