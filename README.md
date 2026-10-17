# Chaldea — Hỏi đáp trên bảng tính Excel

**Chủ đề 2: Hỏi đáp trên bảng tính Excel.** Chaldea đọc các tệp `.xlsx` (nhiều sheet, nhiều bảng trên một
sheet, tiêu đề nhiều tầng, ô gộp), trả lời các câu hỏi ngôn ngữ tự nhiên trong `queries.json` và xuất
`submission.csv` đúng định dạng mẫu.

- **Mô hình:** Qwen3.7 Flash (`qwen/qwen3.7-flash`) qua OpenRouter, đúng mô hình BTC quy định.
- **Cách tiếp cận:** LLM đọc bảng và **viết code Python (pandas)**; Python chạy code để tính đáp án, nên các
  phép đếm, cộng, sắp xếp, so sánh ngày tháng là chính xác.
- **Đóng gói bằng Docker** (Linux amd64, chỉ CPU): build một lần, chạy một lệnh là có `submission.csv`
  (xem [mục 1](#1-chạy-bằng-docker-dành-cho-ban-tổ-chức)). Không cần GPU, không tải mô hình về máy, không có API key trong mã nguồn.
- **Hỗ trợ câu hỏi nhiều ngôn ngữ** (Anh, Việt, Pháp, Hàn, Trung), kể cả yêu cầu định dạng như
  "một chữ số thập phân", "保留一位小数", "소수점 둘째 자리".
- **Giao diện dòng lệnh tương tác** (tuỳ chọn): chạy `python main.py`, gõ `/` để chọn lệnh.

---

## Mục lục

1. [Chạy bằng Docker (dành cho Ban Tổ chức)](#1-chạy-bằng-docker-dành-cho-ban-tổ-chức)
2. [Yêu cầu hệ thống](#2-yêu-cầu-hệ-thống)
3. [Cài đặt](#3-cài-đặt)
4. [Giao diện tương tác (tuỳ chọn)](#4-giao-diện-tương-tác-tuỳ-chọn)
5. [Danh sách lệnh](#5-danh-sách-lệnh)
6. [Định dạng đầu vào và đầu ra](#6-định-dạng-đầu-vào-và-đầu-ra)
7. [Tuân thủ quy định của đề](#7-tuân-thủ-quy-định-của-đề)
8. [Nguyên lý hoạt động](#8-nguyên-lý-hoạt-động)
9. [Kết quả đo trên dữ liệu công khai](#9-kết-quả-đo-trên-dữ-liệu-công-khai)
10. [Cấu trúc mã nguồn](#10-cấu-trúc-mã-nguồn)
11. [Tham số dòng lệnh](#11-tham-số-dòng-lệnh)
12. [Xử lý sự cố](#12-xử-lý-sự-cố)

---

## 1. Chạy bằng Docker (dành cho Ban Tổ chức)

Đây là cách chạy chính thức. Toàn bộ quá trình **tự động**: không cần gõ lệnh nào bên trong chương trình.
Chỉ cần 4 bước.

### Bước 1: Chuẩn bị

- Cài **Docker** (Windows/macOS: [Docker Desktop](https://www.docker.com/products/docker-desktop/); Linux: Docker
  Engine) và **mở Docker lên** trước khi chạy lệnh.
- Có một **API key OpenRouter** (dạng `sk-or-v1-...`) còn số dư.
- Có một **thư mục dữ liệu** gồm `queries.json` và thư mục `xlsx_files/`, ví dụ:

  ```
  D:\Dataset\                 (Linux: /home/an/dataset/ · macOS: /Users/an/dataset/)
  ├── queries.json
  └── xlsx_files\
      ├── p2_t01.xlsx
      └── ...
  ```

### Bước 2: Build ảnh Docker (chỉ làm một lần)

Giải nén `AI26C0102.zip`, mở terminal **tại thư mục chứa `Dockerfile`**, rồi chạy:

```bash
docker build --platform linux/amd64 -t ai26c0102 .
```

Lệnh này tạo một ảnh Docker tên `ai26c0102` chứa sẵn Python, thư viện và mã nguồn (khoảng 90 MB, mất vài
phút ở lần đầu). Dấu chấm `.` ở cuối nghĩa là "dùng `Dockerfile` trong thư mục hiện tại".

> `ai26c0102` là **tên ảnh Docker** (do lệnh `-t` đặt), không phải tên tệp. Docker bắt buộc tên ảnh **viết
> thường**; viết `AI26C0102` sẽ báo lỗi `repository name must be lowercase`. Tên tệp nộp vẫn là `AI26C0102.zip`.

### Bước 3: Chạy

**Cấu trúc lệnh** (viết trên một dòng):

```
docker run --rm -e OPENROUTER_API_KEY=<API_KEY> -v "<THƯ_MỤC_DỮ_LIỆU>:/data" ai26c0102 --input /data --output /data/submission.csv
```

Chỉ cần thay **2 chỗ trong dấu `< >`**, phần còn lại giữ nguyên:

| Chỗ cần thay | Điền gì | Ví dụ |
|---|---|---|
| `<API_KEY>` | API key OpenRouter | `sk-or-v1-abc123...` |
| `<THƯ_MỤC_DỮ_LIỆU>` | Đường dẫn **đầy đủ** tới thư mục chứa `queries.json` và `xlsx_files/` trên máy | Windows: `D:\Dataset` · Linux: `/home/<tên>/dataset` · macOS: `/Users/<tên>/dataset` |

Ý nghĩa các phần giữ nguyên:

| Phần | Ý nghĩa |
|---|---|
| `docker run` | Chạy chương trình bên trong ảnh Docker |
| `--rm` | Tự dọn container sau khi chạy xong |
| `-e OPENROUTER_API_KEY=...` | Truyền API key cho chương trình (key không nằm trong mã nguồn) |
| `-v "...:/data"` | Cho chương trình thấy thư mục dữ liệu trên máy dưới tên `/data` bên trong Docker |
| `ai26c0102` | Tên ảnh đã build ở bước 2 |
| `--input /data` | Đọc dữ liệu từ `/data`, tức chính thư mục dữ liệu trên máy |
| `--output /data/submission.csv` | Ghi kết quả vào `/data/submission.csv`, tức `<THƯ_MỤC_DỮ_LIỆU>/submission.csv` trên máy |

**Ví dụ:**

Linux (thư mục dữ liệu `/home/an/dataset`):

```bash
docker run --rm -e OPENROUTER_API_KEY=sk-or-v1-abc123... -v "/home/an/dataset:/data" ai26c0102 --input /data --output /data/submission.csv
```

macOS (thư mục dữ liệu `/Users/an/dataset`):

```bash
docker run --rm -e OPENROUTER_API_KEY=sk-or-v1-abc123... -v "/Users/an/dataset:/data" ai26c0102 --input /data --output /data/submission.csv
```

Windows, PowerShell hoặc cmd (thư mục dữ liệu `D:\Dataset`):

```powershell
docker run --rm -e OPENROUTER_API_KEY=sk-or-v1-abc123... -v "D:\Dataset:/data" ai26c0102 --input /data --output /data/submission.csv
```

Trên Linux, nếu báo lỗi quyền truy cập Docker (`permission denied`) thì thêm `sudo` ở đầu lệnh.

### Bước 4: Lấy kết quả

Trong lúc chạy, mỗi câu hiện một dòng `[OK ] <id> -> '<đáp án>' (<thời gian>)`. Khi xong, hai dòng cuối có dạng:

```
Done: 30 questions in 40.6s (1.4s/question) | API calls 65 | tokens in 335113 out 34692 (12327/question) | cost $0.01066
Đã lưu kết quả tại: /data/submission.csv
```

Tệp kết quả nằm ngay trong thư mục dữ liệu: **`<THƯ_MỤC_DỮ_LIỆU>/submission.csv`** (ví dụ
`D:\Dataset\submission.csv`), gồm hai cột `id,answer`, mỗi câu hỏi
một dòng (xem [mục 6](#6-định-dạng-đầu-vào-và-đầu-ra)). Bên cạnh là `run_log.jsonl`: code Python đã sinh và thời gian
của từng câu.

### Dành cho hệ thống chấm tự động

Ảnh khai báo `ENTRYPOINT ["python", "/app/main.py"]`: mọi tham số đứng sau tên ảnh được chuyển thẳng vào
chương trình. Ngoài cách ở bước 3, chương trình còn nhận các cách gọi sau:

| Cách gọi (phần sau tên ảnh) | Đọc dữ liệu từ | Ghi kết quả ra |
|---|---|---|
| `--input /data --output /out` (đầu ra là thư mục) | `/data` | `/out/submission.csv` |
| `/data` (chỉ một đường dẫn) | `/data` | `/data/submission.csv` |
| `/data /out/result.csv` | `/data` | `/out/result.csv` |
| (không tham số) | Tự tìm `queries.json` trong `/data`, `/input`, `/code`, `/app/data`, `/workspace`, `/mnt/data` | `/output/submission.csv` nếu có mount `/output`, nếu không thì cạnh `queries.json` |

- `--input` cũng nhận đường dẫn tới chính tệp `queries.json`, hoặc thư mục cha của nó (tìm sâu thêm 2 cấp).
- Thư mục dữ liệu **chỉ đọc** (`-v ...:/data:ro`): kết quả được ghi vào `/app/submission.csv`; đường dẫn thật
  luôn được in ra. Nên mount thêm một thư mục ghi được, ví dụ `-v "/home/an/out:/output"`.
- Thiếu API key: chương trình **không chờ nhập**, vẫn ghi `submission.csv` đủ mọi `id` (đáp án rỗng) để tệp hợp
  lệ, báo lỗi rõ ràng và thoát với mã `2`.
- Có thể chỉ định bằng biến môi trường thay cho tham số: `CHALDEA_INPUT`, `CHALDEA_OUTPUT`.

Tất cả các cách trên đã được kiểm thử, với giới hạn **`--memory=1g --cpus=6`** đúng cấu hình máy chấm.

### Chạy không dùng Docker

Cần Python 3.12 trở lên. Mở terminal tại thư mục chứa `main.py`:

**Windows (PowerShell)**

```powershell
pip install -r requirements.txt
$env:OPENROUTER_API_KEY = "sk-or-v1-..."
python main.py --input D:\Dataset --output D:\Dataset\submission.csv
```

**Linux / macOS**

```bash
pip3 install -r requirements.txt
export OPENROUTER_API_KEY="sk-or-v1-..."
python3 main.py --input /home/an/dataset --output /home/an/dataset/submission.csv
```

Trên Linux/macOS, lệnh Python thường là `python3` và `pip3`; nếu máy có sẵn lệnh `python` trỏ tới Python 3.12
thì dùng `python`/`pip` cũng được.

Ngoài ra chương trình có giao diện tương tác (mục 4 và mục 5) để thử nhanh và trình bày khi vấn đáp.

---

## 2. Yêu cầu hệ thống

| Thành phần | Yêu cầu |
|---|---|
| Docker | Docker Desktop (Windows/macOS) hoặc Docker Engine (Linux), khi chạy bằng Docker |
| Python | **3.12 trở lên** khi cài không qua Docker (thư viện được cố định phiên bản; ảnh Docker đã có sẵn Python 3.12.15) |
| Hệ điều hành | Windows, Linux hoặc macOS |
| Phần cứng | CPU thông thường; không cần GPU |
| Mạng | Truy cập được `https://openrouter.ai` |
| Tài khoản | API key OpenRouter có số dư để gọi `qwen/qwen3.7-flash` |

---

## 3. Cài đặt

Phần này dành cho cách chạy **không dùng Docker** (giao diện tương tác ở mục 4). Giải nén tệp zip, mở terminal **tại thư mục chứa `main.py`**, rồi chạy:

```bash
pip install -r requirements.txt          # Windows
pip3 install -r requirements.txt         # Linux / macOS
```

Thư viện được cài (phiên bản cố định): `openpyxl`, `pandas`, `numpy`, `requests`, `prompt_toolkit`.

> Khuyến nghị dùng môi trường ảo để không ảnh hưởng Python hệ thống:
> `python -m venv .venv` (Linux/macOS: `python3 -m venv .venv`), sau đó kích hoạt bằng `.\.venv\Scripts\Activate.ps1` (Windows PowerShell) hoặc
> `source .venv/bin/activate` (Linux/macOS), rồi mới chạy `pip install`.

---

## 4. Giao diện tương tác (tuỳ chọn)

**Không cần cho việc chấm** (chấm dùng Docker ở mục 1). Đây là cách dùng trên máy cá nhân, để thử nhanh
hoặc trình bày khi vấn đáp: không cần đặt biến môi trường hay gõ tham số, chỉ cần 4 bước sau khi cài đặt (mục 3).

### Bước 1: Khởi động

```bash
python main.py
```

```
 ╭─◇─╮   Chaldea v1.0.0
 │ ◉ │   qwen3.7-flash · OpenRouter · chưa có key · gõ /api
 ╰─◇─╯   D:\AI26C0102
Hỏi đáp trên bảng tính Excel · /folder chọn thư mục · / xem lệnh · Ctrl+C thoát
```

Gõ `/` để hiện danh sách lệnh. Gõ thêm vài chữ để lọc (ví dụ `/a` → `/api`), dùng mũi tên để chọn và
`Enter` để chạy.

### Bước 2: Nhập API key bằng `/api`

```
> /api
API key: *************************************
· Đang kiểm tra key với OpenRouter...
✓ Key hợp lệ: OpenRouter · model qwen/qwen3.7-flash
✓ Đã lưu key vào C:\Users\<tên>\.chaldea\config.json. Lần sau mở không cần nhập lại.
```

- Ký tự được che bằng `*`. Bấm `Esc` để huỷ.
- Key được kiểm tra ngay bằng một lần gọi thử Qwen3.7 Flash. Key sai, hết số dư hoặc không gọi được đúng
  model sẽ bị từ chối và phải nhập lại.
- Key hợp lệ được **tự lưu trong thư mục người dùng** (`~/.chaldea/config.json`), nằm ngoài thư mục mã
  nguồn. Những lần mở sau không cần nhập lại.

### Bước 3: Chọn thư mục dữ liệu bằng `/folder`

```
> /folder
· Đang mở hộp thoại chọn thư mục...
✓ Thư mục làm việc: D:\Dataset
· queries.json: 20 câu hỏi · 10 file Excel. Gõ /run để chạy.
```

`/folder` mở hộp thoại để chọn thư mục. Cũng có thể ghi thẳng đường dẫn: `/folder D:\Dataset`.
Thư mục được chọn phải chứa `queries.json` và `xlsx_files/` (xem [mục 6](#6-định-dạng-đầu-vào-và-đầu-ra)).

### Bước 4: Chạy bằng `/run`

```
> /run
[OK ] p4_q004 -> 'No' (4.63s)
[OK ] p4_q006 -> '7668' (6.22s)
...
Done: 20 questions in 34.7s (1.7s/question) | API calls 47 | tokens in 245396 out 31098 (13825/question) | cost $0.00946
✓ Đã lưu kết quả tại: D:\Dataset\submission.csv
```

Kết quả **tự động được lưu thành `submission.csv` ngay trong thư mục đã chọn**, và đường dẫn đầy đủ được
in ra khi chạy xong.

Thoát chương trình bằng `Ctrl+C` hoặc `/logout`. Key đã lưu vẫn được giữ.

---

## 5. Danh sách lệnh

| Lệnh | Tác dụng |
|---|---|
| `/api` | Nhập API key Qwen3.7 Flash: che ký tự, `Esc` để huỷ, kiểm tra ngay, sai thì nhập lại, hợp lệ thì tự lưu |
| `/folder` | Chọn thư mục dữ liệu (mở hộp thoại, hoặc ghi đường dẫn sau lệnh) |
| `/run` | Trả lời toàn bộ câu hỏi trong `queries.json`, lưu `submission.csv` vào thư mục đang chọn |
| `/file` | Chọn một tệp Excel để hỏi trực tiếp, sau đó gõ thẳng câu hỏi (không cần `/`) |
| `/new` | Bắt đầu phiên mới: bỏ thư mục, tệp và các câu đã hỏi |
| `/status` | Xem key (đã che), model, cấu hình, thư mục, tệp đang chọn, chi phí trong phiên |
| `/reset` | Đưa chương trình về trạng thái như lúc mới mở |
| `/help` | Hiện danh sách lệnh |
| `/logout` | Thoát về terminal (giữ key đã lưu) |

**Hỏi trực tiếp một tệp** (dùng để thử nhanh hoặc trình bày khi vấn đáp): chương trình nhớ 5 câu hỏi gần
nhất nên có thể hỏi nối tiếp.

```
> /file p4_t01
> Who has the highest score?
➜ Nga Anh Ngo
> Which row is that?
➜ 13
```

---

## 6. Định dạng đầu vào và đầu ra

### Đầu vào: thư mục dữ liệu (truyền bằng `--input`, hoặc chọn bằng `/folder`)

```
<thư_mục_dữ_liệu>/
├── queries.json
└── xlsx_files/
    ├── p4_t01.xlsx
    └── ...
```

`queries.json` là danh sách câu hỏi, mỗi phần tử gồm `id` (chuỗi hoặc số), `file_name`, `query` (tiếng Anh hoặc
ngôn ngữ khác):

```json
[
  {"id": "p4_q001", "file_name": "p4_t01.xlsx", "query": "Who was the second-youngest person ...?"}
]
```

Tệp Excel được tìm lần lượt ở `xlsx_files/<file_name>`, `<thư_mục_dữ_liệu>/<file_name>`, rồi trong các thư
mục con.

### Đầu ra

**`<thư_mục_dữ_liệu>/submission.csv`**: mã hoá UTF-8, hai cột `id,answer`, **mỗi `id` trong
`queries.json` đúng một dòng**, giữ nguyên thứ tự câu hỏi. Cột `answer` chỉ chứa đáp án cuối cùng, không kèm
giải thích. Câu nào không giải được vẫn có một dòng (đáp án rỗng), nên tệp luôn hợp lệ.

```csv
id,answer
p4_q001,Ngo
p4_q002,83
p4_q004,No
```

**`run_log.jsonl`** (cùng thư mục với `submission.csv`, kể cả khi chạy bằng Docker): mỗi dòng ứng với một câu hỏi, gồm đáp án, code Python đã
sinh, số lần thử, lỗi (nếu có) và thời gian xử lý. Dùng để kiểm tra và giải thích kết quả.

---

## 7. Tuân thủ quy định của đề

| Quy định | Cách đáp ứng |
|---|---|
| ZIP có `Dockerfile` ngay thư mục gốc | Có; `.dockerignore` loại bí mật và tệp tạm khỏi ảnh |
| Ảnh Docker Linux amd64, không GPU, chứa sẵn mã nguồn và thư viện | `python:3.12.15-slim-trixie`, cài `requirements.txt` (phiên bản cố định) lúc build (mục 1) |
| `ENTRYPOINT` nhận tham số chấm | `ENTRYPOINT ["python", "/app/main.py"]`, nhận `--input/--output`, đường dẫn đơn, hoặc tự tìm (mục 1) |
| Đầu vào là thư mục `xlsx_files/` + `queries.json` | Tham số `--input`, hoặc `/folder` ở giao diện tương tác |
| Xuất `submission.csv` đúng định dạng mẫu | `id,answer`, mỗi `id` một dòng, đáp án không kèm giải thích |
| Chạy được trên dữ liệu mới, không phụ thuộc dữ liệu mẫu | Không có đáp án, tên tệp hay đường dẫn nào được ghi cứng; xử lý mọi cấu trúc bảng bằng toạ độ ô Excel |
| LLM: Qwen3.7 Flash qua OpenRouter | Model `qwen/qwen3.7-flash`, endpoint `https://openrouter.ai/api/v1/chat/completions` |
| Khoá API cấu hình bên ngoài mã nguồn | Biến môi trường `OPENROUTER_API_KEY` (`docker run -e ...`); không nằm trong mã nguồn, tệp zip hay ảnh Docker |
| Chi phí ≤ 0,10 USD/câu hỏi (tính cả retry) | Đo thực tế khoảng **0,0005 USD/câu** (thấp hơn giới hạn hàng trăm lần) (mục 9). Văn bản gửi LLM được giới hạn để tệp lớn không làm vượt ngân sách |
| Thời gian ≤ 40 phút / 20 câu (6 vCPU, 12 GB RAM) | Đo thực tế trong Docker: **45 giây / 20 câu**, **86 giây / 30 câu** |
| Bộ nhớ ≤ 1 GB | Đã chạy đủ hai bộ dữ liệu trong container giới hạn `--memory=1g`. Không tải mô hình cục bộ; chỉ đọc tới ô cuối thực sự có dữ liệu nên tệp có định dạng thừa tới hàng triệu dòng không làm tràn bộ nhớ |
| Tệp zip ≤ 100 MB | Mã nguồn chỉ vài chục KB |

---

## 8. Nguyên lý hoạt động

```
queries.json
     │
     ▼   (xử lý song song nhiều câu)
┌──────────────────────────────────────────────────────────────────────────────┐
│ 1. excel_reader  Đọc .xlsx thành hai dạng:                                   │
│                  • Lưới ô có toạ độ Excel cho LLM đọc:  B12=8669,            │
│                    ô gộp ghi rõ phạm vi  D5[D5:F5]="Some college..."         │
│                  • DataFrame mỗi sheet cho code tính: index = số dòng Excel, │
│                    cột = chữ cái cột, ô gộp được điền lại giá trị            │
│ 2. solver        Gửi lưới ô + câu hỏi cho Qwen3.7 Flash → nhận code pandas   │
│ 3. solver        Chạy code → lấy biến `answer`. Lỗi thì gửi thông báo lỗi    │
│                  để LLM sửa (tối đa 3 lần)                                   │
│ 4. solver        Bỏ phiếu: giải 2 lượt độc lập; khác nhau thì giải lượt 3 và │
│                  lấy đáp án nhiều phiếu nhất. Mọi lượt đều lỗi → dự phòng:   │
│                  LLM đọc bảng và trả lời trực tiếp                           │
│ 5. normalize     Chuẩn hoá đáp án cho Exact Match (11.0 → 11, True → Yes) và │
│                  ép theo yêu cầu định dạng trong câu hỏi ("two decimal       │
│                  places" → 3.10, "integer, without commas" → 9017)           │
└──────────────────────────────────────────────────────────────────────────────┘
     │
     ▼
submission.csv  +  run_log.jsonl
```

**Các quyết định thiết kế chính**

- **Giữ nguyên toạ độ Excel thay vì đoán tiêu đề.** Bảng thật thường có tiêu đề nhiều tầng, ô gộp, nhiều
  bảng trên một sheet và dòng chú thích. Thay vì cố chuyển thành một bảng phẳng (dễ sai), chương trình đưa
  cho LLM lưới ô kèm toạ độ để LLM tự xác định đúng dòng, cột cần dùng.
- **LLM viết code, Python tính toán.** LLM chỉ cần hiểu câu hỏi và cấu trúc bảng; mọi phép tính do Python
  thực hiện trên toàn bộ dữ liệu nên không bị sai số học hay bỏ sót dòng.
- **Kiểm soát chi phí với tệp lớn.** Văn bản gửi LLM giới hạn khoảng 20.000 ký tự (dưới mốc 32.000 token mà
  OpenRouter tăng giá). Sheet quá dài được giữ phần đầu và phần cuối, lược phần giữa kèm ghi chú; code vẫn
  chạy trên đầy đủ mọi dòng.
- **Thinking tắt** (`reasoning: off`) để giảm thời gian và token, phù hợp tiêu chí xếp hạng phụ.
- **Không bao giờ làm hỏng tệp kết quả.** Lỗi ở một câu (tệp thiếu, lỗi mạng, code lỗi) chỉ ảnh hưởng câu
  đó; lỗi mạng và HTTP 429/5xx được tự động thử lại.

---

## 9. Kết quả đo trên dữ liệu công khai

Đo với đúng bản nộp (ảnh build từ `AI26C0102.zip`, phiên bản cố định), trong container giới hạn
`--memory=1g --cpus=6`, cấu hình mặc định, trên thư mục chỉ gồm `queries.json` và `xlsx_files/` (không có đáp án):

| Bộ dữ liệu | Số câu đúng (Exact Match) | Thời gian | Chi phí |
|---|---|---|---|
| Lần 1: 20 câu, 10 tệp, tiếng Anh | **19/20** | 45,3 giây | 0,0104 USD |
| Lần 2: 30 câu, 15 tệp, Anh/Việt/Pháp/Hàn/Trung | **30/30** | 85,9 giây | 0,0132 USD |

Mỗi câu dùng khoảng 13.000–15.000 token (gồm cả bỏ phiếu và retry). Qua nhiều lần chạy, kết quả dao động trong
khoảng 18–20/20 (lần 1) và 26–30/30 (lần 2), vì một số câu hỏi có thể hiểu theo nhiều cách.

Ngoài ra đã kiểm thử với một tệp tự tạo 5.000 dòng: các câu hỏi tổng, đếm và tra cứu dòng nằm trong phần
bị lược đều trả lời đúng, chi phí dưới 0,001 USD/câu.

Kết quả trên bộ kiểm thử ẩn có thể khác.

---

## 10. Cấu trúc mã nguồn

```
AI26C0102.zip
├── Dockerfile            Ảnh Docker Linux amd64 (ENTRYPOINT = main.py)
├── .dockerignore         Loại bí mật, tệp tạm khỏi ảnh
├── main.py               Điểm vào: nhận tham số chấm, hoặc mở giao diện tương tác khi chạy ở terminal
├── requirements.txt      Thư viện cần cài (cố định đúng phiên bản đã kiểm thử)
├── README.md
└── chaldea/
    ├── shell.py          Giao diện tương tác: các lệnh "/", gợi ý khi gõ, hộp thoại chọn thư mục
    ├── runner.py         Chạy toàn bộ queries.json song song, ghi submission.csv và log
    ├── excel_reader.py   Đọc Excel → lưới ô cho LLM + DataFrame cho code
    ├── solver.py         Prompt, trích và chạy code, sửa lỗi, bỏ phiếu, dự phòng
    ├── llm.py            Gọi Qwen3.7 Flash, kiểm tra key, thử lại khi lỗi, đếm token/chi phí
    ├── normalize.py      Chuẩn hoá đáp án và ép định dạng theo câu hỏi
    └── config.py         Cấu hình: model, endpoint, nạp và lưu API key, tuỳ chọn
```

---

## 11. Tham số dòng lệnh

```bash
python main.py [thư_mục_dữ_liệu] [tệp_ra|thư_mục_ra] [--input ...] [--output ...] [--workers N] [--log tệp]
```

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `--input`, `-i` (hoặc đường dẫn thứ nhất) | Tự tìm (mục 1) | Thư mục chứa `queries.json` và `xlsx_files/`, hoặc chính tệp `queries.json` |
| `--output`, `-o` (hoặc đường dẫn thứ hai) | `<thư_mục_dữ_liệu>/submission.csv` | Tệp kết quả; nếu là thư mục thì ghi `<thư_mục>/submission.csv` |
| `--workers` | `8` | Số câu xử lý song song |
| `--log` | `run_log.jsonl` cạnh tệp kết quả | Tệp log chi tiết từng câu (code đã sinh, lỗi, thời gian) |

API key lấy từ biến môi trường `OPENROUTER_API_KEY`, hoặc key đã lưu bằng `/api` (biến môi trường được ưu tiên).
Chạy ở terminal mà không có tham số nào thì mở giao diện tương tác; chạy không có terminal (Docker, script) thì
xử lý luôn theo bảng ở mục 1.

| Mã thoát | Ý nghĩa |
|---|---|
| `0` | Chạy xong, đã ghi tệp kết quả |
| `2` | Không tìm thấy `queries.json`, thiếu API key (vẫn ghi tệp đáp án rỗng) hoặc tham số sai |

Các tuỳ chọn nâng cao (mặc định đã được chọn cho bài nộp, không cần thay đổi) có thể chỉnh bằng biến môi
trường: `CHALDEA_WORKERS` (8), `CHALDEA_VOTES` (3; `1` = tắt bỏ phiếu), `CHALDEA_MAX_ATTEMPTS` (3),
`CHALDEA_REASONING` (`off`).

---

## 12. Xử lý sự cố

| Hiện tượng | Nguyên nhân và cách xử lý |
|---|---|
| `permission denied ... docker.sock` (Linux) | Thêm `sudo` ở đầu lệnh `docker`, hoặc thêm người dùng vào nhóm `docker` |
| Chạy chậm trên Mac chip Apple (M1/M2/M3…) | Ảnh là Linux amd64 theo yêu cầu đề nên Docker phải giả lập; vẫn cho kết quả đúng, chỉ chậm hơn |
| `Không tìm thấy queries.json trong: ...` | Kiểm tra `-v <thư_mục>:/data` trỏ đúng thư mục **chứa** `queries.json` |
| `Thiếu API key: đặt biến môi trường OPENROUTER_API_KEY` | Thêm `-e OPENROUTER_API_KEY="sk-or-v1-..."` vào `docker run` |
| `Không ghi được /data/submission.csv; ghi vào ...` | Thư mục dữ liệu chỉ đọc; mount thêm `-v <thư_mục_ra>:/output`, hoặc lấy tệp ở đường dẫn được in ra |
| `/api` báo `401 Unauthorized` | Key sai hoặc đã bị thu hồi; nhập lại key khác |
| `/api` báo lỗi `402` | Tài khoản OpenRouter hết số dư |
| `/folder` báo không thấy `queries.json` | Chọn thư mục **chứa** `queries.json`, không phải thư mục `xlsx_files/` |
| Hộp thoại chọn thư mục không hiện | Có thể bị che sau cửa sổ khác (xem thanh taskbar), hoặc ghi thẳng đường dẫn: `/folder D:\Dataset` |
| `[ERR] <id> -> ''` | Câu đó không giải được; xem chi tiết lỗi trong `run_log.jsonl`. Tệp kết quả vẫn hợp lệ |
| `ModuleNotFoundError` | Chưa chạy `pip install -r requirements.txt` (hoặc chưa kích hoạt môi trường ảo) |
| Gõ `/` không hiện danh sách gợi ý | Terminal không hỗ trợ; gõ đầy đủ tên lệnh (`/help` để xem) vẫn chạy bình thường |
| Tiếng Việt trên màn hình bị lỗi font | Không ảnh hưởng tệp kết quả (luôn ghi UTF-8) |
