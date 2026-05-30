import json
import asyncio
import logging
import sys
from pathlib import Path
from dataclasses import dataclass

from core.registry import get_registry, tool
from core.server import AppServer
from core.event_bus import EventBus
from core.task_queue import TaskQueue

from proxy_providers.base import ProxyManager
from proxy_providers.tor_provider import TorProvider
from proxy_providers.workers_provider import WorkersProvider
from proxy_providers.direct_provider import DirectProvider

from session.account_manager import AccountManager
from session.login_helper import LoginManager
from anti_detection.fingerprint import FingerprintManager
from browser_agent.controller import BrowserController
from browser_agent.browser_manager import BrowserManager
from browser_agent.analyzer import PageAnalyzer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("main")


# ─── 全局依赖容器 ──────────────────────────────────────────

@dataclass
class AppContext:
    proxy_manager: ProxyManager
    account_manager: AccountManager
    fingerprint_manager: FingerprintManager
    task_queue: TaskQueue
    event_bus: EventBus
    login_manager: LoginManager
    browser: BrowserController
    browser_manager: BrowserManager
    page_analyzer: PageAnalyzer


ctx: AppContext = None


def _ctx():
    return ctx


# ─── 工具函数定义 ─────────────────────────────────────────────

@tool(name="list_functions", description="列出所有可调用的函数及其参数说明")
async def fn_list_functions():
    return get_registry().list_dicts()


@tool(name="get_system_status", description="获取系统整体状态：队列、代理、账号")
async def fn_get_system_status():
    c = _ctx()
    return {
        "proxy": await c.proxy_manager.health(),
        "queue": c.task_queue.get_status(),
        "accounts": c.account_manager.list_accounts(),
    }


@tool(name="list_proxy_modes", description="列出所有可用的代理模式")
async def fn_list_proxy_modes():
    return _ctx().proxy_manager.list_modes()


@tool(name="get_proxy_status", description="获取当前代理的连接状态")
async def fn_get_proxy_status():
    return await _ctx().proxy_manager.health()


@tool(name="switch_proxy", description="切换代理模式", parameters={
    "type": "object",
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["tor", "workers", "direct"],
            "description": "tor=Tor匿名网络, workers=Cloudflare Workers中转, direct=直连(仅测试)"
        }
    },
    "required": ["mode"]
})
async def fn_switch_proxy(mode: str):
    return await _ctx().proxy_manager.switch(mode)


@tool(name="test_proxy", description="测试指定代理模式的连通性", parameters={
    "type": "object",
    "properties": {
        "mode": {"type": "string", "enum": ["tor", "workers", "direct"]}
    },
    "required": ["mode"]
})
async def fn_test_proxy(mode: str):
    return await _ctx().proxy_manager.test(mode)


@tool(name="list_services", description="列出当前可用的 AI 生成服务")
async def fn_list_services():
    return [
        {"name": "stable-diffusion", "label": "Stable Diffusion (本地)", "status": "not_connected"},
        {"name": "midjourney", "label": "Midjourney (Discord)", "status": "not_connected"},
        {"name": "runway", "label": "RunwayML (网页)", "status": "not_connected"},
    ]


@tool(name="list_accounts", description="列出所有已添加的账号", parameters={
    "type": "object",
    "properties": {
        "service": {"type": "string", "description": "按服务筛选，如 midjourney，留空显示全部"}
    }
})
async def fn_list_accounts(service: str = ""):
    s = service if service else None
    return _ctx().account_manager.list_accounts(s)


@tool(name="add_account", description="添加一个账号", parameters={
    "type": "object",
    "properties": {
        "service": {"type": "string", "description": "服务名称，如 midjourney, runway"},
        "label": {"type": "string", "description": "账号标签，如 '主账号'"}
    },
    "required": ["service", "label"]
})
async def fn_add_account(service: str, label: str):
    am = _ctx().account_manager
    account = am.add_account(service, label)
    account.ensure_profile()
    am.save()
    logger.info(f"添加账号: {service}/{label} -> {account.id}")
    return {"success": True, "account_id": account.id, "message": f"请手动登录后将 Cookie 传给 update_account_cookies"}


