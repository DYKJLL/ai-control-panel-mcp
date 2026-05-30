import json
import random
import uuid
from pathlib import Path
from typing import Optional


FINGERPRINTS = [
    {
        "viewport": {"width": 1920, "height": 1080},
        "device_scale_factor": 1,
        "platform": "Win32",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
        "locale": "zh-CN",
        "timezone": "Asia/Shanghai",
        "canvas_noise": 0.0003,
        "webgl_noise": 0.0002,
    },
    {
        "viewport": {"width": 1920, "height": 1080},
        "device_scale_factor": 1,
        "platform": "Win32",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
        "locale": "en-US",
        "timezone": "America/New_York",
        "canvas_noise": 0.0005,
        "webgl_noise": 0.0001,
    },
    {
        "viewport": {"width": 1440, "height": 900},
        "device_scale_factor": 2,
        "platform": "MacIntel",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
        "locale": "zh-CN",
        "timezone": "Asia/Shanghai",
        "canvas_noise": 0.0002,
        "webgl_noise": 0.0004,
    },
]


class FingerprintManager:
    def __init__(self, storage_path: str = "data/fingerprints.json"):
        self._storage_path = Path(storage_path)
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._fingerprints: dict[str, dict] = {}
        self._load()

    def create(self, preset: int = None) -> str:
        if preset is not None and preset < len(FINGERPRINTS):
            fp = dict(FINGERPRINTS[preset])
        else:
            fp = dict(random.choice(FINGERPRINTS))
        fp["id"] = f"fp_{uuid.uuid4().hex[:8]}"
        self._fingerprints[fp["id"]] = fp
        self._save()
        return fp["id"]

    def get(self, fp_id: str) -> Optional[dict]:
        return self._fingerprints.get(fp_id)

    def get_or_create(self, fp_id: Optional[str] = None) -> dict:
        if fp_id and fp_id in self._fingerprints:
            return self._fingerprints[fp_id]
        new_id = self.create()
        return self._fingerprints[new_id]

    def rotate(self, fp_id: str) -> str:
        self._fingerprints.pop(fp_id, None)
        return self.create()

    def list(self) -> list[dict]:
        return list(self._fingerprints.values())

    def generate_stealth_js(self, fp_id: str) -> str:
        fp = self.get(fp_id)
        if not fp:
            return ""
        return f"""
// Canvas 噪声
const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
CanvasRenderingContext2D.prototype.getImageData = function(x, y, w, h) {{
    const data = origGetImageData.call(this, x, y, w, h);
    for (let i = 0; i < data.data.length; i += 4) {{
        data.data[i] += {fp['canvas_noise']};
        data.data[i+1] += {fp['canvas_noise']};
        data.data[i+2] += {fp['canvas_noise']};
    }}
    return data;
}};

// WebGL 噪声
const origGetParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(param) {{
    if (param === 37445) return 'Intel Inc.';
    if (param === 37446) return 'Intel Iris OpenGL Engine';
    return origGetParameter.call(this, param);
}};

// 隐藏 WebDriver
Object.defineProperty(navigator, 'webdriver', {{ get: () => false }});
Object.defineProperty(navigator, 'plugins', {{ get: () => [1,2,3,4,5] }});
Object.defineProperty(navigator, 'languages', {{ get: () => ['{fp['locale']}', 'en'] }});
"""

    def _save(self):
        data = {k: v for k, v in self._fingerprints.items()}
        self._storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self):
        if self._storage_path.exists():
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            self._fingerprints = data
