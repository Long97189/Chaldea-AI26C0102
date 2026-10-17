"""Giao diện dòng lệnh tương tác của Chaldea: gõ "/" để xem lệnh, gõ câu hỏi để hỏi file Excel đang chọn."""
from __future__ import annotations

import difflib
import getpass
import json
import os
import shlex
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

from .config import Settings, load_settings, save_api_key
from .excel_reader import Workbook, load_workbook
from .llm import LLMClient, verify_key
from .runner import run_batch, summary_line
from .solver import solve

VERSION = "1.0.0"
LOGO = ("╭─◇─╮", "│ ◉ │", "╰─◇─╯")  # "ống kính" Chaldea, 3 dòng như logo của Neko Core

MAX_HISTORY = 5                  # số lượt hỏi-đáp gần nhất gửi kèm làm ngữ cảnh

_COLOR = sys.stdout.isatty()
if _COLOR and os.name == "nt":
    os.system("")  # bật mã màu ANSI trên Windows Terminal / PowerShell


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def ok(msg: str) -> None:
    print(_c("✓ ", "32") + msg)


def warn(msg: str) -> None:
    print(_c("✗ " + msg, "31"))


def info(msg: str) -> None:
    print(_c("· " + msg, "2"))


def _width() -> int:
    """Chiều rộng vẽ được: lấy từ ô nhập prompt_toolkit nếu đang chạy, không thì từ terminal."""
    try:
        from prompt_toolkit.application import get_app_or_none
        app = get_app_or_none()
        if app is not None:
            return max(20, app.output.get_size().columns - 1)
    except Exception:
        pass
    return max(20, shutil.get_terminal_size((100, 24)).columns - 1)


def _text_width(text: str) -> int:
    try:
        from prompt_toolkit.utils import get_cwidth
        return get_cwidth(text)
    except ImportError:
        return len(text)


def echo_input(line: str) -> None:
    """In lại câu vừa gõ thành một thanh nền xám kéo hết chiều ngang (giống Neko Core)."""
    body = f" > {line}"
    pad = max(0, _width() - _text_width(body))
    print(_c(" > ", "48;5;237;94") + _c(line + " " * pad, "48;5;237;97"))


def mask(key: str) -> str:
    return f"{key[:8]}…{key[-4:]}" if len(key) > 14 else "****"


def _ask(message: str, hidden: bool = False) -> str | None:
    """Hỏi một dòng. Trả về None nếu người dùng bấm Esc / Ctrl+C / Ctrl+D (huỷ).

    Ở terminal thật dùng prompt_toolkit (bắt được phím Esc, che ký tự bằng *);
    nếu không dùng được thì quay về getpass/input.
    """
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.key_binding import KeyBindings

            keys = KeyBindings()

            @keys.add("escape", eager=True)
            def _cancel(event):
                event.app.exit(result=None)

            session = PromptSession(key_bindings=keys)
        except Exception:
            session = None
        if session is not None:
            try:
                return session.prompt(message, is_password=hidden)
            except (EOFError, KeyboardInterrupt):
                return None
    try:
        return getpass.getpass(message) if hidden else input(message)
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def ask_for_key(settings: Settings) -> bool:
    """Hỏi API key (ẩn ký tự) cho tới khi gọi thử được Qwen3.7 Flash. Trả về False nếu người dùng huỷ."""
    print("Nhập API key của Qwen3.7 Flash (OpenRouter: sk-or-v1-..., hoặc key QwenCloud).")
    print(_c("Ký tự được che bằng *. Bấm Esc (hoặc để trống rồi Enter) để huỷ.", "2"))
    while True:
        key = (_ask("API key: ", hidden=True) or "").strip()
        if not key:
            info("Đã huỷ nhập key, quay lại giao diện lệnh.")
            return False
        trial = replace(settings)
        trial.set_key(key)
        info(f"Đang kiểm tra key với {trial.provider}...")
        valid, message = verify_key(trial)
        if valid:
            settings.set_key(key)
            ok(message)
            _save_key(settings)
            return True
        warn(message)
        print("Vui lòng nhập lại.")


def _save_key(settings: Settings) -> None:
    """Giống Neko Core: tự lưu key vào thư mục người dùng để lần sau không phải nhập lại."""
    path = save_api_key(settings.api_key)
    settings.key_source = f"đã lưu ở {path}"
    ok(f"Đã lưu key vào {path}. Lần sau mở không cần nhập lại.")


