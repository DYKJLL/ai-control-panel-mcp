import asyncio
import logging
import os
from playwright.async_api import Page

logger = logging.getLogger(__name__)


async def navigate(page: Page, url: str) -> dict:
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)
    return {"status": "navigated", "url": url}


async def click_target(page: Page, target: dict) -> dict:
    pid = target.get("id")
    text = target.get("text")
    selector = target.get("selector")
    if pid is not None:
        return await _click_by_id(page, pid)
    elif text:
        return await _click_by_text_js(page, text)
    elif selector:
        return await _click_by_selector(page, selector)
    return {"error": "no valid target"}


async def _click_by_id(page: Page, pid: int) -> dict:
    btns = await page.query_selector_all("button, [role=button], a, label")
    if pid < len(btns):
        await btns[pid].scroll_into_view_if_needed()
        await btns[pid].click()
        text = (await btns[pid].inner_text()).strip()[:30]
        return {"status": "clicked", "id": pid, "text": text}
    return {"error": f"element {pid} not found, only {len(btns)} elements"}


async def _click_by_text_js(page: Page, text: str) -> dict:
    clean = text.strip()
    try:
        result = await page.evaluate("""
            (target) => {
                const items = document.querySelectorAll('button, [role=button], a, label, span, div, [contenteditable]');
                const clean = target.replace(/[\\s\\u200b\\ufeff\\u00a0]/g, '');
                for (const el of items) {
                    const t = (el.innerText || el.textContent || '').trim().replace(/[\\s\\u200b\\ufeff\\u00a0]/g, '');
                    if (t === clean || t.includes(clean)) {
                        el.scrollIntoView({block:'center', behavior:'instant'});
                        setTimeout(() => el.click(), 100);
                        return true;
                    }
                }
                return false;
            }
        """, clean)
        if result:
            await page.wait_for_timeout(300)
            return {"status": "clicked", "match": "js_eval", "text": clean[:30]}
    except Exception as e:
        logger.warning(f"JS click_by_text error: {e}")
    return {"error": f"text '{text}' not found"}


async def _click_by_selector(page: Page, selector: str) -> dict:
    try:
        await page.click(selector, timeout=5000)
        return {"status": "clicked", "selector": selector}
    except Exception as e:
        return {"error": str(e)}


async def type_text(page: Page, text: str, target: dict = None) -> dict:
    pid = target.get("id") if target else None
    selector = target.get("selector") if target else None
    elem = None
    if pid is not None:
        all_inputs = await page.query_selector_all(
            "textarea, [contenteditable=true], input:not([type=hidden])"
        )
        if pid < len(all_inputs):
            elem = all_inputs[pid]
    elif selector:
        elem = await page.query_selector(selector)
    else:
        elem = await page.query_selector("textarea, [contenteditable=true]")
    if not elem:
        return {"error": "target input not found"}
    await elem.scroll_into_view_if_needed()
    await elem.click()
    await elem.fill("")
    await elem.type(text, delay=30)
    return {"status": "typed", "text_length": len(text)}


async def press_key(page: Page, key: str) -> dict:
    await page.keyboard.press(key)
    return {"status": "pressed", "key": key}


async def screenshot(page: Page, path: str = None) -> dict:
    if not path:
        import tempfile
        path = os.path.join(tempfile.gettempdir(), "browser_shot.png")
    await page.screenshot(path=path, full_page=True)
    return {"path": path}


async def generate_image(page: Page, prompt: str, output_dir: str = "output") -> dict:
    current_url = page.url
    if "qianwen.com" in current_url:
        return await _generate_image_qianwen(page, prompt, output_dir)
    return await _generate_image_doubao(page, prompt, output_dir)