@tool(name="remove_account", description="删除一个账号", parameters={
    "type": "object",
    "properties": {"account_id": {"type": "string"}},
    "required": ["account_id"]
})
async def fn_remove_account(account_id: str):
    _ctx().account_manager.remove_account(account_id)
    return {"success": True}


@tool(name="update_account_cookies", description="更新账号的登录 Cookie（手动登录后调用）", parameters={
    "type": "object",
    "properties": {
        "account_id": {"type": "string"},
        "cookies": {"type": "array", "items": {"type": "object"}},
        "storage": {"type": "object"}
    },
    "required": ["account_id", "cookies"]
})
async def fn_update_account_cookies(account_id: str, cookies: list, storage: dict = None):
    _ctx().account_manager.update_cookies(account_id, cookies, storage)
    return {"success": True, "message": "账号已更新"}


@tool(name="submit_tasks", description="提交一批生成任务", parameters={
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "AI 服务名"},
                    "action": {"type": "string", "description": "操作类型"},
                    "params": {"type": "object", "description": "参数字典"},
                    "count": {"type": "integer", "description": "生成数量"}
                },
                "required": ["service", "action", "params"]
            }
        },
        "priority": {"type": "integer", "enum": [1, 2, 3], "description": "优先级 1高-3低"}
    },
    "required": ["tasks"]
})
async def fn_submit_tasks(tasks: list, priority: int = 2):
    from core.task_queue import Task
    task_objs = []
    for t in tasks:
        task = Task(
            service=t["service"],
            action=t["action"],
            params=t.get("params", {}),
            count=t.get("count", 1),
            priority=priority,
        )
        task_objs.append(task)
    batch_id = _ctx().task_queue.submit(task_objs)
    return {"success": True, "batch_id": batch_id, "task_count": len(task_objs)}


@tool(name="get_batch_status", description="查看某个批次的状态", parameters={
    "type": "object",
    "properties": {"batch_id": {"type": "string", "description": "批次ID"}},
    "required": ["batch_id"]
})
async def fn_get_batch_status(batch_id: str):
    batch = _ctx().task_queue.get_batch(batch_id)
    if not batch:
        return {"error": "batch not found"}
    return batch.status


@tool(name="pause_batch", description="暂停某个批次", parameters={
    "type": "object", "properties": {"batch_id": {"type": "string"}}, "required": ["batch_id"]
})
async def fn_pause_batch(batch_id: str):
    _ctx().task_queue.pause_batch(batch_id)
    return {"success": True}


@tool(name="cancel_batch", description="取消某个批次", parameters={
    "type": "object", "properties": {"batch_id": {"type": "string"}}, "required": ["batch_id"]
})
async def fn_cancel_batch(batch_id: str):
    _ctx().task_queue.cancel_batch(batch_id)
    return {"success": True}


@tool(name="echo", description="测试用：原样返回你传的参数", parameters={
    "type": "object",
    "properties": {"message": {"type": "string", "description": "要回复的消息"}},
    "required": ["message"]
})
async def fn_echo(message: str):
    return {"echo": message}


# ─── 浏览器控制工具 ─────────────────────────────────────────

@tool(name="browser_open", description="打开一个浏览器窗口，可指定 URL 和注入 Cookie", parameters={
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "要打开的网址"},
        "headless": {"type": "boolean", "description": "是否无头模式"},
        "account_id": {"type": "string", "description": "账号ID（自动注入 Cookie，有ID则走隔离实例）"}
    },
    "required": ["url"]
})
async def fn_browser_open(url: str, headless: bool = False, account_id: str = ""):
    c = _ctx()
    if account_id:
        acc = c.account_manager.get_account(account_id)
        if acc:
            acc.ensure_profile()
            c.account_manager.save()
        try:
            mb = await c.browser_manager.acquire(account_id, url=url, headless=headless)
        except RuntimeError as e:
            return {"error": str(e)}
        try:
            if mb.page:
                c.page_analyzer.bind(mb.page)
            return {"status": "opened", "account_id": account_id,
                    "cloakbrowser": True, "humanize": True}
        except Exception:
            await c.browser_manager.release(account_id)
            raise
    cookies = None
    proxy = None
    result = await c.browser.open(url=url, headless=headless, cookies=cookies,
                                  proxy=proxy, account_id="")
    if c.browser.page:
        c.page_analyzer.bind(c.browser.page)
    return result


