"""Chạy toàn bộ queries.json -> submission.csv (dùng chung cho CLI một lệnh và giao diện tương tác)."""
from __future__ import annotations

import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import Settings
from .excel_reader import load_workbook
from .llm import LLMClient
from .solver import solve


def find_excel(data_dir: Path, file_name: str) -> Path | None:
    for candidate in (data_dir / "xlsx_files" / file_name, data_dir / file_name):
        if candidate.is_file():
            return candidate
    matches = list(data_dir.rglob(Path(file_name).name))  # dự phòng: tìm trong thư mục con
    return matches[0] if matches else None


def run_batch(data_dir: Path, output: Path, settings: Settings, log_path: Path | None = None) -> dict:
    """Trả lời mọi câu trong <data_dir>/queries.json, ghi submission.csv. Trả về thống kê."""
    queries = json.loads((data_dir / "queries.json").read_text(encoding="utf-8-sig"))
    llm = LLMClient(settings)
    start = time.perf_counter()

    def handle(q: dict) -> dict:
        t0 = time.perf_counter()
        result = {"id": q["id"], "query": q["query"], "answer": "", "error": None, "code": ""}
        try:
            path = find_excel(data_dir, q["file_name"])
            if path is None:
                raise FileNotFoundError(q["file_name"])
            workbook = load_workbook(str(path))
            result.update(solve(q["query"], q["file_name"], workbook, llm, settings.max_attempts, settings.votes))
        except Exception as exc:  # một câu lỗi không được làm hỏng cả file kết quả
            result["error"] = f"{type(exc).__name__}: {exc}"
        result["seconds"] = round(time.perf_counter() - t0, 2)
        status = "OK " if result["answer"] else "ERR"
        print(f"[{status}] {q['id']} -> {result['answer']!r} ({result['seconds']}s)", file=sys.stderr)
        return result

    with ThreadPoolExecutor(max_workers=max(1, settings.workers)) as pool:
        results = list(pool.map(handle, queries))

    # Mỗi id đúng một dòng, giữ thứ tự của queries.json
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "answer"])
        for r in results:
            writer.writerow([r["id"], r["answer"]])

    if log_path:
        try:  # log chỉ để tham khảo: ghi lỗi (vd. thư mục chỉ đọc) không được làm hỏng lượt chạy
            with open(log_path, "w", encoding="utf-8") as f:
                for r in results:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except OSError as exc:
            print(f"Không ghi được log {log_path}: {exc}", file=sys.stderr)

    n = max(1, len(queries))
    elapsed = time.perf_counter() - start
    return {
        "questions": len(queries),
        "errors": sum(1 for r in results if not r["answer"]),
        "seconds": elapsed,
        "per_question": elapsed / n,
        "calls": llm.calls,
        "tokens_in": llm.prompt_tokens,
        "tokens_out": llm.completion_tokens,
        "tokens_per_question": (llm.prompt_tokens + llm.completion_tokens) / n,
        "cost": llm.cost,
    }


def summary_line(stats: dict, output: Path) -> str:
    return (
        f"Done: {stats['questions']} questions in {stats['seconds']:.1f}s ({stats['per_question']:.1f}s/question)"
        f" | API calls {stats['calls']} | tokens in {stats['tokens_in']} out {stats['tokens_out']}"
        f" ({stats['tokens_per_question']:.0f}/question) | cost ${stats['cost']:.5f}\n"
        f"Đã lưu kết quả tại: {output.resolve()}"
    )
