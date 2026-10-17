"""Cấu hình chạy. API key KHÔNG nằm trong mã nguồn hay thư mục project. Thứ tự ưu tiên (giống Neko Core):
1. biến môi trường OPENROUTER_API_KEY (hoặc QWENCLOUD_API_KEY) - dùng khi chấm tự động,
2. key đã lưu ở ~/.chaldea/config.json (thư mục người dùng) sau khi nhập bằng /api (tự lưu).
Nhập key mới bằng /api sẽ ghi đè key đã lưu.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

USER_CONFIG = Path.home() / ".chaldea" / "config.json"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
QWENCLOUD_URL = "https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1/chat/completions"


@dataclass
class Settings:
    api_key: str = ""
    model: str = "qwen/qwen3.7-flash"
    base_url: str = OPENROUTER_URL
    workers: int = 8            # số câu hỏi xử lý song song
    max_attempts: int = 3       # 1 lần đầu + tối đa 2 lần sửa lỗi
    votes: int = 3              # số lượt giải tối đa để bỏ phiếu (1 = tắt)
    request_timeout: int = 90   # giây cho mỗi lần gọi API
    reasoning: str = "off"      # off | low | medium | high
    key_source: str = ""        # "biến môi trường" | "đã lưu ở <đường dẫn>"

    @property
    def provider(self) -> str:
        return "OpenRouter" if "openrouter.ai" in self.base_url else "QwenCloud"

    def set_key(self, api_key: str) -> None:
        """Gán key và tự chọn nhà cung cấp theo dạng key.

        Key OpenRouter bắt đầu bằng "sk-or-"; key khác coi là key QwenCloud (thử nghiệm).
        """
        self.api_key = api_key.strip()
        if self.api_key.startswith("sk-or-"):
            self.model, self.base_url = "qwen/qwen3.7-flash", OPENROUTER_URL
        else:
            self.model, self.base_url = "qwen3.7-flash", QWENCLOUD_URL


def load_settings() -> Settings:
    s = Settings(
        workers=int(os.environ.get("CHALDEA_WORKERS", "8")),
        max_attempts=int(os.environ.get("CHALDEA_MAX_ATTEMPTS", "3")),
        votes=int(os.environ.get("CHALDEA_VOTES", "3")),
        reasoning=os.environ.get("CHALDEA_REASONING", "off"),
    )
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("QWENCLOUD_API_KEY") or ""
    if key:
        s.set_key(key)
        s.key_source = "biến môi trường"
    elif saved := load_saved_key():
        s.set_key(saved)
        s.key_source = f"đã lưu ở {USER_CONFIG}"
    return s


def _read_user_config() -> dict:
    try:
        return json.loads(USER_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_saved_key() -> str:
    return str(_read_user_config().get("api_key", "")).strip()


def save_api_key(key: str) -> Path:
    """Lưu key vào ~/.chaldea/config.json (ngoài thư mục project nên không bị nộp/commit nhầm)."""
    data = _read_user_config()
    data["api_key"] = key
    USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    USER_CONFIG.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return USER_CONFIG