async def _generate_image_qianwen(page: Page, prompt: str, output_dir: str = "output") -> dict:
    await asyncio.sleep(2)

    # 记录当前已有 CDN 图片 URL
    before_srcs = set(await page.evaluate("""
        Array.from(document.querySelectorAll('img'))
            .map(i => i.currentSrc || i.src || '')
            .filter(s => s.includes('workspace-zb-cdn.qianwen.com') && !s.includes('avatar'))
    """))

    ce = page.locator('[contenteditable=true]').first
    await ce.click()
    await ce.fill(prompt)
    await asyncio.sleep(0.5)
    await page.keyboard.press("Enter")

    # Wait for generation: progress bar → 100% → final images
    import re
    max_pct = 0
    for i in range(90):
        await asyncio.sleep(2)
        try:
            text = await page.inner_text("body")
            pct_match = re.search(r"(\d+)%", text)
            if pct_match:
                max_pct = max(max_pct, int(pct_match.group(1)))

            # 只检测千问 CDN 的图片
            final = await page.evaluate("""
                Array.from(document.querySelectorAll('img'))
                    .filter(i => {
                        const s = i.currentSrc || i.src || '';
                        return s.includes('workspace-zb-cdn.qianwen.com') && !s.includes('avatar');
                    })
                    .map(i => ({ src: i.currentSrc || i.src, w: i.naturalWidth || i.width, h: i.naturalHeight || i.height }))
            """)
            if final:
                result_images = final
                break
        except Exception:
            pass
    else:
        if max_pct > 0:
            return {"error": f"generation stuck at {max_pct}%"}
        return {"error": "no response from AI", "waited_seconds": 180}

    # 去重：只下载新增的图片
    new_images = [im for im in result_images if im["src"] not in before_srcs]
    if not new_images:
        return {"status": "success", "images": [], "total": 0, "note": "no new images"}

    os.makedirs(output_dir, exist_ok=True)
    downloaded = []
    import base64

    # 从已有文件确定起始编号
    import re as _re
    existing_nums = []
    for f in os.listdir(output_dir):
        m = _re.match(r"qianwen_(\d+)\.png", f)
        if m:
            existing_nums.append(int(m.group(1)))
    start_idx = max(existing_nums) if existing_nums else 0

    for idx, item in enumerate(new_images):
        fname = os.path.join(output_dir, f"qianwen_{start_idx + idx + 1}.png")
        try:
            b64 = await page.evaluate("""async (url) => {
                const resp = await fetch(url);
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                const blob = await resp.blob();
                return new Promise((resolve) => {
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(reader.result);
                    reader.readAsDataURL(blob);
                });
            }""", item["src"])
            raw = base64.b64decode(b64.split(",", 1)[1])
            with open(fname, "wb") as f:
                f.write(raw)

            _crop_watermark(fname)  # remove watermark if present
            sz = f"{item.get('w', '?')}x{item.get('h', '?')}"
            downloaded.append({"file": fname, "src": item["src"][:100], "size": sz})
        except Exception as e:
            downloaded.append({"file": None, "src": item["src"][:80], "error": str(e)})

    return {"status": "success", "images": downloaded, "total": len(downloaded)}


