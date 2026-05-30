import random
import json
import os
from pathlib import Path


# 真实 GPU 组合池（WebGL vendor + renderer）
GPU_POOL = [
    ("Google Inc. (NVIDIA)", "NVIDIA GeForce RTX 4060"),
    ("Google Inc. (NVIDIA)", "NVIDIA GeForce RTX 4070"),
    ("Google Inc. (NVIDIA)", "NVIDIA GeForce RTX 4080"),
    ("Google Inc. (NVIDIA)", "NVIDIA GeForce RTX 3060 Ti"),
    ("Google Inc. (AMD)", "AMD Radeon RX 7800 XT"),
    ("Google Inc. (AMD)", "AMD Radeon RX 7600"),
    ("Google Inc. (Intel)", "Intel(R) UHD Graphics 770"),
    ("Google Inc. (Intel)", "Intel(R) Iris Xe Graphics"),
    ("Google Inc. (Apple)", "Apple M1"),
    ("Google Inc. (Apple)", "Apple M2 Pro"),
    ("Google Inc. (Apple)", "Apple M3 Max"),
]

SCREEN_POOL = [
    {"width": 1920, "height": 1080, "availWidth": 1920, "availHeight": 1040},
    {"width": 2560, "height": 1440, "availWidth": 2560, "availHeight": 1400},
    {"width": 1920, "height": 1200, "availWidth": 1920, "availHeight": 1160},
    {"width": 1440, "height": 900, "availWidth": 1440, "availHeight": 860},
    {"width": 1366, "height": 768, "availWidth": 1366, "availHeight": 728},
    {"width": 1680, "height": 1050, "availWidth": 1680, "availHeight": 1010},
    {"width": 1536, "height": 864, "availWidth": 1536, "availHeight": 824},
]

UA_POOL = [
    # Chrome 131 on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Chrome 130 on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Chrome 131 on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Edge 131 on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
]

MEMORY_OPTIONS = [4, 8, 16, 32]
CPU_OPTIONS = [4, 8, 12, 16]
TOUCH_OPTIONS = [0, 0, 0, 0, 1]


def generate_fingerprint(seed: str = None) -> dict:
    """为账号生成唯一且稳定的指纹配置"""
    if seed:
        rng = random.Random(seed)
    else:
        rng = random.Random()

    gpu = rng.choice(GPU_POOL)
    screen = rng.choice(SCREEN_POOL)
    ua = rng.choice(UA_POOL)

    return {
        "webgl_vendor": gpu[0],
        "webgl_renderer": gpu[1],
        "screen_width": screen["width"],
        "screen_height": screen["height"],
        "screen_avail_width": screen["availWidth"],
        "screen_avail_height": screen["availHeight"],
        "user_agent": ua,
        "device_memory": rng.choice(MEMORY_OPTIONS),
        "hardware_concurrency": rng.choice(CPU_OPTIONS),
        "max_touch_points": rng.choice(TOUCH_OPTIONS),
        "canvas_noise_seed": rng.randint(0, 99999),
        "audio_noise_seed": rng.randint(0, 99999),
        "plugins_count": rng.randint(3, 5),
    }


def build_fingerprint_script(fp: dict) -> str:
    """根据指纹配置生成 JS 反检测脚本（最小入侵，不破坏页面功能）"""
    return f"""
    (() => {{
        // 1. 隐藏自动化标志
        Object.defineProperty(navigator, 'webdriver', {{ get: () => false }});
        try {{ delete navigator.__proto__.webdriver; }} catch(e) {{}}

        // 2. 伪装 plugins（被动检测，不影响功能）
        const pnames = ['Chrome PDF Plugin','Chrome PDF Viewer','Native Client'];
        const p = Object.create(PluginArray.prototype);
        const cnt = Math.min({fp['plugins_count']}, 3);
        for (let i = 0; i < cnt; i++) {{
            p[i] = {{ name: pnames[i], description: pnames[i], filename: pnames[i]+'.dll', length: 1 }};
        }}
        p.length = cnt;
        p.item = i => p[i] || null;
        p.namedItem = n => null;
        p.refresh = () => {{}};
        Object.defineProperty(navigator, 'plugins', {{ get: () => p }});

        // 3. 语言设置（被动）
        Object.defineProperty(navigator, 'languages', {{ get: () => ['zh-CN', 'zh'] }});

        // 4. 硬件信息（被动）
        Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {fp['device_memory']} }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {fp['hardware_concurrency']} }});
        Object.defineProperty(navigator, 'maxTouchPoints', {{ get: () => {fp['max_touch_points']} }});

        // 5. Chrome runtime 对象（被动）
        if (!window.chrome) window.chrome = {{}};
        if (!window.chrome.runtime) window.chrome.runtime = {{}};

        // 6. WebGL 仅伪造 vendor/renderer（不拦截 getContext，不破坏 canvas 功能）
        const origGetContext = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function(type, attrs) {{
            const ctx = origGetContext.call(this, type, attrs);
            if (ctx && type === 'webgl') {{
                const origGetParam = ctx.getParameter.bind(ctx);
                ctx.getParameter = function(p) {{
                    if (p === 37445) return '{fp['webgl_vendor']}';
                    if (p === 37446) return '{fp['webgl_renderer']}';
                    return origGetParam(p);
                }};
            }}
            return ctx;
        }};

        // 7. 权限（安全）
        if (navigator.permissions) {{
            const origQ = navigator.permissions.query;
            navigator.permissions.query = (p) => {{
                if (p.name === 'notifications' || p.name === 'clipboard-write')
                    return Promise.resolve({{ state: 'granted' }});
                return origQ.call(navigator.permissions, p);
            }};
        }}
    }})();
    """