class Shell:
    def __init__(self) -> None:
        self._read_line = self._make_reader()
        self.reset_state()

    def reset_state(self) -> None:
        """Đưa chương trình về trạng thái như vừa mở (dùng khi khởi động và cho lệnh /reset)."""
        self.settings = load_settings()
        self.llm: LLMClient | None = None      # dùng khi hỏi trực tiếp, cộng dồn chi phí trong phiên
        self.workbook: Workbook | None = None
        self.file_path: Path | None = None
        self.data_dir: Path | None = None      # thư mục làm việc, chọn bằng /folder
        self.last_code = ""
        self.history: list[dict] = []          # các lượt hỏi-đáp trên file đang chọn (ngữ cảnh hội thoại)
        self.commands = {
            "api":    (self.cmd_api,    "/api",                     "Nhập API key Qwen3.7 Flash (kiểm tra, sai thì nhập lại)"),
            "folder": (self.cmd_folder, "/folder [đường_dẫn]",      "Chọn thư mục làm việc (trống = mở hộp thoại)"),
            "run":    (self.cmd_run,    "/run",                     "Trả lời toàn bộ câu hỏi -> <thư mục>/submission.csv"),
            "file":   (self.cmd_file,   "/file [tên.xlsx]",         "Chọn file Excel để hỏi trực tiếp (trống = mở hộp thoại)"),
            "new":    (self.cmd_new,    "/new",                     "Phiên mới: bỏ thư mục, file, câu đã hỏi (giữ cấu hình)"),
            "status": (self.cmd_status, "/status",                  "Xem key, model, cấu hình, chi phí phiên"),
            "help":   (self.cmd_help,   "/help",                    "Hiện danh sách lệnh"),
            "reset":  (self.cmd_reset,  "/reset",                   "Chạy lại chương trình từ đầu (xoá thư mục, file, ngữ cảnh, cấu hình)"),
            "logout": (self.cmd_logout, "/logout",                  "Thoát về terminal (giữ key đã lưu)"),
        }

    # ---------- vòng lặp chính ----------
    def welcome(self) -> None:
        """Header gọn kiểu Neko Core: logo nhỏ bên trái, tên / model / thư mục bên phải."""
        s = self.settings
        key = (_c(f"key {mask(s.api_key)}", "2") if s.api_key else _c("chưa có key · gõ /api", "31"))
        right = [
            _c("Chaldea", "1") + _c(f" v{VERSION}", "2"),
            f"{s.model.split('/')[-1]} · {s.provider if s.api_key else 'OpenRouter'} · " + key,
            str(self.data_dir or Path.cwd()),
        ]
        print()
        for logo, text in zip(LOGO, right):
            print(" " + _c(logo, "38;5;208") + "   " + text)
        print(_c("Hỏi đáp trên bảng tính Excel · /folder chọn thư mục · / xem lệnh · Ctrl+C thoát", "2"))
        print()

    def _toolbar(self):
        """Thanh dưới ô nhập: đường kẻ + trái: thư mục/file, phải: model · votes · chi phí."""
        w = _width()
        left = " ▸ " + (self._where().strip(" []") or "chưa chọn thư mục · /folder")
        cost = self.llm.cost if self.llm else 0.0
        right = f"{self.settings.model.split('/')[-1]} · votes {self.settings.votes} · ${cost:.4f} "
        gap = max(1, w - _text_width(left) - _text_width(right))
        return [("class:rule", "─" * w + "\n"), ("class:left", left), ("", " " * gap), ("class:right", right)]

    def loop(self) -> int:
        self.welcome()
        while True:
            try:
                line = self._read_line().strip()
            except (EOFError, KeyboardInterrupt):  # Ctrl+C / Ctrl+D ở dòng lệnh = thoát (giữ key đã lưu)
                print("\nTạm biệt!")
                return 0
            if not line:
                continue
            if self._fancy:
                echo_input(line)
            try:
                if line.startswith("/"):
                    if self.dispatch(line) == "exit":
                        return 0
                else:
                    self.cmd_ask(line)
            except KeyboardInterrupt:
                warn("Đã dừng.")
            except Exception as exc:  # không để một lỗi làm sập cả phiên
                warn(f"{type(exc).__name__}: {exc}")
            print()

    def _where(self) -> str:
        parts = [p for p in (self.data_dir.name if self.data_dir else "",
                             self.file_path.name if self.file_path else "") if p]
        return f" [{' / '.join(parts)}]" if parts else ""

    def _make_reader(self):
        """Ô nhập lệnh: dùng prompt_toolkit để hiện gợi ý ngay khi gõ "/"; không có thì dùng input()."""
        def plain():
            return input(_c("chaldea", "35;1") + _c(self._where(), "33") + _c(" › ", "35"))

        self._fancy = False
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return plain
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.filters import completion_is_selected
            from prompt_toolkit.history import InMemoryHistory
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.styles import Style

            keys = KeyBindings()

            @keys.add("enter", filter=completion_is_selected)
            def _enter_on_suggestion(event):
                """Enter trên dòng gợi ý = chọn VÀ chạy luôn (trừ gợi ý thư mục con của /folder)."""
                buf = event.current_buffer
                buf.apply_completion(buf.complete_state.current_completion)
                if not buf.text.strip().startswith("/folder "):
                    buf.validate_and_handle()

            @keys.add("enter", filter=~completion_is_selected)
            def _enter_typed(event):
                """Enter khi đã gõ tắt ("/l") = viết đầy đủ ("/logout") ngay trên dòng rồi chạy."""
                buf = event.current_buffer
                full = self.expand(buf.text.strip())
                if full != buf.text:
                    buf.text = full
                    buf.cursor_position = len(full)
                buf.validate_and_handle()

            style = Style.from_dict({
                "rule": "#585858",
                "prompt": "#5f87ff bold",
                "left": "#ff8700",
                "right": "#8a8a8a",
                "bottom-toolbar": "noreverse bg:default",
            })
            session = PromptSession(
                completer=_CommandCompleter(self), complete_while_typing=True, history=InMemoryHistory(),
                key_bindings=keys, style=style, bottom_toolbar=self._toolbar,
                erase_when_done=True,  # xoá ô nhập sau Enter; câu đã gõ được in lại thành thanh xám
            )
        except Exception:  # thiếu thư viện hoặc terminal không hỗ trợ -> ô nhập thường
            return plain
        self._fancy = True
        # Ô nhập ở cuối: đường kẻ phía trên, "> " phía trước; đường kẻ + thanh trạng thái phía dưới
        return lambda: session.prompt(lambda: [("class:rule", "─" * _width() + "\n"), ("class:prompt", "> ")])

    def resolve(self, name: str) -> str | None:
        """Tên lệnh đầy đủ từ tên gõ tắt ("l" -> "logout"); None nếu không có hoặc còn nhập nhằng."""
        name = name.lower()
        if name in self.commands:
            return name
        matches = [c for c in self.commands if c.startswith(name)]
        return matches[0] if len(matches) == 1 else None

    def expand(self, line: str) -> str:
        """"/l" -> "/logout": viết đầy đủ tên lệnh gõ tắt, giữ nguyên phần sau."""
        if not line.startswith("/") or line == "/":
            return line
        name, sep, rest = line[1:].partition(" ")
        full = self.resolve(name)
        return f"/{full}{sep}{rest}" if full else line

    def dispatch(self, line: str):
        name, _, rest = line[1:].partition(" ")
        if not name:
            return self.cmd_help("")
        full = self.resolve(name)
        if full is None:
            matches = [c for c in self.commands if c.startswith(name.lower())]
            hint = matches or difflib.get_close_matches(name.lower(), self.commands, n=2)
            warn(f"Không có lệnh /{name}." + (f" Ý bạn là: {', '.join('/' + h for h in hint)}?" if hint else ""))
            return None
        if full != name.lower():
            info(f"/{full}")  # ô nhập thường không tự viết lại dòng đã gõ -> in tên đầy đủ
        return self.commands[full][0](rest.strip())

    @staticmethod
    def _args(rest: str) -> list[str]:
        return [a.strip('"').strip("'") for a in shlex.split(rest, posix=False)]

    def _need_key(self) -> bool:
        if self.settings.api_key:
            return True
        warn("Chưa có API key.")
        return ask_for_key(self.settings)

    # ---------- các lệnh ----------
    def cmd_help(self, _rest: str):
        print(_c("\nLệnh:", "1"))
        for _, usage, desc in self.commands.values():
            print(f"  {_c(usage.ljust(27), '36')} {desc}")
        print(_c("\nGõ câu hỏi bất kỳ (không có /) để hỏi file Excel đang chọn.\n", "2"))

    def cmd_api(self, _rest: str):
        if ask_for_key(self.settings):
            self.llm = None  # tạo client mới với key mới

    def cmd_folder(self, rest: str):
        args = self._args(rest)
        raw = args[0] if args else _pick_dialog(file=False, start=self.data_dir)
        if raw is None:  # không mở được hộp thoại (vd. máy không có giao diện) -> gõ tay
            raw = input("Đường dẫn thư mục: ").strip().strip('"')
        if not raw:
            info("Đã huỷ chọn thư mục.")
            return
        folder = Path(raw).expanduser().resolve()
        if not folder.is_dir():
            warn(f"Không phải thư mục: {folder}")
            return
        self.data_dir, self.workbook, self.file_path, self.history = folder, None, None, []
        ok(f"Thư mục làm việc: {folder}")
        queries = folder / "queries.json"
        if queries.is_file():
            n = len(json.loads(queries.read_text(encoding="utf-8-sig")))
            info(f"queries.json: {n} câu hỏi · {len(self._xlsx_files())} file Excel. Gõ /run để chạy.")
        else:
            warn("Thư mục này không có queries.json: /run không chạy được, nhưng vẫn dùng /file để hỏi từng file.")

    def _xlsx_files(self) -> list[Path]:
        if not self.data_dir:
            return []
        base = self.data_dir / "xlsx_files"
        return sorted((base if base.is_dir() else self.data_dir).glob("*.xlsx"))

    def cmd_run(self, rest: str):
        if rest.strip():
            self.cmd_folder(rest)  # cho phép /run <thư_mục> = /folder <thư_mục> rồi /run
        if self.data_dir is None:
            warn("Chưa chọn thư mục. Dùng /folder trước.")
            return
        if not (self.data_dir / "queries.json").is_file():
            warn(f"Không thấy queries.json trong {self.data_dir}")
            return
        if not self._need_key():
            return
        output = self.data_dir / "submission.csv"
        info(f"Chạy {self.data_dir / 'queries.json'} (votes={self.settings.votes}, workers={self.settings.workers})...")
        stats = run_batch(self.data_dir, output, self.settings, output.parent / "run_log.jsonl")
        stats_text, saved_text = summary_line(stats, output).split("\n")
        print("\n" + _c(stats_text, "2"))
        ok(saved_text)

    def cmd_file(self, rest: str):
        args = self._args(rest)
        if not args:
            raw = _pick_dialog(file=True, start=self.data_dir)
            if raw is None:  # không mở được hộp thoại -> gõ tay
                raw = input("Đường dẫn file .xlsx: ").strip().strip('"')
            args = [raw] if raw else []
        if not args:
            info("Đã huỷ chọn file.")
            return
        path = Path(args[0])
        if not path.is_file():  # cho phép gõ tắt tên file trong thư mục làm việc
            path = next((p for p in self._xlsx_files() if path.name.lower() in (p.name.lower(), p.stem.lower())), path)
        if not path.is_file():
            warn(f"Không thấy file '{args[0]}'.")
            return
        self.workbook, self.file_path, self.history = load_workbook(str(path)), path, []
        sheets = ", ".join(f"{n} ({len(df)} dòng)" for n, df in self.workbook.sheets.items())
        ok(f"Đã mở {path.name}: {sheets} · ~{len(self.workbook.text) // 3} token")
        info("Giờ gõ câu hỏi (tiếng Anh) để hỏi file này.")

    def cmd_ask(self, rest: str):
        query = rest.strip()
        if not query:
            warn("Gõ câu hỏi để hỏi file đang chọn.")
            return
        if self.workbook is None:
            warn("Chưa chọn file. Dùng /file <đường_dẫn.xlsx> trước.")
            return
        if not self._need_key():
            return
        if self.llm is None:
            self.llm = LLMClient(self.settings)
        cost_before, t0 = self.llm.cost, time.perf_counter()
        result = solve(query, self.file_path.name, self.workbook, self.llm,
                       self.settings.max_attempts, self.settings.votes, history=self.history[-MAX_HISTORY:])
        self.last_code = result.get("code", "")
        if result["answer"]:
            self.history.append({"query": query, "answer": result["answer"], "code": self.last_code})
        took, cost = time.perf_counter() - t0, self.llm.cost - cost_before
        if result["answer"]:
            print(_c("➜ ", "32;1") + _c(result["answer"], "1"))
        else:
            warn(f"Không tìm được đáp án. Lỗi: {(result.get('error') or '').strip()[-300:]}")
        votes = result.get("votes")
        print(_c(f"  {took:.1f}s · ${cost:.5f}" + (f" · phiếu: {votes}" if votes else ""), "2"))

    def cmd_new(self, _rest: str):
        """Phiên mới, trắng như lúc khởi động: bỏ thư mục, file, ngữ cảnh. Giữ key."""
        self.data_dir = self.file_path = self.workbook = None
        self.history, self.last_code = [], ""
        self._clear_screen()
        self.welcome()
        ok("Đã bắt đầu phiên mới.")

    def cmd_status(self, _rest: str):
        s = self.settings
        rows = [
            ("API key", f"{mask(s.api_key)} ({s.key_source})" if s.api_key else _c("chưa có (gõ /api)", "31")),
            ("Nhà cung cấp", s.provider if s.api_key else "-"),
            ("Model", s.model),
            ("Bỏ phiếu", f"votes={s.votes}"),
            ("Song song", f"workers={s.workers}"),
            ("Suy luận", f"reasoning={s.reasoning}"),
            ("File đang chọn", str(self.file_path) if self.file_path else "-"),
            ("Thư mục dữ liệu", str(self.data_dir) if self.data_dir else "-"),
            ("Ngữ cảnh hội thoại", f"{len(self.history)} câu đã hỏi (nhớ {MAX_HISTORY} câu gần nhất, /new để xoá)"),
            ("Chi phí hỏi trực tiếp", f"${self.llm.cost:.5f} ({self.llm.calls} lần gọi)" if self.llm else "$0"),
        ]
        for k, v in rows:
            print(f"  {_c(k.ljust(24), '36')} {v}")

    @staticmethod
    def _clear_screen() -> None:
        os.system("cls" if os.name == "nt" else "clear")

    def cmd_reset(self, _rest: str):
        self.reset_state()
        self._clear_screen()
        self.welcome()
        ok("Đã chạy lại từ đầu.")

    def cmd_logout(self, _rest: str):
        """Thoát về terminal, GIỮ key đã lưu (lần sau mở không phải nhập lại; đổi key bằng /api)."""
        print("Trở về terminal. Key vẫn được giữ, lần sau mở không cần nhập lại.")
        return "exit"