@tool(name="browser_snapshot", description="获取当前页面的完整状态：元素列表、图片、文本", parameters={
    "type": "object",
    "properties": {
        "include_screenshot": {"type": "boolean", "description": "是否包含截图(base64)"},
        "account_id": {"type": "string", "description": "账号ID（留空用默认浏览器）"}
    }
})
async def fn_browser_snapshot(include_screenshot: bool = False, account_id: str = ""):
    c = _ctx()
    if account_id:
        mb = c.browser_manager.get_instance(account_id)
        if not mb or not mb.is_open:
            return {"error": f"账号 {account_id} 的浏览器未打开"}
        c.page_analyzer.bind(mb.page)
    if not c.page_analyzer._page:
        return {"error": "没有打开的页面"}
    return await c.page_analyzer.snapshot(include_screenshot=include_screenshot)


@tool(name="browser_click", description="点击页面上的元素，通过编号或文本匹配", parameters={
    "type": "object",
    "properties": {
        "element_id": {"type": "integer", "description": "元素的编号（从snapshot中获取）"},
        "text": {"type": "string", "description": "按钮文本（模糊匹配）"},
        "account_id": {"type": "string", "description": "账号ID（留空用默认浏览器）"}
    }
})
async def fn_browser_click(element_id: int = -1, text: str = "", account_id: str = ""):
    c = _ctx()
    target = {}
    if element_id >= 0:
        target["id"] = element_id
    elif text:
        target["text"] = text
    else:
        return {"error": "请提供 element_id 或 text"}
    if account_id:
        mb = c.browser_manager.get_instance(account_id)
        if not mb or not mb.is_open:
            return {"error": f"账号 {account_id} 的浏览器未打开"}
        return await mb.click(target)
    return await c.browser.click(target)


@tool(name="browser_type", description="在输入框输入文字", parameters={
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "要输入的文字"},
        "element_id": {"type": "integer", "description": "输入框编号"},
        "account_id": {"type": "string", "description": "账号ID（留空用默认浏览器）"}
    },
    "required": ["text"]
})
async def fn_browser_type(text: str, element_id: int = -1, account_id: str = ""):
    target = {"id": element_id} if element_id >= 0 else {}
    c = _ctx()
    if account_id:
        mb = c.browser_manager.get_instance(account_id)
        if not mb or not mb.is_open:
            return {"error": f"账号 {account_id} 的浏览器未打开"}
        return await mb.type_text(text, target=target)
    return await c.browser.type_text(text, target=target)


@tool(name="browser_press", description="按下键盘按键", parameters={
    "type": "object",
    "properties": {
        "key": {"type": "string", "description": "按键名如 Enter, Escape, ArrowDown"},
        "account_id": {"type": "string", "description": "账号ID（留空用默认浏览器）"}
    },
    "required": ["key"]
})
async def fn_browser_press(key: str, account_id: str = ""):
    c = _ctx()
    if account_id:
        mb = c.browser_manager.get_instance(account_id)
        if not mb or not mb.is_open:
            return {"error": f"账号 {account_id} 的浏览器未打开"}
        return await mb.press_key(key)
    return await c.browser.press_key(key)


@tool(name="browser_extract_images", description="获取当前页面上所有可见图片的 URL", parameters={
    "type": "object",
    "properties": {"account_id": {"type": "string", "description": "账号ID（留空用默认浏览器）"}}
})
async def fn_browser_extract_images(account_id: str = ""):
    c = _ctx()
    if account_id:
        mb = c.browser_manager.get_instance(account_id)
        if not mb or not mb.is_open:
            return {"error": f"账号 {account_id} 的浏览器未打开"}
        c.page_analyzer.bind(mb.page)
    if not c.page_analyzer._page:
        return {"error": "没有打开的页面"}
    return {"images": await c.page_analyzer.extract_images()}


