"""
MCP Server - 通过主服务器 API 提供工具，不自开浏览器
"""
import asyncio, sys, os, logging, subprocess, urllib.request, urllib.error, json

def ensure_deps():
    for pkg in ["mcp"]:
        try:
            __import__(pkg)
        except ImportError:
            print(f"正在安装 {pkg}...")
            subprocess.run([sys.executable, "-m", "pip", "install", pkg, "-q"], check=True)
ensure_deps()

logging.basicConfig(level=logging.WARNING)
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
            name="get_vision_dir",
            description="查看当前图片存储目录",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "账号ID", "default": "acc_577cd0d2"}
                }
            }
        ),
        Tool(
            name="set_vision_dir",
            description="设置图片存储目录（AI 必须先问用户路径）",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "存储目录绝对路径"},
                    "account_id": {"type": "string", "description": "账号ID", "default": "acc_577cd0d2"}
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="browser_ask_vision",
            description="【重要】你不用理解图片！把图片路径/URL直接传进来，系统自动让豆包看图并返回文字回答。你是文本模型，不需要读取图片。",
            inputSchema={
                "type": "object",
                "properties": {
                    "image_source": {"type": "string", "description": "图片来源：本地路径、URL、base64"},
                    "question": {"type": "string", "description": "关于图片的问题"},
                    "account_id": {"type": "string", "description": "账号ID", "default": "acc_577cd0d2"}
                },
                "required": ["image_source", "question"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    result = _api_call(name, arguments)
    if result.get("success"):
        text = json.dumps(result["result"], ensure_ascii=False, indent=2)
    else:
        text = f"错误: {result.get('error', str(result))}"
    return [TextContent(type="text", text=text)]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
