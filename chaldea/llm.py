"""Gọi Qwen3.7 Flash (OpenRouter hoặc QwenCloud), kiểm tra API key, ghi lại token / chi phí."""
from __future__ import annotations

import threading
import time

import requests

from .config import Settings

TARGET_MODEL = "qwen3.7-flash"


class LLMError(RuntimeError):
    pass


def _build_body(s: Settings, messages: list[dict], temperature: float, max_tokens: int) -> dict:
    body = {"model": s.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if s.provider == "OpenRouter":
        body["usage"] = {"include": True}
        body["reasoning"] = {"enabled": False} if s.reasoning == "off" else {"effort": s.reasoning}
    else:  # QwenCloud (chuẩn OpenAI)
        body["enable_thinking"] = s.reasoning != "off"
    return body


def _headers(s: Settings) -> dict:
    return {"Authorization": f"Bearer {s.api_key}", "Content-Type": "application/json"}


def verify_key(s: Settings) -> tuple[bool, str]:
    """Gọi thử Qwen3.7 Flash một lần (vài token, gần như miễn phí).

    Trả về (hợp lệ?, thông báo). Key chỉ hợp lệ khi gọi được đúng model Qwen3.7 Flash.
    """
    if not s.api_key:
        return False, "Key rỗng."
    body = _build_body(s, [{"role": "user", "content": "Reply with: ok"}], 0, 8)
    try:
        resp = requests.post(s.base_url, json=body, headers=_headers(s), timeout=30)
    except requests.RequestException as exc:
        return False, f"Không kết nối được tới {s.provider}: {exc}"
    if resp.status_code == 401:
        return False, f"Key không hợp lệ với {s.provider} (401 Unauthorized)."
    if resp.status_code == 402:
        return False, "Key đúng nhưng tài khoản hết tiền / chưa nạp credit (402)."
    if resp.status_code == 403:
        return False, f"Key không có quyền gọi model {s.model} (403)."
    if resp.status_code != 200:
        return False, f"{s.provider} trả lỗi HTTP {resp.status_code}: {resp.text[:200]}"
    served = str(resp.json().get("model", s.model))
    if TARGET_MODEL not in served:
        return False, f"Key gọi ra model '{served}', không phải Qwen3.7 Flash."
    return True, f"Key hợp lệ: {s.provider} · model {served}"


class LLMClient:
    def __init__(self, settings: Settings):
        if not settings.api_key:
            raise LLMError("Chưa có API key: dùng lệnh /api, hoặc đặt biến môi trường OPENROUTER_API_KEY")
        self.s = settings
        self._lock = threading.Lock()
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost = 0.0

    def chat(self, messages: list[dict], temperature: float = 0) -> str:
        body = _build_body(self.s, messages, temperature, 2048)
        last_error = None
        for attempt in range(3):  # thử lại khi lỗi mạng / 429 / 5xx
            try:
                resp = requests.post(self.s.base_url, json=body, headers=_headers(self.s),
                                     timeout=self.s.request_timeout)
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    time.sleep(2 * (attempt + 1))
                    continue
                if resp.status_code != 200:
                    raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                self._record(data.get("usage") or {})
                return data["choices"][0]["message"].get("content") or ""
            except requests.RequestException as exc:
                last_error = str(exc)
                time.sleep(2 * (attempt + 1))
        raise LLMError(f"Gọi API thất bại: {last_error}")

    def _record(self, usage: dict) -> None:
        with self._lock:
            self.calls += 1
            pt = usage.get("prompt_tokens", 0)
            ct = usage.get("completion_tokens", 0)
            self.prompt_tokens += pt
            self.completion_tokens += ct
            # OpenRouter trả sẵn "cost"; nhà cung cấp khác thì ước tính theo giá Qwen3.7 Flash (<32K token)
            self.cost += float(usage.get("cost") or (pt * 0.03 + ct * 0.13) / 1e6)