@tool(name="browser_download", description="下载指定 URL 的图片到本地", parameters={
    "type": "object",
    "properties": {
        "image_url": {"type": "string", "description": "图片 URL"},
        "filename": {"type": "string", "description": "保存文件名（可选）"}
    },
    "required": ["image_url"]
})
async def fn_browser_download(image_url: str, filename: str = ""):
    import urllib.request
    import os
    os.makedirs("output", exist_ok=True)
    name = filename or f"output/download_{len(os.listdir('output')) + 1}.png"
    try:
        urllib.request.urlretrieve(image_url, name)
        return {"success": True, "path": name, "size": os.path.getsize(name)}
    except Exception as e:
        return {"error": str(e)}


@tool(name="browser_screenshot", description="截取当前浏览器窗口的截图（base64），AI 可用作视觉输入判断页面状态", parameters={
    "type": "object",
    "properties": {
        "full_page": {"type": "boolean", "description": "是否截取整页（默认仅可视区域）"},
        "account_id": {"type": "string", "description": "账号ID（留空用默认浏览器）"}
    }
})
async def fn_browser_screenshot(full_page: bool = False, account_id: str = ""):
    c = _ctx()
    page = None
    if account_id:
        mb = c.browser_manager.get_instance(account_id)
        if not mb or not mb.is_open:
            return {"error": f"账号 {account_id} 的浏览器未打开"}
        page = mb.page
    else:
        if not c.browser.is_open:
            return {"error": "浏览器未打开"}
        page = c.browser.page
    import base64
    raw = await page.screenshot(full_page=full_page, type="png")
    b64 = base64.b64encode(raw).decode()
    return {"screenshot_base64": b64, "size": len(raw), "full_page": full_page}


@tool(name="browser_evaluate", description="在浏览器页面执行 JavaScript 代码并返回结果（调试用）", parameters={
    "type": "object",
    "properties": {
        "code": {"type": "string", "description": "要执行的 JavaScript 代码"},
        "account_id": {"type": "string", "description": "账号ID（留空用默认浏览器）"}
    },
    "required": ["code"]
})
async def fn_browser_evaluate(code: str, account_id: str = ""):
    c = _ctx()
    page = None
    if account_id:
        mb = c.browser_manager.get_instance(account_id)
        if mb and mb.is_open:
            page = mb.page
    else:
        if c.browser.is_open:
            page = c.browser.page
    if not page:
        return {"error": "没有打开的浏览器页面"}
    try:
        result = await page.evaluate(code)
        return {"result": result}
    except Exception as e:
        return {"error": str(e)}


@tool(name="browser_wait", description="等待指定秒数", parameters={
    "type": "object",
    "properties": {"seconds": {"type": "number", "description": "等待秒数"}}
})
async def fn_browser_wait(seconds: float = 2):
    await asyncio.sleep(seconds)
    return {"status": "waited", "seconds": seconds}


@tool(name="browser_close", description="关闭指定账号的浏览器窗口，不传 account_id 则关闭默认窗口", parameters={
    "type": "object",
    "properties": {"account_id": {"type": "string", "description": "账号ID"}}
})
async def fn_browser_close(account_id: str = ""):
    c = _ctx()
    if account_id:
        await c.browser_manager.close(account_id)
        return {"status": "closed", "account_id": account_id}
    await c.browser.close()
    return {"status": "closed"}


@tool(name="browser_ask_vision",
      description="【重要】你不用理解图片内容！把图片路径/URL 直接传给此工具，系统会自动上传到豆包让豆包看图和回答。返回的是豆包的文字回答。你是文本模型，不需要也不应该读取图片。",
      parameters={
          "type": "object",
          "properties": {
              "image_source": {"type": "string", "description": "图片来源：URL、本地路径、或base64。直接传字符串，你不用看图片内容"},
              "question": {"type": "string", "description": "关于图片的问题，如'这张图片里有什么？'"},
              "account_id": {"type": "string", "description": "账号ID（留空用默认浏览器）"},
              "output_dir": {"type": "string", "description": "临时图片存储目录（默认 output）"}
          },
          "required": ["image_source", "question"]
      })
