import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional


class Account:
    def __init__(self, service: str, label: str, url: str = "",
                 cookies: list = None, storage: dict = None, proxy_mode: str = "tor"):
        self.id = f"acc_{uuid.uuid4().hex[:8]}"
        self.service = service
        self.label = label
        self.url = url
        self.cookies = cookies or []
        self.storage = storage or {}
        self.proxy_mode = proxy_mode
        self.status = "active"
        self.created_at = time.time()
        self.last_check: Optional[float] = None
        self.daily_usage = 0
        self.error_count = 0
        self.login_history: list[dict] = []
        # 独立浏览器环境
        self.profile_dir: str = ""  # 自动生成
        self.fingerprint: dict = {}  # 自动生成

    def ensure_profile(self, base_dir: str = "data/profiles"):
        if not self.profile_dir:
            self.profile_dir = os.path.join(base_dir, self.id)
        if not self.fingerprint:
            from browser_agent.fingerprint import generate_fingerprint
            self.fingerprint = generate_fingerprint(seed=self.id)

    def to_dict(self) -> dict:
        caps = []
        if self.url:
            if "doubao.com" in self.url:
                caps = ["generate_image", "ask_vision"]
            elif "qianwen.com" in self.url:
                caps = ["generate_image"]
        return {
            "id": self.id,
            "service": self.service,
            "label": self.label,
            "url": self.url,
            "capabilities": caps,
            "status": self.status,
            "proxy_mode": self.proxy_mode,
            "has_cookies": len(self.cookies) > 0,
            "cookie_count": len(self.cookies),
            "profile_dir": self.profile_dir or "",
            "created_at": self.created_at,
            "last_check": self.last_check,
            "daily_usage": self.daily_usage,
            "error_count": self.error_count,
            "login_history": self.login_history[-5:],
        }

    def add_login_record(self, success: bool, url: str = "", note: str = ""):
        self.login_history.append({
            "time": time.time(),
            "success": success,
            "url": url,
            "note": note,
        })
        if len(self.login_history) > 50:
            self.login_history = self.login_history[-50:]


class AccountManager:
    def __init__(self, storage_path: str = "data/accounts.json"):
        self._storage_path = Path(storage_path)
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._accounts: dict[str, Account] = {}
        self._load()

    def add_account(self, service: str, label: str, url: str = "",
                    cookies: list = None, storage: dict = None) -> Account:
        account = Account(service, label, url=url, cookies=cookies, storage=storage)
        self._accounts[account.id] = account
        self.save()
        return account

    def get_account(self, account_id: str) -> Optional[Account]:
        return self._accounts.get(account_id)

    def list_accounts(self, service: str = None) -> list[dict]:
        accounts = self._accounts.values()
        if service:
            accounts = [a for a in accounts if a.service == service]
        return [a.to_dict() for a in accounts]

    def remove_account(self, account_id: str):
        self._accounts.pop(account_id, None)
        self.save()

    def update_cookies(self, account_id: str, cookies: list, storage: dict = None):
        account = self._accounts.get(account_id)
        if account:
            account.cookies = cookies
            if storage:
                account.storage = storage
            account.last_check = time.time()
            account.status = "active"
            account.add_login_record(True, url=account.url, note="cookies_updated")
            self.save()

    def update_url(self, account_id: str, url: str):
        account = self._accounts.get(account_id)
        if account:
            account.url = url
            self.save()

    def mark_inactive(self, account_id: str):
        account = self._accounts.get(account_id)
        if account:
            account.status = "inactive"
            account.error_count += 1
            self.save()

    def get_available(self, service: str) -> Optional[Account]:
        for acc in self._accounts.values():
            if acc.service == service and acc.status == "active" and acc.cookies:
                return acc
        return None

    def save(self):
        data = {}
        for aid, acc in self._accounts.items():
            data[aid] = {
                "id": acc.id,
                "service": acc.service,
                "label": acc.label,
                "url": acc.url,
                "cookies": acc.cookies,
                "storage": acc.storage,
                "proxy_mode": acc.proxy_mode,
                "status": acc.status,
                "created_at": acc.created_at,
                "last_check": acc.last_check,
                "daily_usage": acc.daily_usage,
                "error_count": acc.error_count,
                "login_history": acc.login_history,
                "profile_dir": acc.profile_dir,
                "fingerprint": acc.fingerprint,
            }
        self._storage_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load(self):
        if self._storage_path.exists():
            data = json.loads(self._storage_path.read_text(encoding="utf-8-sig"))
            for aid, d in data.items():
                acc = Account(d["service"], d.get("label", d["service"]), url=d.get("url", ""))
                acc.id = d["id"]
                acc.cookies = d.get("cookies", [])
                acc.storage = d.get("storage", {})
                acc.proxy_mode = d.get("proxy_mode", "tor")
                acc.status = d.get("status", "active")
                acc.created_at = d.get("created_at", time.time())
                acc.last_check = d.get("last_check")
                acc.daily_usage = d.get("daily_usage", 0)
                acc.error_count = d.get("error_count", 0)
                acc.login_history = d.get("login_history", [])
                acc.profile_dir = d.get("profile_dir", "")
                acc.fingerprint = d.get("fingerprint", {})
                self._accounts[aid] = acc
