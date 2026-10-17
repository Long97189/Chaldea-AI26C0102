"""Giải một câu hỏi: LLM đọc bảng -> viết code pandas -> chạy code -> lấy đáp án.

Vì sao sinh code thay vì để LLM trả lời thẳng: các phép đếm, cộng, sắp xếp, so sánh
ngày tháng do Python tính sẽ chính xác tuyệt đối; LLM chỉ cần hiểu câu hỏi và bảng.
Nếu code lỗi, gửi lỗi lại cho LLM sửa (tối đa max_attempts lần).
"""
from __future__ import annotations

import datetime as dt
import math
import re
import traceback
import warnings
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from .excel_reader import Workbook
from .llm import LLMClient
from .normalize import align_to_query, clean_text, enforce_format, to_answer_text

# Cảnh báo của pandas/numpy trong code sinh ra không ảnh hưởng kết quả. Tắt một lần ở đây
# (warnings.catch_warnings trong từng lượt chạy không an toàn khi chạy nhiều luồng).
SINGLE_VOTE_CHARS = 18_000  # bảng gửi LLM dài hơn mức này thì chỉ giải 1 lượt (không bỏ phiếu)

for _category in (UserWarning, FutureWarning, DeprecationWarning, RuntimeWarning,
                  getattr(pd.errors, "SettingWithCopyWarning", None)):  # pandas 3 đã bỏ cảnh báo này
    if _category is not None:
        warnings.filterwarnings("ignore", category=_category)

SYSTEM_PROMPT = """You are a precise data analyst. You answer questions about an Excel workbook by writing Python code.

The workbook is shown as a cell grid: each cell is written as REF=VALUE (e.g. B12=8669). REF[A1:C1] marks a merged cell range. Empty cells are omitted. Headers can span several rows; one sheet may contain several tables; footnote markers like "3/" or "(1)" may be attached to labels.

In your code these variables already exist:
- sheets: dict mapping sheet name -> pandas DataFrame. Index = Excel row number (int, starting at 1), columns = Excel column letters ("A", "B", ...). Merged cells are filled with their top-left value. Empty cells are None.
- df: the first sheet's DataFrame.
- pd, np, math, re, datetime (module) are imported.

Rules:
1. First identify exactly which rows/columns the question refers to, by reading the header labels carefully (watch multi-level headers, sections like "Men"/"Women", fiscal vs calendar year blocks, totals vs sub-items).
2. Compute the answer FROM THE DATA in code (filter, sort, sum, count, compare). Reference cells by Excel coordinates, e.g. sheets["S"].loc[12, "B"], or select row ranges. Never guess numbers.
3. Do not include total/subtotal rows when the question asks about individual items, unless asked. But when asked to average/sum "across all <levels/categories/groups>" spread over columns, use EVERY numeric cell of that row in the table's data columns - all leaf columns AND group "Total" columns alike (e.g. average of B..I = 8 values), without picking or deduplicating.
4. Report values in the units shown in the table. Do NOT rescale (e.g. do not multiply by 1000 for "[Numbers in thousands]") unless the question explicitly asks to convert.
5. If each person has a birth date and another event date (admission, hire, enrollment...), "age", "oldest", "youngest" mean age on that event date (event date - birth date), unless the question says otherwise.
6. Assign the final answer to a variable named `answer` as a STRING formatted exactly as the question requests (e.g. integer without commas, exactly two decimals, "Yes"/"No", names separated by ", "). Copy names/labels exactly as they appear in the sheet but without footnote markers; if the question itself lists the candidate names, answer with the question's wording for them.
7. Reply with ONE ```python code block and nothing else."""

USER_TEMPLATE = """Workbook "{file_name}":

{table}

{context}Question: {query}"""


def format_history(history: list[dict] | None) -> str:
    """Các lượt hỏi trước (chỉ dùng ở chế độ hỏi trực tiếp) để hiểu câu hỏi nối tiếp như "ở dòng nào?"."""
    if not history:
        return ""
    lines = ['Earlier in this conversation (use it to resolve references like "that person", "which row"):']
    for i, turn in enumerate(history, 1):
        lines.append(f"Q{i}: {turn['query']}\nA{i}: {turn['answer']}")
    last_code = history[-1].get("code", "").strip()
    if last_code:
        lines.append(f"Code used for A{len(history)}:\n```python\n{last_code}\n```")
    return "\n".join(lines) + "\n\n"


def extract_code(text: str) -> str:
    blocks = re.findall(r"```[ \t]*(?:python3?|py)?[^\n]*\n(.*?)```", text, flags=re.S | re.I)
    code = max(blocks, key=len) if blocks else text.strip().strip("`")
    # bỏ dòng "python" thừa nếu model viết lệch định dạng khối code
    return re.sub(r"^\s*python3?\s*\n", "", code, flags=re.I)


def run_code(code: str, workbook: Workbook):
    """Chạy code do LLM sinh ra; trả về giá trị biến `answer`."""
    sheets = {name: df.copy() for name, df in workbook.sheets.items()}
    env = {
        "sheets": sheets,
        "df": next(iter(sheets.values())),
        "pd": pd, "np": np, "math": math, "re": re, "datetime": dt,
        # Bỏ qua print() trong code sinh ra. KHÔNG dùng redirect_stdout: nó đổi sys.stdout chung,
        # khi nhiều luồng (bỏ phiếu song song) chạy cùng lúc sẽ trả sys.stdout về sai -> mất output.
        "print": lambda *args, **kwargs: None,
    }
    exec(compile(code, "<llm_code>", "exec"), env)
    if "answer" not in env:
        raise ValueError("Code did not assign a variable named `answer`.")
    return env["answer"]


