"""
MCP Server - 暴露图片理解工具给支持 MCP 的 AI 客户端

AI 首次使用必须按顺序执行：
  1. 先调用 get_vision_dir 查看当前目录
  2. 询问用户想存哪里，调用 set_vision_dir 配置
  3. 之后才能用 browser_ask_vision 看图

运行方式: python mcp_server.py
"""
import asyncio, sys, os, logging, subprocess

# 自动安装依赖
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

from browser_agent.browser_manager import BrowserManager

server = Server("ai-control-panel-vision")
_bm = None

def _get_bm():
    global _bm
    if _bm is None:
        _bm = BrowserManager(max_instances=2)
    return _bm

def _get_vision_dir(account_id="acc_577cd0d2"):
    """没配置过返回空字符串，AI 必须先问用户配置"""
    cfg_path = os.path.join(os.path.dirname(__file__), "data", "vision_dir.json")
    try:
        if os.path.exists(cfg_path):
            import json
            cfg = json.loads(open(cfg_path, encoding="utf-8").read())
            path = cfg.get(account_id, cfg.get("default", ""))
            if path:
                return path
    except Exception:
        pass
    return ""  # 没配置，返回空，AI 必须问用户

def _set_vision_dir(account_id, path):
    cfg_path = os.path.join(os.path.dirname(__file__), "data", "vision_dir.json")
    try:
        import json
        cfg = {}
        if os.path.exists(cfg_path):
            cfg = json.loads(open(cfg_path, encoding="utf-8").read())
        cfg[account_id] = path
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        open(cfg_path, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))
        return {"status": "ok", "path": path}
    except Exception as e:
        return {"error": str(e)}

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="get_vision_dir",
            description="第一步必用！查看当前图片存储目录。AI 首次使用必须先调用这个，然后询问用户想存哪里，再调用 set_vision_dir 配置。",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "账号ID", "default": "acc_577cd0d2"}
                }
            }
        ),
        Tool(
            name="set_vision_dir",
            description="第二步必用！AI 先问用户想把图片存在哪个目录，然后调用这个工具配置。不配置不能用 browser_ask_vision。",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "存储目录的绝对路径，如 C:\\Users\\xxx\\vision"},
                    "account_id": {"type": "string", "description": "账号ID", "default": "acc_577cd0d2"}
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="browser_ask_vision",
            description="上传图片到豆包，让豆包描述图片内容后返回文字回答。看图前必须先配置目录（用 get_vision_dir + set_vision_dir）。图片会暂存本地目录。",
            inputSchema={
                "type": "object",
                "properties": {
                    "image_source": {"type": "string", "description": "图片来源：本地路径、URL、base64"},
                    "question": {"type": "string", "description": "关于图片的问题，越具体越好"},
                    "account_id": {"type": "string", "description": "账号ID", "default": "acc_577cd0d2"}
                },
                "required": ["image_source", "question"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "get_vision_dir":
        path = _get_vision_dir(arguments.get("account_id", "acc_577cd0d2"))
        return [TextContent(type="text", text=f"当前图片存储目录: {path}。如果还没配置，请先问用户想存哪里，然后调用 set_vision_dir 设置。")]

    elif name == "set_vision_dir":
        result = _set_vision_dir(arguments.get("account_id", "acc_577cd0d2"), arguments.get("path", ""))
        if result.get("status") == "ok":
            return [TextContent(type="text", text=f"目录已配置: {result['path']}。现在可以用 browser_ask_vision 了。")]
        return [TextContent(type="text", text=f"配置失败: {result.get('error')}")]

    elif name == "browser_ask_vision":
        account_id = arguments.get("account_id", "acc_577cd0d2")
        output_dir = _get_vision_dir(account_id)

        # 没配置目录，第一次用
        if not output_dir:
            return [TextContent(type="text", text="还没配置图片存储目录。请先问用户想存在哪个目录，然后调用 set_vision_dir 配置，再重试 browser_ask_vision。")]

        try:
            from browser_agent.actions import ask_vision
            bm = _get_bm()
            mb = await bm.acquire(account_id, url="https://www.doubao.com/chat/",
                                  headless=True, humanize=True)
            try:
                result = await mb.ask_vision(
                    arguments["image_source"],
                    arguments["question"],
                    account_id=account_id,
                    output_dir=output_dir
                )
                if isinstance(result, dict) and "answer" in result:
                    return [TextContent(type="text", text=result["answer"])]
                elif isinstance(result, dict) and "error" in result:
                    return [TextContent(type="text", text=f"错误: {result['error']}。可等2秒后重试。")]
                return [TextContent(type="text", text=str(result))]
            finally:
                await bm.release(account_id)
        except Exception as e:
            return [TextContent(type="text", text=f"异常: {e}")]

    return [TextContent(type="text", text=f"未知工具: {name}")]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())