async def fn_browser_ask_vision(image_source: str, question: str, account_id: str = "", output_dir: str = None):
    c = _ctx()
    if not account_id:
        account_id = "acc_577cd0d2"
    if account_id:
        try:
            mb = await c.browser_manager.acquire(account_id, url="https://www.doubao.com/chat/",
                                                 headless=True, humanize=True)
        except RuntimeError as e:
            return {"error": str(e)}
        try:
            if mb.page:
                c.page_analyzer.bind(mb.page)
            return await mb.ask_vision(image_source, question, account_id=account_id, output_dir=output_dir)
        finally:
            await c.browser_manager.release(account_id)
    if not c.browser.is_open:
        await c.browser.open(url="https://www.doubao.com/chat/", headless=True, account_id="")
    return await c.browser.ask_vision(image_source, question, account_id=account_id, output_dir=output_dir)


@tool(name="get_vision_dir",
      description="查看当前配置的图片存储目录",
      parameters={
          "type": "object",
          "properties": {
              "account_id": {"type": "string", "description": "账号ID（留空用默认）", "default": "acc_577cd0d2"}
          }
      })
async def fn_get_vision_dir(account_id: str = "acc_577cd0d2"):
    from browser_agent.actions import _get_vision_dir
    path = _get_vision_dir(account_id)
    return {"path": path, "account_id": account_id}


@tool(name="set_vision_dir",
      description="设置图片存储目录，AI 会询问用户想存放路径后自动配置",
      parameters={
          "type": "object",
          "properties": {
              "path": {"type": "string", "description": "存储目录的绝对路径，如 C:\\Users\\xxx\\vision"},
              "account_id": {"type": "string", "description": "账号ID（留空用默认）", "default": "acc_577cd0d2"}
          },
          "required": ["path"]
      })
async def fn_set_vision_dir(path: str, account_id: str = "acc_577cd0d2"):
    from browser_agent.actions import _set_vision_dir
    return _set_vision_dir(account_id, path)


@tool(name="browser_generate_image",
      description="【你不用画图】在浏览器调用豆包/千问生成图片，自动下载到本地并裁水印。你只需给文字提示词，剩下的系统做。",
      parameters={
          "type": "object",
          "properties": {
              "prompt": {"type": "string", "description": "图片描述提示词，越详细越好"},
              "account_id": {"type": "string", "description": "账号ID（豆包或千问）"},
              "output_dir": {"type": "string", "description": "下载目录（默认 output）"}
          },
          "required": ["prompt", "account_id"]
      })
async def fn_browser_generate_image(prompt: str, account_id: str, output_dir: str = "output"):
    c = _ctx()
    acc = c.account_manager.get_account(account_id)
    account_url = acc.url if acc else None
    try:
        mb = await c.browser_manager.acquire(account_id, url=account_url,
                                             headless=True, humanize=True)
    except RuntimeError as e:
        return {"error": str(e)}
    try:
        if mb.page:
            c.page_analyzer.bind(mb.page)
        return await mb.generate_image(prompt, output_dir)
    finally:
        await c.browser_manager.release(account_id)



# ─── 批量生成工具 ────────────────────────────────────────────

@tool(name="batch_generate_images",
      description="批量在豆包生成图片：多个账号并行出图，自动管理浏览器实例池",
      parameters={
          "type": "object",
          "properties": {
              "tasks": {
                  "type": "array",
                  "items": {
                      "type": "object",
                      "properties": {
                          "account_id": {"type": "string", "description": "账号ID"},
                          "prompt": {"type": "string", "description": "图片描述提示词"}
                      },
                      "required": ["account_id", "prompt"]
                  },
                  "description": "生成任务列表"
              },
              "max_concurrency": {"type": "integer", "description": "最大并行数（默认3）"},
              "headless": {"type": "boolean", "description": "是否无头模式（生产建议 true）"},
              "output_dir": {"type": "string", "description": "输出目录（默认 output）"}
          },
          "required": ["tasks"]
      })
