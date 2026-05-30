import logging
from typing import Optional
from playwright.async_api import Page

logger = logging.getLogger(__name__)


class PageAnalyzer:
    def __init__(self, page: Optional[Page] = None):
        self._page = page

    def bind(self, page: Page):
        self._page = page

    async def extract_elements(self) -> list[dict]:
        if not self._page:
            return []
        return await self._page.evaluate("""
            (() => {
                const items = [];
                const seen = new Set();

                const selectors = [
                    'button', '[role=button]', 'a', 'textarea',
                    '[contenteditable=true]', 'input:not([type=hidden])',
                    'select', 'label', 'summary', '[tabindex]',
                ].join(', ');

                const els = document.querySelectorAll(selectors);
                els.forEach((el, idx) => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 5 || rect.height < 5) return;

                    const tag = el.tagName.toLowerCase();
                    const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').substring(0, 80);
                    const type = el.type || '';
                    const placeholder = el.placeholder || '';
                    const role = el.getAttribute('role') || '';
                    const aria = el.getAttribute('aria-label') || '';
                    const href = el.getAttribute('href') || '';

                    const key = tag + text + type;
                    if (seen.has(key)) return;
                    seen.add(key);

                    items.push({
                        id: idx,
                        tag: tag,
                        text: text.substring(0, 40),
                        type: type,
                        placeholder: placeholder,
                        role: role,
                        aria_label: aria,
                        href: href.substring(0, 60),
                        visible: rect.width > 0 && rect.height > 0,
                        position: {
                            x: Math.round(rect.x), y: Math.round(rect.y),
                            w: Math.round(rect.width), h: Math.round(rect.height)
                        },
                        hint: _describe(el, tag, text, placeholder)
                    });
                });

                function _describe(el, tag, text, placeholder) {
                    const rect = el.getBoundingClientRect();
                    const vh = window.innerHeight;
                    const vw = window.innerWidth;
                    const vertical = rect.y < vh * 0.3 ? '顶部' :
                        rect.y < vh * 0.7 ? '中部' : '底部';
                    const horizontal = rect.x < vw * 0.3 ? '左侧' :
                        rect.x < vw * 0.7 ? '中间' : '右侧';
                    const desc = text ? `「${text.substring(0, 15)}」` :
                        placeholder ? `「${placeholder}」` : tag;
                    return `${vertical}${horizontal}的${tag} ${desc}`;
                }

                return items;
            })()
        """)

    async def extract_images(self) -> list[dict]:
        if not self._page:
            return []
        return await self._page.evaluate("""
            Array.from(document.querySelectorAll('img'))
                .map((img, idx) => {
                    const rect = img.getBoundingClientRect();
                    const src = img.src || '';
                    const alt = img.alt || '';
                    const isLarge = rect.width > 200 && rect.height > 200;
                    const isGenerated = src.includes('image_generation') ||
                                        src.includes('ocean-cloud') ||
                                        src.includes('ai生成') ||
                                        (isLarge && !src.includes('avatar'));
                    return {
                        id: idx,
                        src: src.substring(0, 200),
                        alt: alt,
                        visible: rect.width > 10 && rect.height > 10,
                        size: {w: Math.round(rect.width), h: Math.round(rect.height)},
                        is_generated: isGenerated
                    };
                })
                .filter(img => img.visible && img.src && !img.src.startsWith('data:'));
        """)

    async def extract_text(self) -> str:
        if not self._page:
            return ""
        texts = await self._page.evaluate("""
            Array.from(document.querySelectorAll('p, h1, h2, h3, h4, span, div, li'))
                .map(el => el.innerText.trim())
                .filter(t => t.length > 3 && t.length < 200)
                .slice(0, 30)
        """)
        return "\n".join(texts[:20])

    async def snapshot(self, include_screenshot: bool = False) -> dict:
        if not self._page:
            return {"error": "no page"}

        elements = await self.extract_elements()
        images = await self.extract_images()

        result = {
            "url": self._page.url,
            "title": await self._page.title(),
            "elements": elements,
            "images": images,
            "summary": {
                "interactive_elements": len(elements),
                "images_on_page": len(images),
                "generated_images": len([i for i in images if i.get("is_generated")]),
            },
            "page_text_preview": (await self.extract_text())[:500],
        }

        if include_screenshot:
            import base64, tempfile, os
            path = os.path.join(tempfile.gettempdir(), "browser_snapshot.png")
            await self._page.screenshot(path=path, full_page=True)
            with open(path, "rb") as f:
                result["screenshot_base64"] = base64.b64encode(f.read()).decode()
            os.remove(path)

        return result

    async def diff(self, prev: dict) -> dict:
        current = await self.snapshot()
        changes = {
            "url_changed": current["url"] != prev.get("url"),
            "title_changed": current["title"] != prev.get("title"),
            "new_images": [i for i in current.get("images", [])
                           if i not in prev.get("images", [])],
            "new_elements": [e for e in current.get("elements", [])
                             if e not in prev.get("elements", [])],
        }
        return changes