async def _generate_image_doubao(page: Page, prompt: str, output_dir: str = "output") -> dict:
    await asyncio.sleep(2)

    # Click 图像生成 in the footer toolbar (if not already in image mode, no-op if already selected)
    await page.evaluate('''() => {
        const btn = Array.from(document.querySelectorAll("button")).find(el =>
            el.textContent.trim() === "图像生成" && el.offsetParent !== null
        );
        if (btn) { btn.click(); return true; }
        return false;
    }''')
    await asyncio.sleep(2)

    # Type prompt into the visible contenteditable div via Playwright fill
    ce = page.locator('[contenteditable=true]')
    if await ce.count():
        await ce.click()
        await ce.fill(prompt)
    else:
        ta = page.locator('textarea')
        if await ta.count():
            await ta.click()
            await ta.fill(prompt)
        else:
            return {"error": "input area not found"}

    await asyncio.sleep(0.5)
    await page.keyboard.press("Enter")
    await asyncio.sleep(1)

    still_visible = await page.evaluate('() => (document.querySelector(\'[contenteditable=true]\')?.textContent || "").length > 0')
    if still_visible:
        await page.evaluate('''() => {
            const sendBtn = Array.from(document.querySelectorAll("button")).find(b => {
                const html = b.innerHTML;
                return html.includes("M12.0005") && html.includes("10.9951H20.75") && b.offsetParent !== null;
            });
            if (sendBtn) sendBtn.click();
        }''')

    result_images = []
    for i in range(120):
        await asyncio.sleep(0.5)
        try:
            images = await page.evaluate("""
                Array.from(document.querySelectorAll('img'))
                    .map(img => {
                        const r = img.getBoundingClientRect();
                        return { src: img.src, w: Math.round(r.width), h: Math.round(r.height), visible: r.width > 10 && r.height > 10 };
                    })
                    .filter(img => img.visible && !img.src.includes('avatar') && !img.src.includes('data:'))
            """)
            large = [img for img in images if img.get("w", 0) > 150 and img.get("h", 0) > 150]
            for img in large:
                if img["src"] not in [r["src"] for r in result_images]:
                    result_images.append(img)
            if len(result_images) >= 2:
                stable = True
                for j in range(3):
                    await asyncio.sleep(0.5)
                    check = await page.evaluate("""
                        Array.from(document.querySelectorAll('img'))
                            .map(img => { const r=img.getBoundingClientRect(); return {src:img.src,w:Math.round(r.width),h:Math.round(r.height),visible:r.width>10&&r.height>10}; })
                            .filter(img => img.visible && !img.src.includes('avatar') && !img.src.includes('data:') && img.w > 150 && img.h > 150)
                    """)
                    if len(check) != len(result_images):
                        stable = False
                        result_images = check
                        break
                if stable:
                    break
        except Exception:
            pass

    if not result_images:
        return {"error": "no images generated", "waited_seconds": 60}

    os.makedirs(output_dir, exist_ok=True)
    downloaded = []
    import base64

    # Capture high-res images from the preview carousel.
    high_res_urls = []
    for i in range(min(4, len(result_images))):
        await page.evaluate(f'''() => {{
            const wrappers = document.querySelectorAll('[class*=clickable]');
            if (wrappers.length > {i}) {{
                wrappers[{i}].click();
                return true;
            }}
            return false;
        }}''')

        for _ in range(20):
            hr = await page.evaluate('''() => {
                const big = Array.from(document.querySelectorAll('img'))
                    .filter(i => (i.src||'').includes('byteimg.com') || (i.src||'').includes('tos-cn-i'))
                    .find(i => i.naturalWidth > 1000);
                if (!big) return null;
                return { src: big.currentSrc, w: big.naturalWidth, h: big.naturalHeight };
            }''')
            if hr:
                high_res_urls.append(hr)
                break
            await asyncio.sleep(0.5)

        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)

    target = high_res_urls if high_res_urls else [{"src": im["src"]} for im in result_images]
    for idx, item in enumerate(target):
        fname = os.path.join(output_dir, f"doubao_{idx+1}.png")
        try:
            b64 = await page.evaluate("""async (url) => {
                const resp = await fetch(url);
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                const blob = await resp.blob();
                return new Promise((resolve) => {
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(reader.result);
                    reader.readAsDataURL(blob);
                });
            }""", item["src"])
            raw = base64.b64decode(b64.split(",", 1)[1])
            with open(fname, "wb") as f:
                f.write(raw)
            _crop_watermark(fname)
            sz = f"{item.get('w', '?')}x{item.get('h', '?')}"
            downloaded.append({"file": fname, "src": item["src"][:100], "size": sz})
        except Exception as e:
            downloaded.append({"file": None, "src": item["src"][:80], "error": str(e)})

    return {"status": "success", "images": downloaded, "total": len(downloaded)}


def _crop_watermark(filepath: str, crop_px: int = 40):
    """裁剪左上角水印"""
    try:
        from PIL import Image
        from io import BytesIO
        with open(filepath, "rb") as f:
            img = Image.open(f)
            img.load()
        w, h = img.size
        if w > crop_px * 2 and h > crop_px * 2:
            cropped = img.crop((crop_px, crop_px, w, h))
            cropped.save(filepath, quality=95)
    except Exception:
        pass


def _get_vision_dir(account_id: str = "default") -> str:
    """获取当前配置的存储目录，默认 output"""
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "data", "vision_dir.json")
    try:
        if os.path.exists(cfg_path):
            import json
            cfg = json.loads(open(cfg_path, encoding="utf-8").read())
            return cfg.get(account_id, cfg.get("default", "output"))
    except Exception:
        pass
    return "output"

def _set_vision_dir(account_id: str, path: str) -> dict:
    """设置存储目录"""
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "data", "vision_dir.json")
    try:
        import json
        cfg = {}
        if os.path.exists(cfg_path):
            cfg = json.loads(open(cfg_path, encoding="utf-8").read())
        cfg[account_id] = path
        open(cfg_path, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))
        return {"status": "ok", "path": path}
    except Exception as e:
        return {"error": str(e)}

async def _save_image(image_source: str, output_dir: str = "output") -> str:
    """下载URL图片或保存base64图片到本地，返回本地路径"""
    os.makedirs(output_dir, exist_ok=True)
    import hashlib
    import urllib.request
    import base64
    if image_source.startswith("http://") or image_source.startswith("https://"):
        name_hash = hashlib.md5(image_source.encode()).hexdigest()[:8]
        fname = os.path.join(output_dir, f"vision_{name_hash}.png")
        urllib.request.urlretrieve(image_source, fname)
        return fname
    if image_source.startswith("data:image") or len(image_source) > 1000:
        header, sep = image_source.split(",", 1) if "," in image_source else ("", image_source)
        raw = base64.b64decode(sep)
        fname = os.path.join(output_dir, f"vision_{hashlib.md5(raw).hexdigest()[:8]}.png")
        with open(fname, "wb") as f:
            f.write(raw)
        return fname
    # 已是本地路径
    if os.path.exists(image_source):
        return image_source
    raise ValueError(f"无法识别图片来源: {image_source[:60]}")


