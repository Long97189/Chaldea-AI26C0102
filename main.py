"""Chaldea - hỏi đáp trên bảng tính Excel.

Các cách chạy:
    python main.py                                   # ở terminal: giao diện tương tác, gõ "/" để xem lệnh
    python main.py <thư_mục> [<file_ra|thư_mục_ra>]  # chạy một lệnh
    python main.py --input <thư_mục> --output <file_ra|thư_mục_ra>

<thư_mục> chứa queries.json và các file .xlsx (thường trong xlsx_files/); cũng có thể trỏ thẳng tới queries.json.
Không ghi đầu ra -> ghi <thư_mục>/submission.csv. Đầu ra là thư mục -> ghi <thư_mục_ra>/submission.csv.

Khi chạy không có terminal (ví dụ trong Docker) mà không truyền tham số, chương trình tự tìm queries.json
trong CHALDEA_INPUT, /data, /input, /code, /app/data, thư mục hiện tại... rồi chạy luôn, không bao giờ chờ nhập.
API key: biến môi trường OPENROUTER_API_KEY (hoặc key đã lưu bằng /api).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from chaldea.config import load_settings
from chaldea.runner import run_batch, summary_line

# Thư mục dữ liệu hay được mount khi chấm bằng Docker (thử lần lượt nếu không truyền tham số)
DEFAULT_INPUT_DIRS = ("/data", "/input", "/code", "/app/data", "/workspace", "/mnt/data", "/data/input")
DEFAULT_OUTPUT_DIRS = ("/output", "/data/output", "/results")


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def find_data_dir(hint: str | None) -> Path | None:
    """Thư mục chứa queries.json, từ đường dẫn được truyền (thư mục hoặc chính file) hoặc các vị trí mặc định."""
    candidates = [hint] if hint else [os.environ.get("CHALDEA_INPUT"), *DEFAULT_INPUT_DIRS, os.getcwd()]
    for raw in filter(None, candidates):
        p = Path(raw)
        if p.is_file() and p.name == "queries.json":
            return p.parent
        if (p / "queries.json").is_file():
            return p
        if p.is_dir():  # queries.json nằm sâu thêm 1-2 cấp (vd. giải nén ra thêm một thư mục)
            found = sorted(p.glob("*/queries.json")) or sorted(p.glob("*/*/queries.json"))
            if found:
                return found[0].parent
    return None


def resolve_output(raw: str | None, data_dir: Path) -> Path:
    """Đường dẫn file kết quả. Mặc định: <thư_mục_dữ_liệu>/submission.csv (hoặc /output nếu có)."""
    raw = raw or os.environ.get("CHALDEA_OUTPUT")
    if raw:
        p = Path(raw)
        if p.is_dir() or raw.endswith(("/", "\\")) or not p.suffix:
            return p / "submission.csv"
        return p
    for d in DEFAULT_OUTPUT_DIRS:
        if Path(d).is_dir() and not _interactive():
            return Path(d) / "submission.csv"
    return data_dir / "submission.csv"


def writable(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8"):
            pass
        return True
    except OSError:
        return False


def write_blank(data_dir: Path, output: Path) -> None:
    """Không gọi được LLM: vẫn ghi đủ id (đáp án rỗng) để tệp kết quả hợp lệ."""
    queries = json.loads((data_dir / "queries.json").read_text(encoding="utf-8-sig"))
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "answer"])
        for q in queries:
            writer.writerow([q["id"], ""])


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # in tiếng Việt an toàn cả khi chuyển hướng ra file
        stream.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) == 1 and _interactive():
        from chaldea.shell import Shell
        return Shell().loop()

    parser = argparse.ArgumentParser(description="Trả lời câu hỏi trên bảng tính Excel -> submission.csv")
    parser.add_argument("paths", nargs="*", help="[thư_mục_dữ_liệu] [file_ra|thư_mục_ra]")
    parser.add_argument("--input", "-i", "--data-dir", "--input-dir", dest="input",
                        help="Thư mục chứa queries.json và xlsx_files/ (hoặc đường dẫn tới queries.json)")
    parser.add_argument("--output", "-o", "--output-dir", "--output-file", dest="output",
                        help="File kết quả hoặc thư mục chứa nó (mặc định <thư_mục_dữ_liệu>/submission.csv)")
    parser.add_argument("--workers", type=int, help="Số câu xử lý song song")
    parser.add_argument("--log", help="File log chi tiết (code đã sinh, lỗi); mặc định run_log.jsonl cạnh file kết quả")
    args = parser.parse_args()

    input_hint = args.input or (args.paths[0] if args.paths else None)
    output_hint = args.output or (args.paths[1] if len(args.paths) > 1 else None)

    data_dir = find_data_dir(input_hint)
    if data_dir is None:
        where = input_hint or ", ".join(DEFAULT_INPUT_DIRS)
        print(f"Không tìm thấy queries.json trong: {where}", file=sys.stderr)
        return 2

    output = resolve_output(output_hint, data_dir)
    if not writable(output):  # thư mục dữ liệu chỉ đọc -> ghi vào thư mục hiện tại
        fallback = Path.cwd() / "submission.csv"
        print(f"Không ghi được {output}; ghi vào {fallback}", file=sys.stderr)
        output = fallback
    # Log ghi cạnh submission.csv để xem lại được cả khi chạy trong Docker (thư mục /app mất khi container tắt)
    log = Path(args.log) if args.log else output.parent / "run_log.jsonl"
    if not writable(log):
        log = Path.cwd() / "run_log.jsonl"
        if not writable(log):
            log = None

    settings = load_settings()
    if args.workers:
        settings.workers = args.workers
    if not settings.api_key:
        if _interactive():
            from chaldea.shell import ask_for_key
            if ask_for_key(settings):
                return _run(data_dir, output, settings, log)
        write_blank(data_dir, output)
        print("Thiếu API key: đặt biến môi trường OPENROUTER_API_KEY "
              f"(đã ghi {output.resolve()} với đáp án rỗng).", file=sys.stderr)
        return 2
    return _run(data_dir, output, settings, log)


def _run(data_dir: Path, output: Path, settings, log: Path | None) -> int:
    print(f"Dữ liệu: {data_dir.resolve()}", file=sys.stderr)
    stats = run_batch(data_dir, output, settings, log)
    print("\n" + summary_line(stats, output), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
