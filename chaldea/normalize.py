"""Chuẩn hoá đáp án cuối cùng để so khớp chính xác (Exact Match)."""
from __future__ import annotations

import datetime as dt
import math
import re
from decimal import ROUND_HALF_UP, Decimal

import numpy as np


def to_answer_text(value) -> str:
    """Chuyển giá trị Python bất kỳ thành chuỗi đáp án gọn."""
    if value is None:
        return ""
    if isinstance(value, (np.generic,)):
        value = value.item()
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer():
            return str(int(value))
        return repr(round(value, 6))
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time(0, 0) else value.isoformat(sep=" ")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return ", ".join(to_answer_text(v) for v in value)
    return clean_text(str(value))


def clean_text(text: str) -> str:
    text = " ".join(text.split())
    text = re.sub(r"^(final\s+)?answer\s*[:：]\s*", "", text, flags=re.I)
    # bỏ dấu nháy / backtick bao quanh cả đáp án
    while len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'`":
        text = text[1:-1].strip()
    # "11.0" -> "11" khi đáp án là một số nguyên viết dạng thực
    if re.fullmatch(r"-?\d+\.0+", text) and not _wants_decimals(text):
        text = text.split(".")[0]
    return text


_KEEP_TABLE_LABEL = re.compile(r"exactly as (it )?(appears|shown|written|listed)|as (it )?appears in the table"
                               r"|as shown in the table|as written in the table", re.I)


def align_to_query(answer: str, query: str) -> str:
    """Khi câu hỏi LIỆT KÊ sẵn các ứng viên, dùng đúng chữ trong câu hỏi.

    Ví dụ: "Rank ...: Agriculture, Manufacturing, and Construction." còn bảng ghi "Agriculture and related"
    -> đáp án dùng "Agriculture". Chỉ đổi khi phần chữ trùng trong câu hỏi đứng như một mục của danh sách
    (theo sau là dấu phẩy, "and"/"or", dấu câu); không đổi nếu câu hỏi yêu cầu giữ nguyên nhãn trong bảng.
    """
    if _KEEP_TABLE_LABEL.search(query):
        return answer
    q = query.lower()
    parts = []
    for part in answer.split(", "):
        new = part
        if part and part[0].isalpha() and part.lower() not in q:
            words = part.split()
            for n in range(len(words) - 1, 0, -1):
                prefix = " ".join(words[:n])
                item = r"(?:^|[\s,:;(\"'])" + re.escape(prefix.lower()) + r"(?=\s*(?:,|;|\.|\?|\)|:|$|\s+and\b|\s+or\b))"
                if len(prefix) >= 4 and re.search(item, q):
                    new = prefix
                    break
        parts.append(new)
    return ", ".join(parts)


_WORD_DIGITS = {
    # tiếng Anh, tiếng Việt, tiếng Pháp, tiếng Hàn (thứ tự: 첫째=1), tiếng Trung
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "không": 0, "một": 1, "hai": 2, "ba": 3, "bốn": 4, "năm": 5,
    "une": 1, "un": 1, "deux": 2, "trois": 3, "quatre": 4,
    "첫째": 1, "둘째": 2, "셋째": 3, "넷째": 4, "한": 1, "두": 2, "세": 3,
    "零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
}
_DIGIT = r"(\d+|" + "|".join(sorted(map(re.escape, _WORD_DIGITS), key=len, reverse=True)) + r")"
# "N decimal places" bằng nhiều ngôn ngữ (câu hỏi của BTC có tiếng Anh, Việt, Pháp, Hàn, Trung)
_W = r"(?<!\w)" + _DIGIT  # chữ số đứng thành từ riêng (ngôn ngữ có dấu cách)
_DECIMAL_PATTERNS = [
    _W + r"\s+decimal\s+places?\b",                 # two decimal places
    _W + r"\s+decimal\b",                           # one decimal
    _W + r"\s+chữ\s+số\s+(?:ở\s+phần\s+)?thập\s+phân",  # một chữ số thập phân
    _W + r"\s+(?:số|chữ số)\s+sau\s+dấu\s+(?:phẩy|chấm)",
    _W + r"\s+décimales?\b",                        # une décimale / deux décimales
    _W + r"\s+chiffres?\s+après\s+la\s+virgule",
    r"소수점\s*(?:이하\s*)?" + _DIGIT + r"\s*(?:자리|번째)",   # 소수점 둘째 자리 / 소수점 2자리
    r"保留\s*" + _DIGIT + r"\s*位\s*小数",            # 保留一位小数
    r"小数点后\s*" + _DIGIT + r"\s*位",
]
_INTEGER_WORDS = ("integer", "whole number", "số nguyên", "nombre entier", "entier", "정수", "整数")
_WITHOUT_WORDS = ("without", "không có", "không kèm", "không dùng", "không ghi", "sans", "없이", "不带", "不要", "不含", "去掉")
_THOUSANDS = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _decimal_places(q: str) -> int | None:
    for pattern in _DECIMAL_PATTERNS:
        m = re.search(pattern, q)
        if m:
            word = m.group(1)
            return int(word) if word.isdigit() else _WORD_DIGITS[word]
    return None


def enforce_format(answer: str, query: str) -> str:
    """Ép đáp án theo đúng yêu cầu định dạng ghi trong câu hỏi (lệch 1 ký tự là sai Exact Match):
    "Yes or No", "N decimal places", "integer", "without commas", "without the percent sign / units".
    Áp dụng cho từng phần nếu đáp án là danh sách "a, b"."""
    if not answer:
        return answer
    q = query.lower()

    if re.search(r"\byes\s+or\s+no\b", q):
        low = answer.strip().rstrip(".").lower()
        if low in ("yes", "true", "y"):
            return "Yes"
        if low in ("no", "false", "n"):
            return "No"
        return answer

    decimals = _decimal_places(q)
    integer = decimals is None and any(w in q for w in _INTEGER_WORDS)
    numeric_format = decimals is not None or integer
    without = any(w in q for w in _WITHOUT_WORDS)
    strip_percent = without and ("percent sign" in q or "%" in q or "units" in q)
    strip_units = without and ("units" in q or "đơn vị" in q or "unité" in q or "단위" in q or "单位" in q)

    def fix(part: str) -> str:
        p = part.strip()
        if strip_percent or (numeric_format and re.fullmatch(r"-?[\d.,]+\s*%", p)):  # "chỉ trả lời bằng số"
            p = p.rstrip("%").strip()
        if strip_units:
            m_unit = re.fullmatch(r"\$?\s*(-?[\d.,]+)\s*[A-Za-z%$ ]*", p)
            if m_unit:
                p = m_unit.group(1)
        if _THOUSANDS.fullmatch(p) and (numeric_format or "comma" in q):
            p = p.replace(",", "")
        if numeric_format and _NUMBER.fullmatch(p):
            places = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
            p = str(Decimal(p).quantize(places, rounding=ROUND_HALF_UP))
        return p

    return ", ".join(fix(part) for part in answer.split(", "))


def _wants_decimals(text: str) -> bool:
    # "3.00" có thể là định dạng 2 chữ số thập phân cố ý -> giữ nguyên
    return len(text.split(".")[1]) >= 2
