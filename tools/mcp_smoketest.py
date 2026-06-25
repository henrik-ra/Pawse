"""Quick end-to-end MCP client check against the public streamable-HTTP endpoint.

Verifies that an MCP client (like Copilot Studio) can: connect, list tools, and
call get_day — exactly the flow the Teams chatbot uses.
"""
import asyncio
import sys

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/mcp"


async def main() -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    print(f"Connecting to {URL} ...")
    async with streamablehttp_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("TOOLS:", [t.name for t in tools.tools])
            res = await session.call_tool("get_day", {})
            text = ""
            for c in res.content:
                text += getattr(c, "text", "")
            print("get_day ->", text[:300])


if __name__ == "__main__":
    asyncio.run(main())
