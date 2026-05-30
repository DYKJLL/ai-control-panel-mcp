# AI Control Panel

桌面软件框架，嵌入 Web AI 服务。让 AI 通过函数调用控制浏览器完成生图、看图。

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  AI Client                       │
│  (Claude, Cline, 魔塔, 或其他任何 AI)            │
└──────────────┬──────────────────────┬──────────┘
               │ MCP Protocol          │ REST API
               ▼                       ▼
┌──────────────────────┐  ┌──────────────────────┐
│   mcp/               │  │   server/             │
│   MCP Server (stdio) │  │   FastAPI Server      │
│   API 转发层          │  │   :1984               │
│   不自开浏览器         │  │   管理浏览器          │
└──────────────────────┘  └──────────────────────┘
                                   │
                          ┌────────┴────────┐
                          │   Browser Pool   │
                          │  (Playwright)    │
                          │  max 5 instances │
                          └────────┬────────┘
                          ┌────────┴────────┐
                          │  Account Profiles │
                          │  data/profiles/   │
                          │  per-account     │
                          └─────────────────┘
```

## Project Structure

```
ai-control-panel/
├── server/                  # 主服务器代码
│   ├── main.py             # FastAPI 入口 + 33 个工具注册
│   ├── Dockerfile          # 魔塔/容器部署
│   ├── requirements.txt    # Python 依赖
│   ├── config.json         # 服务器配置
│   ├── start.bat / start.vbs  # 静默启动
│   ├── browser_agent/      # 浏览器控制核心
│   │   ├── browser_manager.py  # 浏览器池 + 看门狗
│   │   └── actions.py      # 纯函数：导航/点击/类型/生图/看图
│   ├── core/               # 核心基础设施
│   │   ├── server.py       # FastAPI 路由 + ai-summary
│   │   ├── registry.py     # 函数注册器
│   │   ├── event_bus.py    # 事件总线
│   │   └── task_queue.py   # 任务队列
│   ├── session/            # 会话管理
│   │   └── account_manager.py  # 账号 CRUD + cookie 管理
│   ├── proxy_providers/    # 代理供应商
│   ├── anti_detection/     # 反检测
│   ├── data/               # 运行时数据
│   │   ├── accounts.json   # 账号配置 + cookies
│   │   ├── profiles/       # 每个账号独立 Chromium 用户目录
│   │   └── vision_dir.json # 看图存储目录
│   ├── web/                # Web 控制面板
│   │   └── dashboard/      # HTML + JS 前端
│   └── output/             # 生成图片输出
│
├── mcp/                    # MCP 独立包（可发 PyPI）
│   ├── pyproject.toml      # 打包配置
│   ├── mcp_config.json     # AI 客户端 MCP 配置示例
│   ├── src/
│   │   └── ai_control_panel_mcp/
│   │       ├── __init__.py
│   │       └── server.py   # MCP 服务器（API 转发）
│   └── dist/               # 构建产物
│
├── docs/                   # 文档
│   └── development.md      # 开发日志
│
├── README.md
└── .gitignore
```

## Quick Start

### 1. 启动主服务器

```bash
cd server
pip install -r requirements.txt
python -m playwright install chromium
python main.py
```

访问 http://localhost:1984

### 2. MCP 配置（给 AI 用）

```json
{
  "mcpServers": {
    "ai-control-panel": {
      "command": "python",
      "args": ["mcp/src/ai_control_panel_mcp/server.py"],
      "env": {
        "AI_PANEL_URL": "http://127.0.0.1:1984"
      }
    }
  }
}
```

### 3. 账号配置

首次使用需手动登录一次：
- 打开 Web 面板 `http://localhost:1984`
- 添加账号 → 填写服务名和网址 → "打开浏览器并登录"
- 浏览器弹出 → 手动登录 → 点击"已完成登录，捕获信息"
- Cookies 保存后即可调用

## 已有账号

| 账号 | 能力 | 说明 |
|------|------|------|
| `acc_577cd0d2` | `generate_image`, `ask_vision` | 豆包 - 生图 + 看图 |
| `acc_8e8d58ef` | `generate_image` | 千问 - 仅生图 |

## Tools（33 个）

全部工具通过 `GET /api/ai-summary` 获取。关键工具：

| 工具 | 说明 |
|------|------|
| `browser_generate_image` | 生图（千问/豆包自动分流），同一账号连续调用保持聊天上下文 |
| `batch_generate_images` | 批量并行生图 |
| `browser_ask_vision` | 上传图片到豆包看图回答（文本 AI 的"眼睛"） |
| `list_accounts` | 列出账号及其 capabilities |
| `get_browser_pool_stats` | 浏览器池状态 |
| `set_vision_dir` / `get_vision_dir` | 看图存储目录 |

## 开发注意

### 关键修改记录

- **会话保持**：同一账号多次生图不刷新页面，保持聊天上下文 → 同角色一致性
- **去重下载**：多次生图只下载新增图片，不重复下载旧图
- **水印裁剪**：千问 / 豆包图片自动裁左上角 40px 水印
- **GPU 渲染**：headless 模式需保留 SwiftShader，不添加 `--disable-software-rasterizer`
- **系统代理**：Windows 上 Chromium 走系统代理，启动时临时禁用注册表 ProxyEnable，关闭时恢复
- **千问生图**：contenteditable 输入 → Enter → 进度检测 → CDN 图片下载
- **豆包生图**：点击"图像生成" → 输入 → 发送 → 轮询大图 → carousel 高清下载
- **豆包看图**：+ 按钮上传 → 输入问题 → Enter → 等待稳定文本

### 依赖

```
fastapi, uvicorn      # Web 服务器
playwright             # 浏览器自动化
aiohttp                # HTTP 客户端
Pillow                 # 图片处理（水印裁剪）
mcp                    # MCP 协议（mcp/ 包用）
```

### 启动方式

| 方式 | 命令 | 窗口 |
|------|------|------|
| 调试 | `python main.py` | 有终端 |
| 静默 | `start.vbs`（双击） | 无窗口 |
| ECS 部署 | `docker build -t ai-panel .` | 容器 |

---

*更新于 2026-05-28*