def solve(query: str, file_name: str, workbook: Workbook, llm: LLMClient,
          max_attempts: int = 3, votes: int = 3, history: list[dict] | None = None) -> dict:
    """Bỏ phiếu: giải 2 lần song song; nếu 2 đáp án trùng nhau thì chốt luôn,
    nếu khác nhau thì giải thêm đến tối đa `votes` lần và lấy đáp án nhiều phiếu nhất.
    Lần đầu dùng temperature 0, các lần sau 0.5 để có góc nhìn khác."""
    def attempt(i: int) -> dict:
        try:
            return solve_once(query, file_name, workbook, llm, max_attempts,
                              temperature=0 if i == 0 else 0.5, history=history)
        except Exception as exc:  # lỗi mạng / API sau khi đã thử lại -> coi như lượt này không có đáp án
            return {"answer": "", "code": "", "attempts": 0, "error": f"{type(exc).__name__}: {exc}"}

    if len(workbook.text) > SINGLE_VOTE_CHARS:
        votes = 1  # file rất lớn: mỗi lượt ~15-18K token, bỏ phiếu 2-3 lượt sẽ vượt ngân sách chi phí
    if votes <= 1:
        runs = [attempt(0)]
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            runs = list(pool.map(attempt, range(2)))
        while len(runs) < votes and not _agreed(runs):
            runs.append(attempt(len(runs)))

    answers = [r["answer"] for r in runs if r["answer"]]
    if not answers:  # mọi lượt viết code đều thất bại -> dự phòng: hỏi thẳng, không để trống đáp án
        return {**runs[0], **answer_directly(query, file_name, workbook, llm, history)}
    if len(runs) == 1:
        return runs[0]
    counts = Counter(answers)
    best = max(answers, key=lambda a: (counts[a], -answers.index(a)))  # hoà phiếu -> lần chạy sớm nhất
    chosen = next(r for r in runs if r["answer"] == best)
    return {**chosen, "votes": [r["answer"] for r in runs]}


def _agreed(runs: list[dict]) -> bool:
    answers = [r["answer"] for r in runs if r["answer"]]
    return bool(answers) and Counter(answers).most_common(1)[0][1] >= 2


# Đáp án "rỗng" trá hình: code chạy được nhưng bộ lọc không khớp dòng nào -> coi là lỗi, bắt sửa lại
NO_RESULT = re.compile(r"^\s*(no data( found)?|not found|n/?a|none|null|nan|unknown|no (match|result)s?( found)?"
                       r"|not available|empty|\[\]|\{\})\s*\.?\s*$", re.I)


def solve_once(query: str, file_name: str, workbook: Workbook, llm: LLMClient,
               max_attempts: int = 3, temperature: float = 0, history: list[dict] | None = None) -> dict:
    """Một lượt giải (kèm sửa lỗi). Trả về dict: answer, code, attempts, error."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(
            file_name=file_name, table=workbook.text, context=format_history(history), query=query)},
    ]
    code, error = "", None
    for attempt in range(1, max_attempts + 1):
        reply = llm.chat(messages, temperature=temperature)
        code = extract_code(reply)
        try:
            answer = enforce_format(align_to_query(to_answer_text(run_code(code, workbook)), query), query)
            if answer and not NO_RESULT.match(answer):
                return {"answer": answer, "code": code, "attempts": attempt, "error": None}
            error = (f"The code ran but `answer` is {answer!r}: your filter/lookup matched nothing. The data IS in the "
                     "table - re-read the exact labels/headers in the grid (spelling, footnote marks, extra spaces, "
                     "merged header rows) and match them more loosely (e.g. str.contains, strip, lower).")
        except Exception:
            error = traceback.format_exc(limit=2)[-1500:]
        messages += [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": f"Your code failed:\n{error}\nFix it and reply with one corrected ```python block."},
        ]
    return {"answer": "", "code": code, "attempts": max_attempts, "error": error}


DIRECT_PROMPT = """You answer questions about an Excel workbook shown as a cell grid (REF=VALUE, REF[A1:C1] = merged range).
Read the relevant cells carefully and reply with ONLY the final answer, formatted exactly as the question requests.
No explanation, no units unless asked, no extra words."""


def answer_directly(query: str, file_name: str, workbook: Workbook, llm: LLMClient,
                    history: list[dict] | None = None) -> dict:
    """Phương án dự phòng khi không viết được code chạy đúng: để LLM đọc bảng và trả lời thẳng.
    Kém chính xác hơn với phép tính, nhưng còn hơn để trống (chắc chắn 0 điểm)."""
    messages = [
        {"role": "system", "content": DIRECT_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(
            file_name=file_name, table=workbook.text, context=format_history(history), query=query)},
    ]
    try:
        reply = llm.chat(messages)
    except Exception as exc:
        return {"answer": "", "fallback": True, "error": f"{type(exc).__name__}: {exc}"}
    lines = [x for x in reply.strip().splitlines() if x.strip()]
    answer = enforce_format(align_to_query(clean_text(lines[-1]) if lines else "", query), query)
    return {"answer": answer, "fallback": True}