def _pick_dialog(file: bool, start: Path | None) -> str | None:
    """Mở hộp thoại chọn thư mục (hoặc file .xlsx) của hệ điều hành.

    Trả về đường dẫn, "" nếu người dùng huỷ, None nếu không mở được hộp thoại.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)  # hiện đè lên VS Code / terminal
        root.update()
        initial = str(start) if start else os.getcwd()
        if file:
            if start and (start / "xlsx_files").is_dir():
                initial = str(start / "xlsx_files")
            info("Đang mở hộp thoại chọn file Excel...")
            chosen = filedialog.askopenfilename(title="Chọn file Excel", initialdir=initial, parent=root,
                                                filetypes=[("Excel", "*.xlsx"), ("Tất cả", "*.*")])
        else:
            info("Đang mở hộp thoại chọn thư mục...")
            chosen = filedialog.askdirectory(title="Chọn thư mục dữ liệu (queries.json + xlsx_files/)",
                                             initialdir=initial, parent=root)
        root.destroy()
        return chosen or ""
    except Exception:
        return None


try:
    from prompt_toolkit.completion import Completer, Completion, PathCompleter
    from prompt_toolkit.document import Document

    class _CommandCompleter(Completer):
        """Gợi ý khi gõ: "/" -> danh sách lệnh; "/a" -> /api; "/file " -> tên file Excel;
        "/folder " -> thư mục."""

        def __init__(self, shell: Shell):
            self.shell = shell
            self.paths = PathCompleter(only_directories=True, expanduser=True)

        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if not text.startswith("/"):
                return
            if " " not in text:
                word = text[1:].lower()
                for name, (_, _usage, desc) in self.shell.commands.items():
                    if name.startswith(word):
                        yield Completion("/" + name, start_position=-len(text), display_meta=desc)
                return
            cmd, _, arg = text[1:].partition(" ")
            cmd = cmd.lower()
            if cmd == "folder":
                yield from self.paths.get_completions(Document(arg, len(arg)), complete_event)
            elif cmd == "file":
                for p in self.shell._xlsx_files():
                    if p.name.lower().startswith(arg.lower()):
                        yield Completion(p.name, start_position=-len(arg))
except ImportError:  # không có prompt_toolkit: vẫn chạy được, chỉ mất gợi ý khi gõ
    _CommandCompleter = None
