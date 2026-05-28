"""
MCP server for AI Control Panel.

Configure AI_PANEL_URL env var to point to your deployed server.
Default: http://127.0.0.1:1984
"""
import asyncio, os, json, urllib.request, urllib.error

from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server

server = Server("ai-control-panel")
BASE = os.environ.get("AI_PANEL_URL", "http://127.0.0.1:1984")


def _api_call(tool: str, params: dict) -> dict:
    url = f"{BASE}/api/call/{tool}"
    data = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"success": False, "error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="browser_ask_vision",
            description="Upload image to Doubao AI and ask a question about it. Returns text answer. You are a text model, do NOT try to read the image yourself - just pass the path/URL.",
            inputSchema={
                "type": "object",
                "properties": {
                    "image_source": {"type": "string", "description": "Image path, URL, or data URL"},
                    "question": {"type": "string", "description": "Question about the image"},
                    "account_id": {"type": "string", "description": "Account ID", "default": "acc_577cd0d2"}
                },
                "required": ["image_source", "question"]
            }
        ),
        Tool(
            name="get_vision_dir",
            description="Check current image storage directory",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "Account ID", "default": "acc_577cd0d2"}
                }
            }
        ),
        Tool(
            name="set_vision_dir",
            description="Set image storage directory. Ask user for the path first.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path for image storage"},
                    "account_id": {"type": "string", "description": "Account ID", "default": "acc_577cd0d2"}
                },
                "required": ["path"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    result = _api_call(name, arguments)
    if result.get("success"):
        text = json.dumps(result["result"], ensure_ascii=False, indent=2)
    else:
        text = f"Error: {result.get('error', str(result))}"
    return [TextContent(type="text", text=text)]


def main():
    asyncio.run(_main())


async def _main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    main()