UI_NOISE = {'快速新', 'PPT 生成', '图像生成', '帮我写作', '更多', '超能模式Beta', 'Beta',
            '下载电脑版', '用户916112', '新对话', '在此处拖放文件', '解释图片',
            '有什么我能帮你的吗？', '文件数量', '登录'}


async def ask_vision(page: Page, image_source: str, question: str, account_id: str = "acc_577cd0d2", output_dir: str = None) -> dict:
    """上传图片到豆包 → 提问 → 读取AI回复（给无视觉AI当眼睛）"""
    if output_dir is None:
        output_dir = _get_vision_dir(account_id)
    try:
        local_path = await _save_image(image_source, output_dir)
    except Exception as e:
        return {"error": f"图片保存失败: {e}"}

    # 1. 聚焦输入框
    ta = await page.query_selector("textarea")
    if not ta:
        return {"error": "找不到输入框"}
    await ta.focus()
    await asyncio.sleep(0.5)

    # 2. 点击 + 按钮打开附件面板
    # 按钮特征：在输入框左边，包含 SVG，无文字，尺寸约 36x36
    plus_handle = await page.evaluate_handle("""
        () => {
            const ta = document.querySelector('textarea');
            if (!ta) return null;
            const taRect = ta.getBoundingClientRect();
            const btns = Array.from(document.querySelectorAll('button'));
            for (const b of btns) {
                const r = b.getBoundingClientRect();
                if (r.x < taRect.x && r.width < 50 && r.width > 20
                    && Math.abs(r.y - taRect.y) < 60
                    && !(b.textContent||'').trim()
                    && (b.innerHTML||'').includes('svg')) {
                    return b;
                }
            }
            return null;
        }
    """)
    if not plus_handle:
        return {"error": "找不到 + 按钮"}
    await plus_handle.as_element().click(timeout=5000)

    # 等待上传面板出现（轮询 0.5s 间隔，最多 6s）
    fi = None
    for _ in range(12):
        fi = await page.query_selector("input[type=file]")
        if fi:
            break
        await asyncio.sleep(0.5)
    if not fi:
        return {"error": "上传面板未打开"}

    # 3. 上传图片
    try:
        await fi.set_input_files(local_path, timeout=15000)
    except Exception as e:
        return {"error": f"图片上传失败: {e}"}

    # 等待上传完成（最多 4s）
    for _ in range(8):
        upload_done = await page.evaluate("!!document.querySelector('.semi-image img, img[src*=\"blob:\"], [class*=\"upload\"] img')")
        if upload_done:
            break
        await asyncio.sleep(0.5)

    # 4. 捕获发送前的页面文本
    body_before = await page.evaluate("document.body.innerText")

    # 5. 输入问题
    await page.evaluate("""
        (text) => {
            const ta = document.querySelector('textarea');
            if (!ta) return;
            ta.value = text;
            ta.dispatchEvent(new Event('input', {bubbles: true}));
            ta.focus();
        }
    """, question)
    await asyncio.sleep(0.2)
    await page.keyboard.press("Enter")

    # 6. 轮询新文本（AI 回复，0.5s 间隔，等待稳定）
    last_text = ""
    stable_count = 0
    answer = ""
    for i in range(60):
        await asyncio.sleep(0.5)
        body_now = await page.evaluate("document.body.innerText")
        diff = len(body_now) - len(body_before)
        if diff > 10:
            # 新文本在 body 末尾
            new_text = body_now[len(body_before):] if len(body_now) >= len(body_before) else ""
            lines = new_text.split("\n")
            clean_lines = [l.strip() for l in lines if len(l.strip()) > 10 and l.strip() not in UI_NOISE]
            if clean_lines:
                current = "\n".join(clean_lines)
                if current == last_text:
                    stable_count += 1
                else:
                    last_text = current
                    answer = current
                    stable_count = 0
                if stable_count >= 3:
                    logger.info(f"ask_vision 获取到回复 ({len(answer)} 字符)")
                    return {"answer": answer, "question": question[:50]}

    if answer:
        return {"answer": answer, "question": question[:50], "truncated": True}
    return {"error": "未在30秒内获取到AI回复", "question": question[:50]}
