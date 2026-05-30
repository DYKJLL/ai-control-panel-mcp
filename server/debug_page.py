import asyncio
import urllib.request
from playwright.async_api import async_playwright

TARGET_URL = "https://dsw-gateway-cn-hangzhou.data.aliyun.com/dsw-1922829/lab/workspaces/auto-p"

async def debug_page():
    import json

    async with async_playwright() as p:
        try:
            targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json").read().decode())
            print(f"发现 {len(targets)} 个页面")

            target_url = None
            for t in targets:
                print(f"  - {t.get('title', '无标题')}: {t.get('url', '')[:80]}")
                if TARGET_URL in t.get('url', ''):
                    target_url = t
                    break

            if not target_url:
                print(f"\n未找到目标页面。请在浏览器中打开: {TARGET_URL}")
                return

            ws_url = target_url.get('webSocketDebuggerUrl')
            print(f"\n正在连接到: {ws_url}")
            browser = await p.chromium.connect_over_cdp(ws_url)
        except Exception as e:
            print(f"连接失败: {e}")
            print("请先运行: msedge --remote-debugging-port=9222")
            return

        context = browser.contexts[0]
        pages = context.pages

        target_page = None
        for pg in pages:
            print(f"页面: {pg.url}")
            if TARGET_URL in pg.url:
                target_page = pg
                break

        if not target_page:
            print("未找到目标页面，请在浏览器中打开后再运行此脚本")
            return

        page = target_page
        print(f"\n找到目标页面: {page.url}")

        await asyncio.sleep(3)

        print("\n正在分析页面结构...")
        snapshot = await page.evaluate("""() => {
            const elements = [];
            const allElements = document.querySelectorAll('*');
            let id = 0;
            for (const el of allElements) {
                const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
                if (rect && rect.width > 0 && rect.height > 0) {
                    elements.push({
                        id: id,
                        tag: el.tagName,
                        text: el.textContent?.trim().substring(0, 80) || '',
                        className: el.className || '',
                        rect: {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height)
                        }
                    });
                }
                id++;
            }
            return elements;
        }""")

        print(f"\n获取到 {len(snapshot)} 个元素\n")

        print("=== 左侧区域元素 (x < 250) ===")
        left_elements = [e for e in snapshot if e['rect']['x'] < 250]
        for elem in sorted(left_elements, key=lambda x: x['rect']['x']):
            print(f"[{elem['id']}] {elem['tag']:15} x={elem['rect']['x']:4} y={elem['rect']['y']:4} w={elem['rect']['width']:4} h={elem['rect']['height']:4} | {elem['text'][:50]}")

        print("\n=== 所有可见文本元素 ===")
        text_elements = [e for e in snapshot if e['text'].strip() and len(e['text'].strip()) > 2]
        for elem in sorted(text_elements, key=lambda x: x['rect']['y'])[:50]:
            print(f"[{elem['id']}] {elem['tag']:15} x={elem['rect']['x']:4} y={elem['rect']['y']:4} | {elem['text'][:60]}")

asyncio.run(debug_page())
