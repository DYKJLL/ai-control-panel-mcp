import asyncio
import schedule
import time
import logging
from datetime import datetime

from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("auto_click")

TARGET_URL = "https://dsw-gateway-cn-hangzhou.data.aliyun.com/dsw-1922829/lab/workspaces/auto-p"
CLICK_INTERVAL_MINUTES = 20
CLICK_COUNT = 2


async def connect_and_click():
    logger.info(f"开始执行自动化任务: {datetime.now()}")
    async with async_playwright() as p:
        ws_url = "ws://127.0.0.1:9222"
        try:
            browser = await p.chromium.connect_over_cdp(ws_url)
            logger.info("已连接到现有浏览器")
        except Exception as e:
            logger.error(f"连接浏览器失败: {e}")
            logger.info("请确保Edge浏览器已启用远程调试模式")
            logger.info("启动Edge的命令: msedge --remote-debugging-port=9222")
            return

        contexts = browser.contexts
        if not contexts:
            logger.warning("没有找到浏览器上下文，尝试创建新页面")
            page = await browser.new_page()
        else:
            context = contexts[0]
            pages = context.pages
            target_page = None
            for pg in pages:
                if TARGET_URL in pg.url:
                    target_page = pg
                    break

            if target_page:
                page = target_page
                logger.info(f"找到已打开的目标页面: {page.url}")
            else:
                page = await context.new_page()
                logger.info("在现有上下文创建新页面")

        try:
            if TARGET_URL not in page.url:
                logger.info(f"正在导航到: {TARGET_URL}")
                await page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
                await asyncio.sleep(5)

            logger.info("等待页面加载完成...")
            await asyncio.sleep(3)

            snapshot = await page.evaluate("""() => {
                const elements = [];
                const allElements = document.querySelectorAll('*');
                let id = 0;
                for (const el of allElements) {
                    if (el.children.length === 0 || el.textContent.trim()) {
                        elements.push({
                            id: id++,
                            tag: el.tagName,
                            text: el.textContent?.trim().substring(0, 100) || '',
                            className: el.className || '',
                            ariaLabel: el.getAttribute('aria-label') || '',
                            role: el.getAttribute('role') || '',
                            rect: el.getBoundingClientRect ? {
                                x: el.getBoundingClientRect().x,
                                y: el.getBoundingClientRect().y,
                                width: el.getBoundingClientRect().width,
                                height: el.getBoundingClientRect().height
                            } : null
                        });
                    }
                }
                return elements;
            }""")

            left_panel_candidates = []
            for elem in snapshot:
                text = elem.get('text', '').lower()
                class_name = elem.get('className', '').lower()
                role = elem.get('role', '').lower()
                rect = elem.get('rect')

                if rect and rect.get('width') and rect.get('height'):
                    is_left = rect['x'] < 200 and rect['width'] > 30 and rect['height'] > 30
                    is_panel_related = any(keyword in text or keyword in class_name or keyword in role
                                          for keyword in ['panel', 'control', 'sidebar', 'menu', '导航', '侧边', '控制'])

                    if is_left and is_panel_related:
                        left_panel_candidates.append(elem)

            if left_panel_candidates:
                logger.info(f"找到 {len(left_panel_candidates)} 个左侧控制栏候选元素")
                for candidate in left_panel_candidates[:5]:
                    logger.info(f"  候选: [{candidate['id']}] {candidate['tag']} text='{candidate['text'][:50]}' class='{candidate['className'][:50]}'")

                for i in range(min(CLICK_COUNT, len(left_panel_candidates))):
                    elem = left_panel_candidates[i]
                    try:
                        await page.evaluate(f"document.querySelectorAll('*')[{elem['id']}].click()")
                        logger.info(f"点击 {i+1}/{CLICK_COUNT}: [{elem['id']}] {elem['tag']} text='{elem['text'][:30]}'")
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.warning(f"点击失败: {e}")
            else:
                logger.info("未找到明确的左侧控制栏，尝试点击页面左侧的可见元素...")

                left_elements = [e for e in snapshot if e.get('rect') and
                               e['rect']['x'] < 200 and e['rect']['width'] > 50 and e['rect']['height'] > 20
                               and e['text'].strip()]

                if left_elements:
                    for elem in left_elements[:10]:
                        logger.info(f"  左侧元素: [{elem['id']}] {elem['tag']} text='{elem['text'][:50]}'")

                    clicked_count = 0
                    for elem in left_elements:
                        if clicked_count >= CLICK_COUNT:
                            break
                        if elem['text'].strip() and len(elem['text'].strip()) > 1:
                            try:
                                await page.evaluate(f"document.querySelectorAll('*')[{elem['id']}].click()")
                                logger.info(f"点击 {clicked_count+1}/{CLICK_COUNT}: [{elem['id']}] {elem['tag']} text='{elem['text'][:30]}'")
                                clicked_count += 1
                                await asyncio.sleep(1)
                            except Exception as e:
                                logger.warning(f"点击失败: {e}")
                else:
                    logger.warning("未找到可点击的左侧元素")

            logger.info("任务执行完成")

        except Exception as e:
            logger.error(f"执行出错: {e}")


def run_async_task():
    asyncio.run(connect_and_click())


def main():
    logger.info(f"=== 自动化任务启动 ===")
    logger.info(f"目标网址: {TARGET_URL}")
    logger.info(f"执行间隔: 每{CLICK_INTERVAL_MINUTES}分钟")
    logger.info(f"点击次数: {CLICK_COUNT}次")
    logger.info(f"启动时间: {datetime.now()}")
    logger.info("将连接到已运行的Edge浏览器 (ws://127.0.0.1:9222)")

    logger.info("")
    logger.info("提示: 如果连接失败，需要重新启动Edge并启用远程调试:")
    logger.info("  关闭所有Edge窗口后运行:")
    logger.info("  msedge --remote-debugging-port=9222")
    logger.info("")

    run_async_task()

    schedule.every(CLICK_INTERVAL_MINUTES).minutes.do(run_async_task)

    logger.info("定时任务已设置，等待下次执行...")
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
