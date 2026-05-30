# 开发日志

## 架构决策

### 为什么 MCP 不自开浏览器？
- 避免与主服务器冲突（共用 Chromium profile）
- MCP 只是转发层，真正的浏览器由主服务器管理
- 主服务器不启动时 MCP 不可用（报错提示）

### 为什么用 Playwright 而非 CloakBrowser？
- CloakBrowser 是 C++ 补丁，某些环境下不可用
- Playwright 内置 Chromium，跨平台一致
- 有自动 fallback：CloakBrowser → Playwright

### 为什么同账号不刷新页面？
- 千问/豆包在同一聊天会话中能保持角色一致性
- 连续生图时，AI 记住之前的角色设定
- 见 `acquire()` 方法：已有实例时不复导航到 URL

## 已知问题

### 豆包每日配额
- "今天的生图次数已达到上限" 时需等待次日重置
- 或用不同账号

### 千问无 visual 能力
- 千问只有 `generate_image`，没有 `ask_vision`
- 看图功能必须走豆包账号

### Windows 代理冲突
- Chromium 尊重 Windows 系统代理
- Clash 等客户端开启时会阻断 Chromium
- 解决：启动浏览器前临时禁用注册表 `ProxyEnable`，关闭时恢复

### GBK 中文乱码
- Windows PowerShell 输出中文字符乱码
- 日志保存到文件再查看

## 环境要求

### 硬件
- 操作系统：Windows 10+ / Linux
- GPU：推荐 NVIDIA 4GB+（非必须，有 SwiftShader 软件渲染）
- 网络：可访问 qianwen.com / doubao.com

### 软件
- Python 3.10+
- Chromium（Playwright 自动安装）
- Windows 可选：CloakBrowser

## 测试

### 千问生图
1. 打开浏览器 `http://localhost:1984`
2. 调用 `browser_generate_image(account_id="acc_8e8d58ef", prompt="测试图片")`
3. 检查 `output/qianwen_*.png`

### 豆包生图
1. 调用 `browser_generate_image(account_id="acc_577cd0d2", prompt="测试图片")`
2. 检查 `output/doubao_*.png`

### 豆包看图
1. 调用 `get_vision_dir` → `set_vision_dir`
2. 调用 `browser_ask_vision(image_source="图片路径", question="这是什么")`
3. 检查返回的文本回答