async def fn_batch_generate_images(tasks: list, max_concurrency: int = 3,
                                    headless: bool = True, output_dir: str = "output"):
    c = _ctx()
    results = await c.browser_manager.execute_batch(
        tasks, max_concurrency=max_concurrency,
        headless=headless, output_dir=output_dir,
    )
    succeeded = sum(1 for r in results if r.get("success"))
    failed = sum(1 for r in results if not r.get("success"))
    return {
        "success": True,
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


@tool(name="get_browser_pool_stats", description="查看浏览器实例池状态（当前实例数、空闲/忙碌等）")
async def fn_get_browser_pool_stats():
    return _ctx().browser_manager.get_stats()


# ─── 主启动 ─────────────────────────────────────────────────

def main():
    global ctx

    config_path = Path("config.json")
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        config = {}

    server_cfg = config.get("server", {"host": "127.0.0.1", "port": 1984})
    proxy_cfg = config.get("proxy", {})
    storage_cfg = config.get("storage", {})

    # 初始化各模块
    event_bus = EventBus()
    task_queue = TaskQueue(max_concurrency=config.get("executors", {}).get("concurrency", 3))
    account_manager = AccountManager(storage_path=storage_cfg.get("accounts", "data/accounts.json"))
    fingerprint_manager = FingerprintManager(storage_path=storage_cfg.get("fingerprints", "data/fingerprints.json"))
    login_manager = LoginManager()
    proxy_manager = ProxyManager()
    browser = BrowserController()
    browser_manager = BrowserManager(
        max_instances=config.get("executors", {}).get("max_browsers", 5),
        idle_timeout=config.get("executors", {}).get("browser_idle_timeout", 600),
    )
    page_analyzer = PageAnalyzer()

    # 注册代理提供者
    tor_cfg = proxy_cfg.get("tor", {})
    workers_cfg = proxy_cfg.get("workers", {})
    proxy_manager.register(TorProvider(
        socks_host=tor_cfg.get("socks_host", "127.0.0.1"),
        socks_port=tor_cfg.get("socks_port", 9050),
        control_port=tor_cfg.get("control_port", 9051),
    ))
    proxy_manager.register(WorkersProvider(workers_url=workers_cfg.get("url", "")))
    proxy_manager.register(DirectProvider())

    # 给 BrowserManager 注入 account/proxy 依赖
    browser_manager.account_manager = account_manager
    browser_manager.proxy_manager = proxy_manager

    # 初始化全局上下文
    ctx = AppContext(
        proxy_manager=proxy_manager,
        account_manager=account_manager,
        fingerprint_manager=fingerprint_manager,
        task_queue=task_queue,
        event_bus=event_bus,
        login_manager=login_manager,
        browser=browser,
        browser_manager=browser_manager,
        page_analyzer=page_analyzer,
    )

    registry = get_registry()

    async def run_async():
        # 启动默认代理
        default_mode = proxy_cfg.get("default_mode", "tor")
        try:
            await proxy_manager.switch(default_mode)
            logger.info(f"默认代理已启动: {default_mode}")
        except Exception as e:
            logger.warning(f"默认代理启动失败: {e}，可稍后通过 switch_proxy 切换")

        # 启动任务队列处理
        asyncio.create_task(task_queue.process_loop())

        # 启动浏览器实例池看门狗
        await browser_manager.start_watchdog(interval=30)
        logger.info("浏览器实例池看门狗已启动")

        # 任务完成时推送事件
        async def on_task_complete(task):
            await event_bus.emit_state_change({
                "queue": task_queue.get_status(),
            })
        task_queue.set_on_complete(on_task_complete)

        # 启动 HTTP 服务
        server = AppServer(
            registry=registry,
            event_bus=event_bus,
            task_queue=task_queue,
            account_manager=account_manager,
            login_manager=login_manager,
            fingerprint_manager=fingerprint_manager,
            browser_manager=browser_manager,
        )
        await server.start_event_listener()

        host = server_cfg.get("host", "0.0.0.0")
        port = server_cfg.get("port", 1984)
        logger.info(f"🤖 AI 控制面板启动: http://{host}:{port}")
        logger.info(f"📋 API 文档: http://{host}:{port}/docs")
        logger.info(f"🔧 已注册 {len(registry.all())} 个函数")
        await server.start(host=host, port=port)

    asyncio.run(run_async())


if __name__ == "__main__":
    main()
